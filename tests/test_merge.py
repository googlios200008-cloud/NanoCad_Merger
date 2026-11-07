from __future__ import annotations

import json
import threading

import ezdxf
import pytest
from conftest import make_drawing
from pypdf import PdfReader

from nanomerger import MergeOptions, merge_folder
from nanomerger.converters import DxfPassthroughConverter
from nanomerger.errors import (
    CancelledError,
    DependencyError,
    InputError,
    OutputExistsError,
    UnsupportedDrawingError,
)
from nanomerger.publishing import sha256


def dxf_options(**kwargs):
    return MergeOptions(input_format="dxf", output_format="dxf", **kwargs)


def test_merge_model_layouts_pdf_and_report(dxf_folder, tmp_path):
    out = tmp_path / "out"
    result = merge_folder(dxf_folder, out, options=dxf_options(gap_mm=50))
    assert [s.file_number for s in result.sheets] == [1, 2, 10]
    assert result.dwg_path is None and result.dxf_path == result.cad_path
    assert result.cad_path.exists() and result.pdf_path.exists() and result.report_path.exists()
    doc = ezdxf.readfile(result.cad_path)
    inserts = list(doc.modelspace().query("INSERT"))
    assert len(inserts) == 3
    assert [s.layout_name for s in result.sheets] == [
        n for n in doc.layouts.names_in_taborder() if n != "Model"
    ]
    for previous, current in zip(result.sheets, result.sheets[1:], strict=False):
        assert current.model_bounds_mm[0] - previous.model_bounds_mm[2] == pytest.approx(50)
    for sheet in result.sheets:
        layout = doc.layouts.get(sheet.layout_name)
        viewports = [vp for vp in layout.viewports() if vp.dxf.id > 1]
        assert len(viewports) == 1
        vp = viewports[0]
        assert vp.dxf.view_center_point.x == pytest.approx(
            (sheet.model_bounds_mm[0] + sheet.model_bounds_mm[2]) / 2
        )
        assert vp.dxf.view_center_point.y == pytest.approx(
            (sheet.model_bounds_mm[1] + sheet.model_bounds_mm[3]) / 2
        )
        assert layout.dxf_layout.dxf.paper_width == pytest.approx(420)
        assert layout.dxf_layout.dxf.paper_height == pytest.approx(297)
    pdf = PdfReader(result.pdf_path)
    assert len(pdf.pages) == 3
    for page in pdf.pages:
        assert float(page.mediabox.width) == pytest.approx(420 * 72 / 25.4, abs=0.1)
        assert float(page.mediabox.height) == pytest.approx(297 * 72 / 25.4, abs=0.1)
        assert len(page.get_contents().get_data()) > 100
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["status"] == "complete"
    assert report["outputs"]["cad_sha256"] == sha256(result.cad_path)
    assert report["outputs"]["pdf_sha256"] == sha256(result.pdf_path)
    assert [s["name"] for s in report["sources"]] == [
        "EPLAN_1.dxf",
        "EPLAN_2.dxf",
        "EPLAN_10.dxf",
    ]


