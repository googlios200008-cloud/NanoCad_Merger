"""Generate a synthetic EPLAN-like demo and merge it.

Default: DXF inputs → merged DXF + PDF (no proprietary converter needed).
With --dwg: the same demo inputs are converted to real DWG by an installed ODA
File Converter, then merged through the production DWG pipeline.
These drawings are synthetic examples, not actual EPLAN exports.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import ezdxf

from nanomerger import MergeOptions, merge_folder
from nanomerger.converters import OdaConverter


def make_sheet(number: int) -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    for name, color in (("FRAME", 8), ("WIRE", 7), ("DEVICE", 5), ("LABEL", 7)):
        doc.layers.new(name, dxfattribs={"color": color})
    model = doc.modelspace()
    model.add_lwpolyline(
        [(0, 0), (420, 0), (420, 297), (0, 297)], close=True, dxfattribs={"layer": "FRAME"}
    )
    model.add_lwpolyline(
        [(10, 10), (410, 10), (410, 287), (10, 287)], close=True, dxfattribs={"layer": "FRAME"}
    )
    model.add_text(
        f"Схема соединений · Лист {number}",
        dxfattribs={"height": 7, "insert": (18, 272), "layer": "LABEL"},
    )
    model.add_text(
        "NanoMerger · синтетический пример, не экспорт EPLAN",
        dxfattribs={"height": 3.5, "insert": (18, 262), "layer": "LABEL"},
    )
    terminal = doc.blocks.new("TERMINAL")
    terminal.add_circle((0, 0), 2.5)
    terminal.add_line((-5, 0), (5, 0))
    model.add_line((40, 65), (40, 245), dxfattribs={"layer": "WIRE"})
    model.add_line((380, 65), (380, 245), dxfattribs={"layer": "WIRE"})
    for row in range(10):
        y = 235 - row * 16
        model.add_line((40, y), (175, y), dxfattribs={"layer": "WIRE"})
        model.add_line((245, y), (380, y), dxfattribs={"layer": "WIRE"})
        model.add_blockref("TERMINAL", (100, y))
        model.add_blockref("TERMINAL", (320, y))
        model.add_lwpolyline(
            [(175, y - 6), (245, y - 6), (245, y + 6), (175, y + 6)],
            close=True,
            dxfattribs={"layer": "DEVICE"},
        )
        model.add_text(
            f"K{number}.{row + 1}",
            dxfattribs={"height": 4, "insert": (194, y - 2), "layer": "LABEL"},
        )
        model.add_text(
            f"X{number}:{row + 1}",
            dxfattribs={"height": 3, "insert": (90, y + 4), "layer": "LABEL"},
        )
    # Simple title block.
    model.add_lwpolyline(
        [(230, 10), (410, 10), (410, 50), (230, 50)], close=True, dxfattribs={"layer": "FRAME"}
    )
    model.add_line((230, 30), (410, 30), dxfattribs={"layer": "FRAME"})
    model.add_line((330, 10), (330, 50), dxfattribs={"layer": "FRAME"})
    model.add_text(
        "Демонстрационный комплект", dxfattribs={"height": 4, "insert": (235, 38), "layer": "LABEL"}
    )
    model.add_text(
        f"Лист {number} из 3", dxfattribs={"height": 4, "insert": (335, 38), "layer": "LABEL"}
    )
    model.add_text(
        "Формат A3 · мм", dxfattribs={"height": 3.5, "insert": (235, 18), "layer": "LABEL"}
    )
    model.add_text(
        "NanoMerger 0.1", dxfattribs={"height": 3.5, "insert": (335, 18), "layer": "LABEL"}
    )
    doc.layouts.active_layout().page_setup(size=(420, 297), margins=(5, 5, 5, 5))
    return doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "output")
    parser.add_argument(
        "--dwg", action="store_true", help="Проверить полный DWG-цикл через установленный ODA"
    )
    parser.add_argument("--oda", type=Path)
    args = parser.parse_args()
    root = args.output.expanduser().resolve()
    dxf_dir = root / "demo_dxf"
    dxf_dir.mkdir(parents=True, exist_ok=True)
    for number in (1, 2, 3):
        make_sheet(number).saveas(dxf_dir / f"EPLAN_Demo_{number}.dxf")
    if args.dwg:
        converter = OdaConverter(args.oda)
        dwg_dir = root / "demo_dwg"
        for dxf in sorted(dxf_dir.glob("*.dxf")):
            converter.write_dwg(dxf, dwg_dir / f"{dxf.stem}.dwg", "R2018")
        result = merge_folder(
            dwg_dir, root / "merged", oda_path=args.oda, options=MergeOptions(overwrite=True)
        )
    else:
        result = merge_folder(
            dxf_dir,
            root / "merged",
            options=MergeOptions(input_format="dxf", output_format="dxf", overwrite=True),
        )
    print(f"Демо-комплект: {result.cad_path}")
    print(f"PDF: {result.pdf_path}")
    print(f"Отчёт: {result.report_path}")
    print("Это синтетические чертежи. Для проверки заказчика используйте реальный экспорт EPLAN.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
