"""Sprite library: loads assets/sprites.yaml into Activities of Poses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ASSETS = Path(__file__).resolve().parent.parent / "assets"


@dataclass(frozen=True)
class Pose:
    key: str  # "<sheet>/<nn>"
    path: Path
    scale: float  # multiplier applied on top of the display scale


@dataclass(frozen=True)
class Activity:
    name: str
    poses: tuple[Pose, ...]
    mode: str = "loop"  # loop | oneshot
    hold: tuple[float, float] = (4.0, 8.0)
    motion: str = "breathe"
    ambient: str | None = None  # group it's picked from as a random gesture: idle | coding


@dataclass
class SpriteLibrary:
    reference_height: float
    activities: dict[str, Activity] = field(default_factory=dict)

    def get(self, name: str) -> Activity:
        return self.activities[name]

    def ambient(self, group: str = "idle") -> list[Activity]:
        return [a for a in self.activities.values() if a.ambient == group]

    def poses(self) -> list[Pose]:
        seen = {}
        for activity in self.activities.values():
            for pose in activity.poses:
                seen[pose.key] = pose
        return list(seen.values())


def ambient_group(value) -> str | None:
    """`ambient: true` means the idle group; a string names another group."""
    if value is True:
        return "idle"
    return value or None


def load_library(path: Path = ASSETS / "sprites.yaml") -> SpriteLibrary:
    data = yaml.safe_load(path.read_text())
    sprite_dir = path.parent / "sprites"
    sheets = data.get("sheets", {})

    def make_pose(key: str) -> Pose:
        sheet, nn = key.split("/")
        conf = sheets.get(sheet, {})
        scale = conf.get("scale", 1.0) * conf.get("pose_scale", {}).get(nn, 1.0)
        pose_path = sprite_dir / sheet / f"{nn}.png"
        if not pose_path.exists():
            raise FileNotFoundError(f"{pose_path} missing; run tools/slice_sheets.py")
        return Pose(key, pose_path, scale)

    raw = data["activities"]
    library = SpriteLibrary(reference_height=data.get("reference_height", 380))
    for name, conf in raw.items():
        library.activities[name] = Activity(
            name=name,
            poses=tuple(make_pose(k) for k in conf.get("poses", [])),
            mode=conf.get("mode", "loop"),
            hold=tuple(conf.get("hold", (4.0, 8.0))),
            motion=conf.get("motion", "breathe"),
            ambient=ambient_group(conf.get("ambient")),
        )

    # Resolve fallbacks for activities without art yet.
    for name, conf in raw.items():
        fallback = conf.get("fallback")
        if not library.activities[name].poses and fallback:
            library.activities[name] = library.activities[fallback]
    return library