def test_conflicting_resources_are_isolated(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    make_drawing(folder / "A1.dxf", 1, layer_color=1)
    make_drawing(folder / "A2.dxf", 2, layer_color=3)
    result = merge_folder(folder, tmp_path / "out", options=dxf_options())
    doc = ezdxf.readfile(result.cad_path)
    wire_layers = [
        layer
        for layer in doc.layers
        if layer.dxf.name == "WIRE" or layer.dxf.name.endswith("$WIRE")
    ]
    assert len(wire_layers) == 2
    assert {layer.dxf.color for layer in wire_layers} == {1, 3}
    sym_blocks = [
        name for name in doc.blocks.block_names() if name == "SYM" or "sym" in name.lower()
    ]
    assert len(sym_blocks) == 2


def test_units_are_normalized_to_mm(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    make_drawing(folder / "U1.dxf", 1, width=42, height=29.7, units=5, paper=None)  # cm
    make_drawing(folder / "U2.dxf", 2, width=0.42, height=0.297, units=6, paper=None)  # m
    result = merge_folder(folder, tmp_path / "out", options=dxf_options(paper="A3"))
    for sheet in result.sheets:
        bounds = sheet.model_bounds_mm
        assert bounds[2] - bounds[0] == pytest.approx(420)
        assert bounds[3] - bounds[1] == pytest.approx(297)
    assert ezdxf.readfile(result.cad_path).header["$INSUNITS"] == 4


def test_grid_columns(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    for n in range(1, 5):
        make_drawing(folder / f"G{n}.dxf", n)
    result = merge_folder(folder, tmp_path / "out", options=dxf_options(columns=2, gap_mm=20))
    a, b, c, d = [s.model_bounds_mm for s in result.sheets]
    assert b[0] > a[2] and c[1] < a[1]
    assert c[0] == pytest.approx(a[0]) and d[0] == pytest.approx(b[0])


def test_overwrite_protects_existing_complete_set(dxf_folder, tmp_path):
    out = tmp_path / "out"
    result = merge_folder(dxf_folder, out, options=dxf_options())
    before = {p: p.read_bytes() for p in (result.cad_path, result.pdf_path, result.report_path)}
    with pytest.raises(OutputExistsError):
        merge_folder(dxf_folder, out, options=dxf_options())
    assert all(p.read_bytes() == data for p, data in before.items())
    merge_folder(dxf_folder, out, options=dxf_options(overwrite=True))


def test_cancel_before_work_publishes_nothing(dxf_folder, tmp_path):
    event = threading.Event()
    event.set()
    out = tmp_path / "out"
    with pytest.raises(CancelledError):
        merge_folder(dxf_folder, out, options=dxf_options(), cancel_event=event)
    assert not out.exists() or not any(out.iterdir())


def test_unsupported_object_fails_closed(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    path = make_drawing(folder / "X1.dxf", 1)
    doc = ezdxf.readfile(path)
    doc.modelspace().add_xline((0, 0), (1, 1))
    doc.saveas(path)
    with pytest.raises(UnsupportedDrawingError, match="XLINE"):
        merge_folder(folder, tmp_path / "out", options=dxf_options())
    assert not (tmp_path / "out" / "X_merged.dxf").exists()


def test_external_reference_fails_closed(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    path = make_drawing(folder / "R1.dxf", 1)
    doc = ezdxf.readfile(path)
    doc.blocks.new("EXTERNAL", dxfattribs={"flags": 4, "xref_path": "missing.dwg"})
    doc.modelspace().add_blockref("EXTERNAL", (0, 0))
    doc.saveas(path)
    with pytest.raises(UnsupportedDrawingError, match="XREF"):
        merge_folder(folder, tmp_path / "out", options=dxf_options())


def test_missing_oda_is_explicit(tmp_path, monkeypatch):
    folder = tmp_path / "dwg-in"
    folder.mkdir()
    (folder / "A1.dwg").touch()
    monkeypatch.delenv("NANOMERGER_ODA", raising=False)
    monkeypatch.setattr("nanomerger.converters.shutil.which", lambda _: None)
    with pytest.raises(DependencyError, match="ODA"):
        merge_folder(folder, tmp_path / "out", oda_path=tmp_path / "missing.exe")


def test_dxf_adapter_never_fakes_dwg(tmp_path):
    with pytest.raises(DependencyError, match="не переименовывается"):
        DxfPassthroughConverter().write_dwg(tmp_path / "a.dxf", tmp_path / "a.dwg", "R2018")


def test_output_cannot_overwrite_source(dxf_folder):
    with pytest.raises(InputError, match="совпадает"):
        merge_folder(dxf_folder, dxf_folder, output_name="EPLAN_1", options=dxf_options())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"gap_mm": -1},
        {"columns": -1},
        {"margin_mm": float("nan")},
        {"paper": "A9"},
        {"dwg_version": "R12"},
        {"timeout_seconds": 0},
    ],
)
def test_invalid_options(kwargs):
    with pytest.raises(InputError):
        MergeOptions(**kwargs)
