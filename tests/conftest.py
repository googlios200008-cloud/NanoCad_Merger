from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest


def make_drawing(
    path: Path,
    number: int,
    *,
    width: float = 420.0,
    height: float = 297.0,
    units: int = 4,
    offset: tuple[float, float] = (0, 0),
    layer_color: int = 1,
    paper: tuple[float, float] | None = (420, 297),
) -> Path:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = units
    model = doc.modelspace()
    ox, oy = offset
    scale = width / 420.0
    doc.layers.new("WIRE", dxfattribs={"color": layer_color})
    block = doc.blocks.new("SYM")
    block.add_circle((0, 0), 8 * scale)
    block.add_line((-12 * scale, 0), (12 * scale, 0))
    model.add_lwpolyline(
        [(ox, oy), (ox + width, oy), (ox + width, oy + height), (ox, oy + height)],
        close=True,
        dxfattribs={"layer": "WIRE"},
    )
    model.add_text(
        f"SHEET {number}",
        dxfattribs={"height": 12 * scale, "insert": (ox + 20 * scale, oy + height - 35 * scale)},
    )
    model.add_blockref("SYM", insert=(ox + width / 2, oy + height / 2))
    model.add_circle((ox + width / 2, oy + height / 2), 35 * scale, dxfattribs={"layer": "WIRE"})
    if paper:
        layout = doc.layouts.active_layout()
        layout.page_setup(size=paper, margins=(5, 5, 5, 5))
    doc.saveas(path)
    return path


@pytest.fixture
def dxf_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "input"
    folder.mkdir()
    for number in (10, 2, 1):
        make_drawing(
            folder / f"EPLAN_{number}.dxf",
            number,
            offset=(-100, -50) if number == 2 else (0, 0),
            layer_color=3 if number == 2 else 1,
        )
    return folder
