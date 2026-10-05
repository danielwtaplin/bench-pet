from benchpet.genre import best_recording, release_group_id, search_query, top_genres


def test_search_query_drops_featured_artists_and_escapes_quotes():
    assert search_query('Felony Abuse Of A Corpse (feat. PeelingFlesh)', "Sanguisugabogg, PeelingFlesh") == \
        'recording:"Felony Abuse Of A Corpse" AND artist:"Sanguisugabogg"'
    assert search_query('Say "Hi"', "", "LP") == r'recording:"Say \"Hi\"" AND release:"LP"'


def test_best_recording_needs_a_confident_match_and_prefers_the_album():
    recs = {"recordings": [
        {"id": "single", "score": 100, "releases": [{"title": "Single"}]},
        {"id": "album", "score": 100, "releases": [{"title": "The LP"}]},
        {"id": "weak", "score": 60},
    ]}
    assert best_recording(recs, "the lp")["id"] == "album"
    assert best_recording({"recordings": [{"id": "weak", "score": 60}]}) is None


def test_release_group_prefers_matching_then_official_album():
    rec = {"releases": [
        {"title": "Comp", "status": "Official", "release-group": {"id": "c", "primary-type": "Compilation"}},
        {"title": "LP", "status": "Bootleg", "release-group": {"id": "b", "primary-type": "Album"}},
        {"title": "LP", "status": "Official", "release-group": {"id": "a", "primary-type": "Album"}},
    ]}
    assert release_group_id(rec, "LP") == "a"
    assert release_group_id(rec) == "a"
    assert release_group_id({"releases": []}) is None


def test_top_genres_by_vote_count():
    entity = {"genres": [{"name": "metal", "count": 1}, {"name": "death metal", "count": 3},
                         {"name": "grind", "count": 2}, {"name": "rock", "count": 0}]}
    assert top_genres(entity) == ["death metal", "grind", "metal"]
    assert top_genres({}) == []


def test_busy_responses_are_retried_and_failures_not_cached(monkeypatch):
    import urllib.error

    from PySide6.QtCore import QCoreApplication

    import benchpet.genre as genre

    app = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(genre, "RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(genre, "MIN_INTERVAL", 0)
    responses = [urllib.error.HTTPError("u", 503, "busy", {}, None),
                 {"recordings": [{"id": "r", "score": 100, "releases": []}]},
                 {"genres": [{"name": "death metal", "count": 2}]}]

    def fake_request(self, path, params):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(genre.GenreLookup, "_request", fake_request)
    lookup = genre.GenreLookup()
    got = []
    lookup.ready.connect(lambda *a: (got.append(a), app.quit()))
    assert lookup.get("Song", "Artist") is None
    app.exec()
    assert got == [("Song", "Artist", ["death metal"])]
    assert lookup.get("Song", "Artist") == ["death metal"]

    # A lookup that keeps failing isn't cached as "no genre", and is retried later.
    def always_busy(self, path, params):
        raise urllib.error.HTTPError("u", 503, "busy", {}, None)

    monkeypatch.setattr(genre.GenreLookup, "_request", always_busy)
    lookup._failed.connect(app.quit)
    assert lookup.get("Other", "Artist") is None
    app.exec()
    assert ("other", "artist") not in lookup._cache
    assert lookup.get("Other", "Artist") is None and ("other", "artist") not in lookup._pending
    monkeypatch.setattr(genre, "RETRY_AFTER_FAILURE", 0)
    lookup.get("Other", "Artist")
    assert ("other", "artist") in lookup._pending
    lookup.stop()


def test_unmatched_title_falls_back_to_album_then_artist_search(monkeypatch):
    from PySide6.QtCore import QCoreApplication

    import benchpet.genre as genre

    app = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(genre, "MIN_INTERVAL", 0)
    responses = {
        "recording": {"recordings": []},  # the player's title isn't MusicBrainz's spelling
        "release-group": {"release-groups": [{"id": "rg", "score": 100}]},
        "release-group/rg": {"genres": []},
        "artist": {"artists": [{"id": "weak", "score": 50}, {"id": "a", "score": 100}]},
        "artist/a": {"genres": [{"name": "death metal", "count": 2}]},
    }
    paths = []

    def fake_request(self, path, params):
        paths.append(path)
        return responses[path]

    monkeypatch.setattr(genre.GenreLookup, "_request", fake_request)
    lookup = genre.GenreLookup()
    got = []
    lookup.ready.connect(lambda *a: (got.append(a), app.quit()))
    lookup.get("Ritual of Autophagia (feat. Todd Jones)", "Sanguisugabogg, Todd Jones", "Hideous Aftermath")
    app.exec()
    assert got[0][2] == ["death metal"]
    assert paths == ["recording", "recording", "release-group", "release-group/rg", "artist", "artist/a"]
    assert genre.album_query("Hideous Aftermath", "Sanguisugabogg, Todd Jones") == \
        'releasegroup:"Hideous Aftermath" AND artist:"Sanguisugabogg"'
    lookup.stop()
