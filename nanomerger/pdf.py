"""Multipage vector PDF rendered from the saved merged CAD document.

This is deliberately not advertised as native CAD plotting: CTB/STB, printer
drivers, SHX substitutions and proprietary object enablers are not emulated.
The geometry comes from the final saved DWG (round-tripped through ODA), or from
the final DXF in explicit DXF-only mode, and each page uses that sheet's viewport.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration, LinePolicy
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.properties import LayoutProperties
from ezdxf.document import Drawing

from .converters import check_cancel
from .errors import CancelledError, ConversionError, DependencyError
from .models import CancelEvent, MergeOptions, Progress, ProgressCallback, SheetInfo, safe_stem

try:
    from matplotlib import rc_context
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure
except ImportError as exc:  # pragma: no cover - normal installs include this
    raise DependencyError("Для PDF установите зависимости: pip install -e .") from exc


def _sheet_viewport(document: Drawing, sheet: SheetInfo):
    if sheet.layout_name not in document.layouts:
        raise ConversionError(f"В итоговом CAD-файле отсутствует лист {sheet.layout_name}.")
    layout = document.layouts.get(sheet.layout_name)
    candidates = [vp for vp in layout.viewports() if vp.dxf.id > 1 and vp.dxf.status > 0]
    if len(candidates) != 1:
        raise ConversionError(
            f"Лист {sheet.layout_name}: ожидался один рабочий видовой экран, найдено {len(candidates)}."
        )
    return layout, candidates[0]


def render_pdf(
    document: Drawing,
    sheets: Sequence[SheetInfo],
    path: Path,
    options: MergeOptions,
    *,
    cancel: CancelEvent | None = None,
    progress: ProgressCallback | None = None,
) -> None:
    model = document.modelspace()
    context = RenderContext(document)
    config = Configuration(
        background_policy=BackgroundPolicy.WHITE,
        color_policy=ColorPolicy.COLOR_SWAP_BW if options.color_pdf else ColorPolicy.BLACK,
        line_policy=LinePolicy.ACCURATE,
        min_lineweight=0.13,
        lineweight_scaling=1.0,
    )
    model_properties = LayoutProperties.from_layout(model)
    model_properties.set_colors("#ffffff", "#000000")
    path = Path(path)
    try:
        with (
            PdfPages(path) as pdf,
            rc_context({"pdf.fonttype": 42, "path.simplify": False, "axes.autolimit_mode": "data"}),
        ):
            info = pdf.infodict()
            info["Title"] = safe_stem(path.stem)
            info["Author"] = "NanoMerger"
            info["Creator"] = "NanoMerger / ezdxf / matplotlib"
            info["Subject"] = (
                "Vector geometry preview from merged CAD model; not a CTB/STB CAD plot"
            )
            for index, sheet in enumerate(sheets, start=1):
                check_cancel(cancel)
                layout, viewport = _sheet_viewport(document, sheet)
                paper_w = float(layout.dxf_layout.dxf.paper_width)
                paper_h = float(layout.dxf_layout.dxf.paper_height)
                vp_w, vp_h = float(viewport.dxf.width), float(viewport.dxf.height)
                view_h = float(viewport.dxf.view_height)
                values = (paper_w, paper_h, vp_w, vp_h, view_h)
                if not all(math.isfinite(v) and v > 0 for v in values):
                    raise ConversionError(
                        f"Некорректный лист или видовой экран: {sheet.layout_name}"
                    )
                center = viewport.dxf.view_center_point
                paper_center = viewport.dxf.center
                view_w = view_h * vp_w / vp_h
                inserts = [
                    entity
                    for entity in model
                    if entity.dxftype() == "INSERT"
                    and entity.dxf.name.casefold() == sheet.block_name.casefold()
                ]
                if len(inserts) != 1:
                    raise ConversionError(
                        f"В итоговой модели не найден единственный блок листа {sheet.layout_name}."
                    )
                insert_handle = inserts[0].dxf.handle
                figure = Figure(
                    figsize=(paper_w / 25.4, paper_h / 25.4), dpi=100, facecolor="white"
                )
                ax = figure.add_axes((0, 0, 1, 1))
                backend = MatplotlibBackend(ax, adjust_figure=False)
                frontend = Frontend(context, backend, config=config)
                frontend.draw_layout(
                    model,
                    finalize=True,
                    filter_func=lambda entity, handle=insert_handle: entity.dxf.handle == handle,
                    layout_properties=model_properties,
                )
                # MatplotlibBackend.finalize() enables autoscaling; restore the
                # exact CAD viewport window afterwards so PDF and layout agree.
                ax.set_xlim(center.x - view_w / 2, center.x + view_w / 2)
                ax.set_ylim(center.y - view_h / 2, center.y + view_h / 2)
                ax.set_position(
                    (
                        (paper_center.x - vp_w / 2) / paper_w,
                        (paper_center.y - vp_h / 2) / paper_h,
                        vp_w / paper_w,
                        vp_h / paper_h,
                    )
                )
                ax.set_axis_off()
                ax.set_facecolor("white")
                # Match CAD viewport clipping: geometry outside the sheet window
                # must not bleed into neighbouring margins on the PDF page.
                for artist in (*ax.lines, *ax.collections, *ax.patches, *ax.images):
                    artist.set_clip_on(True)
                    artist.set_clip_path(ax.patch)
                pdf.savefig(figure, facecolor="white")
                figure.clear()
                if progress:
                    progress(
                        Progress(
                            "pdf",
                            index,
                            len(sheets),
                            f"PDF: лист {index}/{len(sheets)} — {sheet.source_name}",
                        )
                    )
    except CancelledError:
        path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        path.unlink(missing_ok=True)
        if isinstance(exc, ConversionError):
            raise
        raise ConversionError(f"Не удалось создать PDF: {exc}") from exc
