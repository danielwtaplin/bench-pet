"""Album art for the now-playing tile, from an MPRIS artUrl.

Browsers hand over a file:// path to a temp file; Spotify and others give an https://
URL, which is fetched in the background and cached.
"""

from __future__ import annotations

import glob
import os

from PySide6.QtCore import QObject, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

CACHE_SIZE = 20


def local_path(url: str) -> str | None:
    """Filesystem path for a file:// URL. A Flatpak app (e.g. Chrome) reports paths in its
    private /tmp, which the host sees under /run/user/<uid>/.flatpak/<app>/tmp."""
    path = QUrl(url).toLocalFile()
    if os.path.exists(path):
        return path
    if path.startswith("/tmp/"):
        runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        rel = glob.escape(path.removeprefix("/tmp/"))
        return next(iter(glob.glob(f"{glob.escape(runtime)}/.flatpak/*/tmp/{rel}")), None)
    return None


def rounded_tile(pixmap: QPixmap, size: int, radius: float = 6) -> QPixmap:
    """Centre-crop `pixmap` to a square of `size` px with rounded corners."""
    scaled = pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    tile = QPixmap(size, size)
    tile.fill(Qt.transparent)
    p = QPainter(tile)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    p.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    p.end()
    return tile


class AlbumArt(QObject):
    ready = Signal(str)  # url whose image just finished downloading

    def __init__(self):
        super().__init__()
        self._cache: dict[str, QPixmap] = {}
        self._pending: set[str] = set()
        self._nam: QNetworkAccessManager | None = None

    def get(self, url: str) -> QPixmap | None:
        """The image for `url` if it's available now. Remote images that aren't cached yet
        start downloading and announce themselves through `ready`."""
        if not url:
            return None
        if url.startswith("file://"):
            # Not cached: browsers reuse temp file names across tracks.
            path = local_path(url)
            pixmap = QPixmap(path) if path else QPixmap()
            return None if pixmap.isNull() else pixmap
        if url in self._cache:
            return self._cache[url]
        if url.startswith(("http://", "https://")) and url not in self._pending:
            self._fetch(url)
        return None

    def _fetch(self, url: str) -> None:
        if self._nam is None:
            self._nam = QNetworkAccessManager(self)
        self._pending.add(url)
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                             QNetworkRequest.NoLessSafeRedirectPolicy)
        reply = self._nam.get(request)
        reply.finished.connect(lambda: self._on_finished(url, reply))

    def _on_finished(self, url: str, reply: QNetworkReply) -> None:
        self._pending.discard(url)
        pixmap = QPixmap()
        if reply.error() == QNetworkReply.NoError and pixmap.loadFromData(reply.readAll()):
            self._cache[url] = pixmap
            while len(self._cache) > CACHE_SIZE:
                self._cache.pop(next(iter(self._cache)))
            self.ready.emit(url)
        reply.deleteLater()
