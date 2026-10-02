import numpy as np

from tools.slice_sheets import cell_bounds, clean_cell, crop_to_content, segment_sheet


def test_cell_bounds_cover_sheet_without_gaps():
    for count in (3, 4):
        bounds = [cell_bounds(1254, count, i) for i in range(count)]
        assert bounds[0][0] == 0
        assert bounds[-1][1] == 1254
        for (_, end), (start, _) in zip(bounds, bounds[1:]):
            assert end == start


def test_cell_bounds_fractional_cells():
    # 1254 / 4 = 313.5 → cells alternate between 313 and 314 px wide.
    widths = [b - a for a, b in (cell_bounds(1254, 4, i) for i in range(4))]
    assert sorted(set(widths)) == [313, 314]


def test_clean_cell_snaps_alpha_and_removes_haze_and_speckles():
    cell = np.zeros((40, 40, 4), dtype=np.uint8)
    cell[10:30, 10:30] = (120, 120, 120, 252)  # body, nearly opaque
    cell[0:5, 0:5, 3] = 10  # haze
    cell[35, 35] = (255, 0, 0, 255)  # one-pixel speckle
    out = clean_cell(cell)
    assert (out[10:30, 10:30, 3] == 255).all()
    assert out[0:5, 0:5, 3].max() == 0
    assert out[35, 35, 3] == 0


def test_clean_cell_desaturates_fringe():
    cell = np.zeros((20, 20, 4), dtype=np.uint8)
    cell[5:15, 5:15] = (120, 120, 120, 255)
    cell[4, 5:15] = (255, 0, 0, 128)  # red semi-transparent fringe
    out = clean_cell(cell)
    r, g, b = out[4, 8, :3]
    assert r == g == b


def test_crop_to_content():
    cell = np.zeros((50, 50, 4), dtype=np.uint8)
    cell[20:30, 10:15, 3] = 255
    out = crop_to_content(cell)
    assert out.shape[:2] == (10 + 4, 5 + 4)
    assert crop_to_content(np.zeros((5, 5, 4), dtype=np.uint8)) is None


def test_segment_sheet_assigns_blobs_that_cross_cell_lines_by_centroid():
    img = np.zeros((100, 100, 4), dtype=np.uint8)
    # Top-left pose spills past the row boundary at y=50 but its centroid is in row 0.
    img[5:60, 5:40, 3] = 255
    # Bottom-right pose.
    img[60:95, 60:95, 3] = 255
    cells = segment_sheet(img, rows=2, cols=2)
    assert set(cells) == {0, 3}
    assert cells[0][55, 20]  # the spilled-over part stays with pose 0
    assert not cells[3][55, 20]
