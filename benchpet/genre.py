"""Genre lookup for the now-playing track via MusicBrainz (free, no API key).

MPRIS players rarely report a genre (browsers never do), so the track is searched by
title and artist. MusicBrainz seldom tags individual recordings, so genres fall back from
the recording to its album (release group) and then to the artist. When the title finds no
recording (players and MusicBrainz often spell tracks differently), the album and artist are
searched by name instead.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

API = "https://musicbrainz.org/ws/2"
USER_AGENT = "bench-pet/0.1"
MIN_INTERVAL = 1.1  # MusicBrainz allows one request per second
MIN_SCORE = 90  # search match confidence, 0-100
MAX_GENRES = 3
CACHE_SIZE = 200
RETRY_DELAYS = (3, 10, 30)  # seconds to back off when MusicBrainz is busy (503/429) or unreachable
RETRY_AFTER_FAILURE = 60  # a track whose lookup failed is tried again on its next update after this

FEAT = re.compile(r"\s*[(\[](?:feat|ft|featuring|with)\.?\s[^)\]]*[)\]]", re.IGNORECASE)
LUCENE_SPECIAL = re.compile(r'([\\"])')


def _quoted(s: str) -> str:
    return '"' + LUCENE_SPECIAL.sub(r"\\\1", s) + '"'


def _main_artist(artist: str) -> str:
    return artist.split(",")[0].strip()


def search_query(title: str, artist: str, album: str = "") -> str:
    """Lucene query for a recording; featured artists dropped from the title."""
    parts = [f"recording:{_quoted(FEAT.sub('', title).strip())}"]
    if artist:
        parts.append(f"artist:{_quoted(_main_artist(artist))}")
    if album:
        parts.append(f"release:{_quoted(album)}")
    return " AND ".join(parts)


def album_query(album: str, artist: str) -> str:
    """Lucene query for an album (release group) by name and main artist."""
    return f"releasegroup:{_quoted(album)} AND artist:{_quoted(_main_artist(artist))}"


def best_match(results: dict, kind: str) -> dict | None:
    """Highest-scoring `kind` (e.g. "artists") at or above MIN_SCORE."""
    good = [r for r in results.get(kind, []) if r.get("score", 0) >= MIN_SCORE]
    return max(good, key=lambda r: r.get("score", 0)) if good else None


def best_recording(results: dict, album: str = "") -> dict | None:
    """Highest-scoring recording at or above MIN_SCORE; ties go to one on `album`."""
    def on_album(rec: dict) -> bool:
        return any(r.get("title", "").casefold() == album.casefold() for r in rec.get("releases", []))

    good = [r for r in results.get("recordings", []) if r.get("score", 0) >= MIN_SCORE]
    good.sort(key=lambda r: (-r.get("score", 0), not (album and on_album(r))))
    return good[0] if good else None


def release_group_id(recording: dict, album: str = "") -> str | None:
    """The recording's album: the release matching `album`, else the first official album."""
    releases = recording.get("releases", [])
    ranked = sorted(releases, key=lambda r: (
        not (album and r.get("title", "").casefold() == album.casefold()),
        r.get("release-group", {}).get("primary-type") != "Album",
        r.get("status") != "Official"))
    for release in ranked:
        if rg := release.get("release-group", {}).get("id"):
            return rg
    return None


def top_genres(entity: dict) -> list[str]:
    genres = sorted(entity.get("genres", []), key=lambda g: -g.get("count", 0))
    return [g["name"] for g in genres[:MAX_GENRES]]


def _key(title: str, artist: str) -> tuple[str, str]:
    return title.casefold(), artist.casefold()


class GenreLookup(QObject):
    ready = Signal(str, str, list)  # title, artist, genres (possibly empty)
    _failed = Signal(str, str)  # title, artist: the lookup gave up; not cached

    def __init__(self):
        super().__init__()
        self._cache: dict[tuple[str, str], list[str]] = {}
        self._pending: set[tuple[str, str]] = set()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="genre")
        self._failures: dict[tuple[str, str], float] = {}  # key → monotonic time it failed
        self._last_request = 0.0
        self.ready.connect(self._store)
        self._failed.connect(self._forget)

    def get(self, title: str, artist: str, album: str = "") -> list[str] | None:
        """Genres if known (empty when MusicBrainz has none); None while a lookup runs,
        whose result arrives through `ready`."""
        if not title:
            return []
        key = _key(title, artist)
        if key in self._cache:
            return self._cache[key]
        if time.monotonic() - self._failures.get(key, -RETRY_AFTER_FAILURE) < RETRY_AFTER_FAILURE:
            return None
        if key not in self._pending:
            self._pending.add(key)
            self._pool.submit(self._lookup, title, artist, album)
        return None

    def stop(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _store(self, title: str, artist: str, genres: list) -> None:
        key = _key(title, artist)
        self._pending.discard(key)
        self._failures.pop(key, None)
        self._cache[key] = genres
        while len(self._cache) > CACHE_SIZE:
            self._cache.pop(next(iter(self._cache)))

    def _forget(self, title: str, artist: str) -> None:
        key = _key(title, artist)
        self._pending.discard(key)
        self._failures[key] = time.monotonic()

    def _lookup(self, title: str, artist: str, album: str) -> None:  # worker thread
        genres: list[str] = []
        try:
            found = self._get("recording", {"query": search_query(title, artist, album), "limit": 5})
            if album and not found.get("recordings"):  # album names from players can be off
                found = self._get("recording", {"query": search_query(title, artist), "limit": 5})
            recording = best_recording(found, album)
            if recording:
                genres = top_genres(self._get(f"recording/{recording['id']}", {"inc": "genres"}))
                if not genres and (rg := release_group_id(recording, album)):
                    genres = top_genres(self._get(f"release-group/{rg}", {"inc": "genres"}))
                credits = recording.get("artist-credit", [])
                if not genres and credits:
                    genres = top_genres(self._get(f"artist/{credits[0]['artist']['id']}", {"inc": "genres"}))
            elif artist:
                # Players' titles can differ from MusicBrainz's ("Ritual of Autophagia" vs
                # "Ritual Autophagia"), so fall back to searching the album, then the artist.
                if album and (rg := best_match(self._get("release-group", {"query": album_query(album, artist),
                                                                           "limit": 5}), "release-groups")):
                    genres = top_genres(self._get(f"release-group/{rg['id']}", {"inc": "genres"}))
                if not genres and (match := best_match(self._get(
                        "artist", {"query": f"artist:{_quoted(_main_artist(artist))}", "limit": 5}), "artists")):
                    genres = top_genres(self._get(f"artist/{match['id']}", {"inc": "genres"}))
            log.debug("genre: %s — %s → %s", title, artist, genres or "none")
        except Exception as e:
            log.warning("genre: lookup for %s — %s failed: %s", title, artist, e)
            self._failed.emit(title, artist)
            return
        self.ready.emit(title, artist, genres)

    def _get(self, path: str, params: dict) -> dict:
        for delay in RETRY_DELAYS:
            try:
                return self._request(path, params)
            except urllib.error.HTTPError as e:
                if e.code not in (429, 503):
                    raise
                log.info("genre: MusicBrainz busy (%s), retrying in %ss", e.code, delay)
            except (urllib.error.URLError, TimeoutError) as e:
                log.info("genre: %s, retrying in %ss", e, delay)
            time.sleep(delay)
        return self._request(path, params)

    def _request(self, path: str, params: dict) -> dict:
        wait = self._last_request + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        url = f"{API}/{path}?" + urllib.parse.urlencode({**params, "fmt": "json"})
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as resp:
            return json.load(resp)
