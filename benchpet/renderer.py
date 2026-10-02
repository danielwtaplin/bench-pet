"""Draws the pet: holds poses, crossfades between them, adds procedural motion.

The sheets are distinct poses rather than frame sequences, so liveliness comes
from timing (hold, crossfade) and small transforms (breathing, bobbing, sway).
"""

from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPixmap, QRegion, QTransform
from PySide6.QtWidgets import QWidget

from benchpet.sprites import Activity, Pose, SpriteLibrary

FPS = 60
CROSSFADE = 0.25  # seconds
MASK_SLOP = 12  # px of headroom (and input-mask growth) for sway/bob offsets


class PetWidget(QWidget):
    activity_finished = Signal(object)  # Activity
    pose_changed = Signal()

    def __init__(self, library: SpriteLibrary, height: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.library = library
        self.rng = random.Random()
        self._pixmaps: dict[str, QPixmap] = {}
        self.activity: Activity | None = None
        self.pose: Pose | None = None
        self.prev_pose: Pose | None = None
        self._index = 0
        self._pose_until = 0.0
        self._fade_start = -CROSSFADE
        self._finished = False
        self._t0 = time.monotonic()
        self.paused = False
        self.set_display_height(height)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000 // FPS)

    # --- sizing ----------------------------------------------------------

    def set_display_height(self, height: int) -> None:
        self.display_height = height
        self._pixmaps.clear()
        dpr = self.devicePixelRatioF()
        base = height / self.library.reference_height
        for pose in self.library.poses():
            src = QPixmap(str(pose.path))
            scale = base * pose.scale * dpr
            pm = src.scaled(round(src.width() * scale), round(src.height() * scale),
                            Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self._pixmaps[pose.key] = pm
        w = max(pm.deviceIndependentSize().width() for pm in self._pixmaps.values())
        h = max(pm.deviceIndependentSize().height() for pm in self._pixmaps.values())
        # Headroom for bob/dance offsets.
        self.setFixedSize(math.ceil(w) + 2 * MASK_SLOP, math.ceil(h) + 2 * MASK_SLOP)
        self.update()

    def pose_rect(self, pose: Pose | None = None) -> QRect:
        """Where a pose is drawn (before motion): bottom-centred in the widget."""
        pose = pose or self.pose
        if pose is None:
            return QRect()
        size = self._pixmaps[pose.key].deviceIndependentSize()
        w, h = round(size.width()), round(size.height())
        return QRect((self.width() - w) // 2, self.height() - MASK_SLOP - h, w, h)

    def input_region(self) -> QRegion:
        """Opaque pixels of the current (and fading-out) pose, grown slightly."""
        region = QRegion()
        for pose in {self.pose, self.prev_pose} - {None}:
            pm = self._pixmaps[pose.key]
            # mask() is in device pixels; scale back to logical coordinates.
            bitmap = pm.mask()
            dpr = pm.devicePixelRatio()
            mask = QRegion(bitmap)
            if dpr != 1:
                mask = QTransform.fromScale(1 / dpr, 1 / dpr).map(mask)
            r = self.pose_rect(pose)
            mask.translate(r.topLeft())
            for dx, dy in ((0, 0), (MASK_SLOP, 0), (-MASK_SLOP, 0), (0, -MASK_SLOP)):
                region = region.united(mask.translated(dx, dy))
        return region

    # --- activity playback -----------------------------------------------

    def set_activity(self, activity: Activity) -> None:
        self.activity = activity
        self._finished = False
        if activity.mode == "loop":
            # Keep the current pose if it belongs to the new activity, otherwise pick one.
            current = [i for i, p in enumerate(activity.poses) if p is self.pose]
            self._index = current[0] if current else self.rng.randrange(len(activity.poses))
        else:
            self._index = 0
        self._show(activity.poses[self._index])

    def _show(self, pose: Pose) -> None:
        now = time.monotonic()
        if pose is not self.pose:
            self.prev_pose = self.pose
            self.pose = pose
            self._fade_start = now
            self.pose_changed.emit()
        self._pose_until = now + self.rng.uniform(*self.activity.hold)

    def _advance(self) -> None:
        activity = self.activity
        if activity.mode == "oneshot":
            if self._index + 1 >= len(activity.poses):
                if not self._finished:
                    self._finished = True
                    self.activity_finished.emit(activity)
                return
            self._index += 1
        elif len(activity.poses) > 1:
            choices = [i for i in range(len(activity.poses)) if i != self._index]
            self._index = self.rng.choice(choices)
        self._show(activity.poses[self._index])

    def _tick(self) -> None:
        if self.activity is None or self.paused:
            return
        now = time.monotonic()
        if now >= self._pose_until:
            self._advance()
        if self.prev_pose is not None and now - self._fade_start >= CROSSFADE:
            self.prev_pose = None
            self.pose_changed.emit()
        self.update()

    # --- painting --------------------------------------------------------

    def _motion(self, t: float) -> QTransform:
        """Transform about the feet (bottom-centre of the pose)."""
        style = self.activity.motion if self.activity else "none"
        dy = angle = 0.0
        sy = 1.0
        if style == "breathe":
            sy = 1 + 0.008 * math.sin(2 * math.pi * t / 3.5)
        elif style == "bob":  # nodding along, ~100 bpm
            dy = -2.5 * abs(math.sin(math.pi * t * 100 / 60))
            angle = 0.8 * math.sin(math.pi * t * 50 / 60)
        elif style == "dance":
            dy = -6 * abs(math.sin(math.pi * t * 120 / 60))
            angle = 3 * math.sin(math.pi * t * 60 / 60)
        elif style == "walk":
            dy = -3 * abs(math.sin(math.pi * t / 0.35))
            angle = 1.5 * math.sin(math.pi * t / 0.35)
        r = self.pose_rect()
        foot = QPointF(r.center().x(), r.bottom())
        tr = QTransform()
        tr.translate(foot.x(), foot.y() + dy)
        tr.rotate(angle)
        tr.scale(1, sy)
        tr.translate(-foot.x(), -foot.y())
        return tr

    def paintEvent(self, _event) -> None:
        if self.pose is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        t = time.monotonic() - self._t0
        p.setTransform(self._motion(t))
        fade = min((time.monotonic() - self._fade_start) / CROSSFADE, 1.0)
        if self.prev_pose is not None and fade < 1.0:
            # Ease the old pose out more slowly so the overlap doesn't dip in opacity.
            p.setOpacity(1 - fade * fade)
            p.drawPixmap(self.pose_rect(self.prev_pose).topLeft(), self._pixmaps[self.prev_pose.key])
        p.setOpacity(fade)
        p.drawPixmap(self.pose_rect().topLeft(), self._pixmaps[self.pose.key])
        p.end()
