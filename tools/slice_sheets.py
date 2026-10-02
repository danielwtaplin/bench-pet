"""Slice the spritesheets in refs/ into cleaned, per-pose PNGs.

Each sheet is a grid of distinct poses. Cells are cut using float bounds
(4-column sheets have 313.5px cells), cleaned up (alpha snapping, haze removal,
colour-fringe desaturation, speckle removal) and cropped to their content.

Output: assets/sprites/<sheet>/<nn>.png plus assets/sprites/manifest.json with
each pose's size, so the renderer can bottom-align poses on a shared baseline.

Run: .venv/bin/python tools/slice_sheets.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
REFS = ROOT / "refs"
OUT = ROOT / "assets" / "sprites"


@dataclass(frozen=True)
class Sheet:
    name: str
    file: str
    cols: int
    rows: int
    skip: tuple[int, ...] = ()
    matte: str | None = None  # "black": opaque sheet on a black background to key out


SHEETS = [
    Sheet("generic_a", "desk_pet_spritesheet.png", 3, 3),
    Sheet("generic_b", "desk_pet_spritesheet_1.png", 3, 3),
    Sheet("music", "desk_spritesheet_music.png", 3, 3),
    Sheet("laptop", "desk_pet_spritesheet_laptop.png", 4, 3),
    Sheet("coffee", "desk_spritesheet_coffee.png", 4, 4),
    # Cell 11 has an opaque sky background; skip until it's redrawn.
    Sheet("weather", "desk_spritesheet_weather.png", 4, 3, skip=(11,)),
    Sheet("ai", "desk_pet_spritesheet_ai_agent.png", 4, 3, matte="black"),
    Sheet("stress", "desk_pet_spritesheet_stresspng.png", 4, 4, matte="black"),
    Sheet("coding", "desk_pet_spritesheet_coding.png", 4, 4, matte="black"),
]

ALPHA_FLOOR = 32  # below this is haze → fully transparent
ALPHA_SNAP = 240  # at/above this is body → fully opaque
FRINGE_CHROMA = 60  # semi-transparent pixels more saturated than this get greyed
MIN_COMPONENT_FRACTION = 0.01  # drop blobs smaller than 1% of the largest one
PAD = 2
BLACK_MAX = 8  # max channel value counted as background on black-matte sheets
MIN_HOLE = 400  # enclosed black areas at least this big are background, not clothing
EDGE_BAND = 2  # px around the background where alpha is estimated from brightness
EDGE_RAMP = 60  # brightness above BLACK_MAX at which an edge pixel is fully opaque


def cell_bounds(size: int, count: int, index: int) -> tuple[int, int]:
    """Integer [start, end) bounds of cell `index` when `size` px is split into `count`."""
    return round(index * size / count), round((index + 1) * size / count)


def clean_cell(rgba: np.ndarray) -> np.ndarray:
    rgba = rgba.copy()
    alpha = rgba[..., 3].astype(np.int32)
    alpha[alpha < ALPHA_FLOOR] = 0
    alpha[alpha >= ALPHA_SNAP] = 255

    # Remove speckles: keep only connected blobs of meaningful size.
    labels, n = ndimage.label(alpha > 0)
    if n > 1:
        sizes = ndimage.sum(np.ones_like(alpha), labels, range(1, n + 1))
        keep = np.zeros(n + 1, dtype=bool)
        keep[1:] = sizes >= sizes.max() * MIN_COMPONENT_FRACTION
        alpha[~keep[labels]] = 0

    # Desaturate coloured fringes on semi-transparent edge pixels.
    rgb = rgba[..., :3].astype(np.int32)
    chroma = rgb.max(-1) - rgb.min(-1)
    fringe = (alpha > 0) & (alpha < 255) & (chroma > FRINGE_CHROMA)
    luma = (rgb[..., 0] * 299 + rgb[..., 1] * 587 + rgb[..., 2] * 114) // 1000
    rgb[fringe] = luma[fringe][:, None]

    rgba[..., :3] = rgb.astype(np.uint8)
    rgba[..., 3] = alpha.astype(np.uint8)
    rgba[alpha == 0, :3] = 0
    return rgba


def crop_to_content(rgba: np.ndarray) -> np.ndarray | None:
    ys, xs = np.nonzero(rgba[..., 3])
    if len(ys) == 0:
        return None
    y0, y1 = max(ys.min() - PAD, 0), min(ys.max() + 1 + PAD, rgba.shape[0])
    x0, x1 = max(xs.min() - PAD, 0), min(xs.max() + 1 + PAD, rgba.shape[1])
    return rgba[y0:y1, x0:x1]


def key_black(rgb: np.ndarray) -> np.ndarray:
    """RGBA from an opaque image on black: remove the background, keep dark clothing.

    Background is near-black connected to the border, plus large enclosed near-black
    regions (gaps between arms and body). Small dark clumps (shirt shadows, shoes) stay.
    Pixels just inside the background edge get alpha from their brightness and are
    un-premultiplied, so edges don't keep a black halo.
    """
    rgb = rgb[..., :3].astype(np.float32)
    dark = rgb.max(-1) <= BLACK_MAX
    labels, n = ndimage.label(dark)
    sizes = ndimage.sum(np.ones(dark.shape), labels, range(1, n + 1))
    border = set(np.unique(np.concatenate(
        [labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    keep = np.zeros(n + 1, dtype=bool)
    for label in range(1, n + 1):
        keep[label] = label in border or sizes[label - 1] >= MIN_HOLE
    background = keep[labels]

    alpha = np.where(background, 0.0, 1.0)
    band = ndimage.binary_dilation(background, iterations=EDGE_BAND) & ~background
    brightness = rgb.max(-1)
    alpha[band] = np.clip((brightness[band] - BLACK_MAX) / EDGE_RAMP, 0, 1)
    out = np.zeros(rgb.shape[:2] + (4,), dtype=np.uint8)
    safe = np.maximum(alpha, 1e-3)[..., None]
    out[..., :3] = np.clip(np.where(band[..., None], rgb / safe, rgb), 0, 255).astype(np.uint8)
    out[..., 3] = (alpha * 255).astype(np.uint8)
    return out


def cell_index(cy: float, cx: float, h: int, w: int, rows: int, cols: int) -> int:
    """Grid cell containing point (cy, cx)."""
    r = min(int(cy * rows / h), rows - 1)
    c = min(int(cx * cols / w), cols - 1)
    return r * cols + c


def segment_sheet(img: np.ndarray, rows: int, cols: int) -> dict[int, np.ndarray]:
    """Map cell index → boolean mask of the pixels belonging to that pose.

    Poses don't sit neatly inside uniform cells on every sheet (coffee rows are
    uneven), so group pixels into blobs and assign each blob to the cell its
    centroid falls in. Blobs are found on a dilated mask so hair strands and
    detached props stay with their pose.
    """
    h, w = img.shape[:2]
    present = img[..., 3] > 0
    grouped, n = ndimage.label(ndimage.binary_dilation(present, iterations=4))
    labels = np.where(present, grouped, 0)
    centroids = ndimage.center_of_mass(present, labels, range(1, n + 1))
    cells: dict[int, list[int]] = {}
    for label, (cy, cx) in enumerate(centroids, start=1):
        if not np.isnan(cy):
            cells.setdefault(cell_index(cy, cx, h, w, rows, cols), []).append(label)
    return {idx: np.isin(labels, members) for idx, members in cells.items()}


def slice_sheet(sheet: Sheet) -> dict[str, dict]:
    img = np.array(Image.open(REFS / sheet.file).convert("RGBA"))
    if sheet.matte == "black":
        img = key_black(img)
    img[..., 3][img[..., 3] < ALPHA_FLOOR] = 0
    out_dir = OUT / sheet.name
    out_dir.mkdir(parents=True, exist_ok=True)
    poses = {}
    for idx, mask in sorted(segment_sheet(img, sheet.rows, sheet.cols).items()):
        if idx in sheet.skip:
            continue
        pose = img.copy()
        pose[~mask] = 0
        cropped = crop_to_content(pose)
        if cropped is None:
            continue
        cropped = crop_to_content(clean_cell(cropped))
        if cropped is None:
            continue
        name = f"{idx:02d}"
        Image.fromarray(cropped).save(out_dir / f"{name}.png", optimize=True)
        poses[name] = {"w": int(cropped.shape[1]), "h": int(cropped.shape[0])}
    return poses


def main() -> None:
    manifest = {}
    for sheet in SHEETS:
        manifest[sheet.name] = slice_sheet(sheet)
        print(f"{sheet.name}: {len(manifest[sheet.name])} poses")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
