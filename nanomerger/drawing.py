"""CAD document construction, resource isolation, extents and paper layout."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import ezdxf
from ezdxf import bbox, units, xref
from ezdxf.document import Drawing

from .errors import ConversionError, InputError, UnsupportedDrawingError
from .models import PAPERS, MergeOptions, SheetInfo, SourceFile

# Deliberately conservative: an unknown object must not disappear silently.
# In particular, proxy objects, OLE, tables, external raster images, 3D solids
# and unbounded construction lines require a CAD-native workflow, not this MVP.
SUPPORTED_ENTITIES = frozenset(
    {
        "LINE",
        "POINT",
        "CIRCLE",
        "ARC",
        "ELLIPSE",
        "SPLINE",
        "LWPOLYLINE",
        "POLYLINE",
        "TEXT",
        "MTEXT",
        "ATTRIB",
        "ATTDEF",
        "INSERT",
        "HATCH",
        "SOLID",
        "TRACE",
        "3DFACE",
        "MESH",
        "DIMENSION",
        "LEADER",
        "MULTILEADER",
        "MLINE",
        "WIPEOUT",
        "MPOLYGON",
    }
)
VIEWPORT_LAYER = "NM_VIEWPORTS"


@dataclass(frozen=True)
class PreparedSource:
    source: SourceFile
    document: Drawing
    bounds: tuple[float, float, float, float]
    unit_scale: float
    source_units: int
    paper_mm: tuple[float, float]
    paper_source: str
    warnings: tuple[str, ...]


def _finite_bounds(values: Sequence[float], filename: str) -> tuple[float, float, float, float]:
    if len(values) < 4 or not all(math.isfinite(float(v)) for v in values[:4]):
        raise InputError(f"Не удалось определить конечные габариты чертежа: {filename}")
    x0, y0, x1, y1 = map(float, values[:4])
    if x1 < x0 or y1 < y0 or max(x1 - x0, y1 - y0) < 1e-9:
        raise InputError(f"Пустые или вырожденные габариты чертежа: {filename}")
    if max(abs(v) for v in (x0, y0, x1, y1)) > 1e12:
        raise InputError(f"Слишком большие координаты чертежа: {filename}")
    return x0, y0, x1, y1


def inspect_supported_entities(document: Drawing, filename: str) -> None:
    """Inspect model space and every recursively referenced block before importing."""
    unsupported: set[str] = set()
    external: set[str] = set()
    missing: set[str] = set()
    visited: set[str] = set()
    pending = list(document.modelspace())
    while pending:
        entity = pending.pop()
        kind = entity.dxftype()
        if kind not in SUPPORTED_ENTITIES:
            unsupported.add(kind)
        block_names: list[str] = []
        if kind == "INSERT":
            block_names.append(entity.dxf.name)
        elif kind == "DIMENSION" and entity.dxf.hasattr("geometry"):
            block_names.append(entity.dxf.geometry)
        for name in block_names:
            if name in visited:
                continue
            visited.add(name)
            if name not in document.blocks:
                missing.add(name)
                continue
            block = document.blocks[name]
            definition = block.block
            if definition is not None and (definition.dxf.flags & 4 or definition.dxf.xref_path):
                external.add(name)
            pending.extend(block)
    problems: list[str] = []
    if unsupported:
        problems.append("неподдерживаемые объекты: " + ", ".join(sorted(unsupported)))
    if external:
        problems.append("внешние ссылки XREF: " + ", ".join(sorted(external)))
    if missing:
        problems.append("отсутствуют определения блоков: " + ", ".join(sorted(missing)))
    if problems:
        raise UnsupportedDrawingError(
            f"{filename}: "
            + "; ".join(problems)
            + ". Преобразуйте их в поддерживаемую геометрию/блоки в CAD или экспортируйте из EPLAN без внешних зависимостей. "
            "Файл не объединён, чтобы не потерять данные."
        )


def _source_paper(document: Drawing) -> tuple[float, float] | None:
    try:
        active = document.layouts.active_layout()
        if active is None or active.name == "Model":
            names = [n for n in document.layouts.names_in_taborder() if n != "Model"]
            active = document.layouts.get(names[0]) if names else None
        if active is None:
            return None
        width = float(active.dxf_layout.dxf.get("paper_width", 0))
        height = float(active.dxf_layout.dxf.get("paper_height", 0))
        if math.isfinite(width) and math.isfinite(height) and width >= 50 and height >= 50:
            # DXF layout paper sizes are stored in millimetres.
            return width, height
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    return None


def choose_paper(
    document: Drawing, bounds: tuple[float, float, float, float], options: MergeOptions
) -> tuple[tuple[float, float], str]:
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    landscape = width >= height

    def orient(size: tuple[float, float]) -> tuple[float, float]:
        short, long = sorted(size)
        return (long, short) if landscape else (short, long)

    if options.paper in PAPERS:
        return orient(PAPERS[options.paper]), f"explicit:{options.paper}"
    source_paper = _source_paper(document)
    if source_paper is not None:
        if options.paper == "source":
            return source_paper, "source-layout"
        short, long = sorted(source_paper)
        return ((long, short) if landscape else (short, long)), "source-layout"
    candidates = [orient(size) for size in PAPERS.values()]
    # EPLAN frames often have exactly the trim size in model space. Recognize
    # that before adding margins, otherwise an A3 frame becomes an A2 sheet.
    close = [
        size
        for size in candidates
        if math.isclose(size[0], width, rel_tol=0.03, abs_tol=2.0)
        and math.isclose(size[1], height, rel_tol=0.03, abs_tol=2.0)
    ]
    if close:
        size = min(close, key=lambda s: abs(s[0] - width) + abs(s[1] - height))
        return size, "inferred-frame"
    fits = [
        size
        for size in candidates
        if size[0] >= width + 2 * options.margin_mm and size[1] >= height + 2 * options.margin_mm
    ]
    if fits:
        return min(fits, key=lambda s: s[0] * s[1]), "inferred-fit"
    return (width + 2 * options.margin_mm, height + 2 * options.margin_mm), "custom-extents"


def prepare_source(source: SourceFile, dxf_path: Path, options: MergeOptions) -> PreparedSource:
    try:
        document = ezdxf.readfile(dxf_path)
    except (OSError, ValueError, ezdxf.DXFError) as exc:
        raise ConversionError(f"Не удалось прочитать чертёж {source.name}: {exc}") from exc
    inspect_supported_entities(document, source.name)
    warnings: list[str] = []
    if any(
        entity.dxftype() != "VIEWPORT"
        for name in document.layouts.names_in_taborder()
        if name != "Model"
        for entity in document.layouts.get(name)
    ):
        warnings.append(
            f"{source.name}: объединяется пространство модели; исходные объекты Paper Space не копируются. Размер листа учитывается, если задан."
        )
    source_units = int(document.header.get("$INSUNITS", 0))
    unit_scale = 1.0
    if source_units == 0:
        warnings.append(
            f"{source.name}: единицы не заданы ($INSUNITS=0); принято 1 единица = 1 мм."
        )
    else:
        try:
            unit_scale = float(units.conversion_factor(source_units, units.MM))
        except (ValueError, TypeError, IndexError) as exc:
            raise InputError(
                f"{source.name}: неподдерживаемые единицы $INSUNITS={source_units}."
            ) from exc
        if not math.isfinite(unit_scale) or unit_scale <= 0:
            raise InputError(
                f"{source.name}: не удалось перевести единицы $INSUNITS={source_units} в мм."
            )
    try:
        extents = bbox.extents(document.modelspace(), fast=False)
    except Exception as exc:
        raise InputError(f"Не удалось рассчитать габариты {source.name}: {exc}") from exc
    if not extents.has_data:
        raise InputError(
            f"{source.name}: пространство модели пустое или не содержит видимых габаритов."
        )
    raw = _finite_bounds(
        (extents.extmin.x, extents.extmin.y, extents.extmax.x, extents.extmax.y), source.name
    )
    bounds = tuple(value * unit_scale for value in raw)
    bounds = _finite_bounds(bounds, source.name)
    paper, paper_source = choose_paper(document, bounds, options)
    if paper[0] <= 2 * options.margin_mm or paper[1] <= 2 * options.margin_mm:
        raise InputError(
            f"{source.name}: поля {options.margin_mm:g} мм оставляют нулевую область печати на листе {paper[0]:g}×{paper[1]:g} мм."
        )
    return PreparedSource(
        source, document, bounds, unit_scale, source_units, paper, paper_source, tuple(warnings)
    )


def placement_grid(
    items: Sequence[PreparedSource], options: MergeOptions
) -> list[tuple[float, float, float, float]]:
    """Left-to-right, then top-to-bottom; sheets are top-aligned within a row."""
    sizes = [
        (max(i.bounds[2] - i.bounds[0], 1e-6), max(i.bounds[3] - i.bounds[1], 1e-6)) for i in items
    ]
    columns = len(items) if options.columns == 0 else min(options.columns, len(items))
    rows = math.ceil(len(items) / columns)
    widths = [
        max(sizes[r * columns + c][0] for r in range(rows) if r * columns + c < len(items))
        for c in range(columns)
    ]
    heights = [max(size[1] for size in sizes[r * columns : (r + 1) * columns]) for r in range(rows)]
    xs, ys = [], []
    x = y = 0.0
    for width in widths:
        xs.append(x)
        x += width + options.gap_mm
    for height in heights:
        ys.append(y)
        y += height + options.gap_mm
    result = []
    for index, (width, height) in enumerate(sizes):
        row, column = divmod(index, columns)
        left, top = xs[column], -ys[row]
        result.append((left, top - height, left + width, top))
    return result


def layout_name(index: int, stem: str) -> str:
    cleaned = re.sub(r'[<>/\\":;?*|=\x00-\x1f]', "_", stem).strip()[:180]
    return f"{index:04d}_{cleaned}"


def build_document(
    prepared: Sequence[PreparedSource], options: MergeOptions
) -> tuple[Drawing, tuple[SheetInfo, ...]]:
    version = options.dwg_version if options.output_format == "dwg" else "R2018"
    target = ezdxf.new(version, setup=True)
    target.header["$INSUNITS"] = int(units.MM)
    target.header["$MEASUREMENT"] = 1
    target.header["$PSLTSCALE"] = 1
    target.header["$LTSCALE"] = 1.0
    target.layers.new(VIEWPORT_LAYER, dxfattribs={"color": 7, "plot": 0})
    default_layouts = [name for name in target.layouts.names_in_taborder() if name != "Model"]
    placements = placement_grid(prepared, options)
    sheets: list[SheetInfo] = []
    model = target.modelspace()
    for index, (item, bounds) in enumerate(zip(prepared, placements, strict=True), start=1):
        block_name = f"NM_SHEET_{index:04d}"
        block = target.blocks.new(block_name, base_point=(0, 0, 0))
        # Unlike the legacy Importer's KEEP behaviour, this remaps conflicting
        # layers, linetypes, styles and block names instead of reusing definitions
        # from a different EPLAN file.
        loader = xref.Loader(item.document, target, conflict_policy=xref.ConflictPolicy.NUM_PREFIX)
        loader.load_modelspace(target_layout=block)
        loader.execute()
        x0, y0, x1, y1 = item.bounds
        left, bottom, right, top = bounds
        scale = item.unit_scale
        model.add_blockref(
            block_name,
            insert=(left - x0, top - y1, 0),
            dxfattribs={"xscale": scale, "yscale": scale, "zscale": scale, "layer": "0"},
        )
        name = layout_name(index, item.source.path.stem)
        sheet_layout = target.layouts.new(name)
        paper_w, paper_h = item.paper_mm
        margin = options.margin_mm
        sheet_layout.page_setup(
            size=(paper_w, paper_h),
            margins=(margin, margin, margin, margin),
            scale=(1, 1),
            name="NanoMerger",
            device="DWG To PDF.pc3",
        )
        print_w, print_h = paper_w - 2 * margin, paper_h - 2 * margin
        viewport_scale = min(print_w / max(right - left, 1e-6), print_h / max(top - bottom, 1e-6))
        center_x, center_y = (left + right) / 2, (bottom + top) / 2
        sheet_layout.add_viewport(
            center=(margin + print_w / 2, margin + print_h / 2),
            size=(print_w, print_h),
            view_center_point=(center_x, center_y, 0),
            view_height=print_h / viewport_scale,
            status=2,
            dxfattribs={"layer": VIEWPORT_LAYER},
        )
        sheet_layout.dxf_layout.dxf.taborder = index
        sheet_layout.reset_extents(extmin=(0, 0, 0), extmax=(paper_w, paper_h, 0))
        sheets.append(
            SheetInfo(
                index=index,
                source_name=item.source.name,
                file_number=item.source.number,
                layout_name=name,
                block_name=block_name,
                source_units=item.source_units,
                unit_scale=scale,
                source_bounds_mm=item.bounds,
                model_bounds_mm=bounds,
                paper_mm=item.paper_mm,
                paper_source=item.paper_source,
                viewport_scale=viewport_scale,
            )
        )
    # ezdxf requires at least one paperspace layout; remove the template tabs
    # only after all replacement sheets have been created.
    for name in default_layouts:
        if name in target.layouts:
            target.layouts.delete(name)
    all_bounds = placements
    extmin = (min(b[0] for b in all_bounds), min(b[1] for b in all_bounds), 0)
    extmax = (max(b[2] for b in all_bounds), max(b[3] for b in all_bounds), 0)
    target.header["$EXTMIN"] = extmin
    target.header["$EXTMAX"] = extmax
    target.header["$LIMMIN"] = extmin[:2]
    target.header["$LIMMAX"] = extmax[:2]
    target.set_modelspace_vport(
        height=max((extmax[1] - extmin[1]) * 1.15, 10),
        center=((extmin[0] + extmax[0]) / 2, (extmin[1] + extmax[1]) / 2),
    )
    target.layouts.set_active_layout(sheets[0].layout_name)
    audit = target.audit()
    if audit.errors:
        messages = "; ".join(f"{e.code}: {e.message}" for e in audit.errors[:10])
        raise ConversionError(f"Объединённый DXF не прошёл аудит: {messages}")
    return target, tuple(sheets)
