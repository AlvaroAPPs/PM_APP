"""Generacion del Planning Gantt en PDF: cabecera con logo de Mecalux,
nombre/codigo de proyecto, y una fila por tarea/hito/subtarea con su
barra posicionada sobre un eje de meses. Reutiliza el motor generico de
reports/pdf_engine.py (sin dependencias externas).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from itertools import groupby
from pathlib import Path

from reports.pdf_engine import (
    PAGE_HEIGHT,
    PAGE_WIDTH,
    PdfImage,
    assemble_pdf,
    load_jpeg_image,
    pdf_image,
    pdf_rect,
    pdf_text,
)

LOGO_PATH = Path(__file__).resolve().parent.parent / "meeting_minutes" / "assets" / "mecalux_logo.jpg"

NAVY = (0.122, 0.227, 0.373)
BRIGHT_BLUE = (0.20, 0.55, 0.95)
GOLD = (0.86, 0.62, 0.06)
GREEN = (0.082, 0.451, 0.278)
ORANGE = (0.910, 0.349, 0.047)
INK = (0.125, 0.122, 0.110)
MUTED = (0.42, 0.42, 0.39)
YEAR_COLOR = (0.122, 0.227, 0.373)
MONTH_LABEL_COLOR = (0.29, 0.37, 0.50)
WEEK_LABEL_COLOR = (0.60, 0.62, 0.68)

MARGIN = 15.0
CONTENT_X = MARGIN + 10
CONTENT_W = PAGE_WIDTH - (2 * MARGIN) - 20
TITLE_W = 150.0
START_W = 55.0
END_W = 55.0
PCT_W = 30.0
TITLE_COL_W = TITLE_W + START_W + END_W + PCT_W
ROW_H = 16.0
MONTH_NAMES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

SOURCE_COLORS = {"phase": NAVY, "checklist": GREEN, "manual": BRIGHT_BLUE}


def _lighten(color: tuple[float, float, float], amount: float = 0.6) -> tuple[float, float, float]:
    return tuple(c + (1.0 - c) * amount for c in color)


def _load_logo() -> PdfImage | None:
    try:
        return load_jpeg_image(str(LOGO_PATH))
    except (OSError, ValueError):
        return None


def _week_starts(min_date: date, max_date: date) -> list[date]:
    """Lunes de cada semana ISO cubierta por el rango, para la fila de
    semanas de la cabecera (agrupadas visualmente bajo cada mes)."""
    cursor = min_date - timedelta(days=min_date.weekday())
    weeks = []
    while cursor <= max_date:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    return weeks


def _date_x(d: date, min_date: date, span_days: int, chart_x: float, chart_w: float) -> float:
    offset = (d - min_date).days
    return chart_x + (offset / span_days) * chart_w


def _text_width(text: str, size: float, bold: bool = False) -> float:
    return len(text) * size * (0.56 if bold else 0.50)


def _week_groups(week_starts, min_date, span_days, chart_x, chart_w, key_fn):
    """Agrupa semanas consecutivas por key_fn (p.ej. mes o año) del lunes
    de cada semana. Los limites de cada grupo caen siempre justo en el
    borde de una semana, para que la linea de mes/año nunca corte por la
    mitad un numero de semana."""
    groups = []
    idx = 0
    for key, grp in groupby(week_starts, key=key_fn):
        count = sum(1 for _ in grp)
        end_idx = idx + count
        x0 = max(chart_x, _date_x(week_starts[idx], min_date, span_days, chart_x, chart_w))
        x1 = (
            _date_x(week_starts[end_idx], min_date, span_days, chart_x, chart_w)
            if end_idx < len(week_starts) else chart_x + chart_w
        )
        groups.append((key, x0, x1))
        idx = end_idx
    return groups


def _order_items(items: list[dict]) -> list[tuple[dict, int]]:
    top_level = [it for it in items if it.get("parent_id") is None]
    top_level.sort(key=lambda it: (it["position"], it["id"]))
    children: dict[int, list[dict]] = {}
    for it in items:
        parent_id = it.get("parent_id")
        if parent_id is not None:
            children.setdefault(parent_id, []).append(it)
    for kids in children.values():
        kids.sort(key=lambda it: (it["position"], it["id"]))

    ordered: list[tuple[dict, int]] = []
    for parent in top_level:
        ordered.append((parent, 0))
        for child in children.get(parent["id"], []):
            ordered.append((child, 1))
    return ordered


def _page_header(
    page: list[str],
    logo: PdfImage | None,
    project_name: str,
    project_code: str,
    generated_at: date,
    progress_w: float | None,
) -> None:
    pdf_rect(page, MARGIN, MARGIN, PAGE_WIDTH - (2 * MARGIN), PAGE_HEIGHT - (2 * MARGIN),
             fill_rgb=(0.98, 0.98, 0.97), stroke_rgb=(0.90, 0.91, 0.93), line_width=0.8)
    pdf_rect(page, CONTENT_X, PAGE_HEIGHT - 62, CONTENT_W, 40, fill_rgb=NAVY, stroke_rgb=None)

    text_x = CONTENT_X + 14
    if logo is not None:
        logo_h = 22.0
        logo_w = logo.width * (logo_h / logo.height)
        pdf_rect(page, CONTENT_X + 10, PAGE_HEIGHT - 51, logo_w + 12, logo_h + 6, fill_rgb=(1.0, 1.0, 1.0), stroke_rgb=None)
        pdf_image(page, CONTENT_X + 16, PAGE_HEIGHT - 48, logo_w, logo_h, "Logo")
        text_x = CONTENT_X + 16 + logo_w + 18

    title = project_name if len(project_name) <= 48 else project_name[:45].rstrip() + "..."
    pdf_text(page, text_x, PAGE_HEIGHT - 34, f"Planning - {title}", size=14, bold=True, color_rgb=(1.0, 1.0, 1.0))
    pdf_text(page, text_x, PAGE_HEIGHT - 48, f"Código de proyecto: {project_code}", size=8.5, color_rgb=(0.85, 0.88, 0.93))
    if progress_w is not None:
        pdf_text(page, text_x + 220, PAGE_HEIGHT - 48, f"Avance del proyecto: {progress_w:g}%", size=8.5, bold=True, color_rgb=(1.0, 1.0, 1.0))
    pdf_text(
        page, CONTENT_X + CONTENT_W - 190, PAGE_HEIGHT - 34,
        f"Generado: {generated_at.strftime('%d/%m/%Y %H:%M')}", size=7.5, color_rgb=(0.85, 0.88, 0.93),
    )


def _legend(page: list[str], y: float) -> None:
    entries = [("Hito", GOLD), ("Avance", ORANGE)]
    x = CONTENT_X
    for label, color in entries:
        pdf_rect(page, x, y, 10, 8, fill_rgb=color, stroke_rgb=None)
        pdf_text(page, x + 14, y + 1, label, size=7.5, color_rgb=MUTED)
        x += 100


def build_gantt_pdf(project_name: str, project_code: str, items: list[dict], progress_w: float | None = None) -> bytes:
    generated_at = datetime.now()
    logo = _load_logo()

    parsed_items = []
    for item in items:
        parsed_items.append(
            {
                **item,
                "start_date": date.fromisoformat(item["start_date"]),
                "end_date": date.fromisoformat(item["end_date"]),
            }
        )

    ordered = _order_items(parsed_items)

    if not parsed_items:
        page: list[str] = []
        _page_header(page, logo, project_name, project_code, generated_at, progress_w)
        pdf_text(page, CONTENT_X, PAGE_HEIGHT - 100, "Este proyecto todavía no tiene tareas en el planning.", size=10)
        pdf_bytes = assemble_pdf([page], page_size=(PAGE_WIDTH, PAGE_HEIGHT), images=_images(logo))
        return pdf_bytes

    min_date = min(it["start_date"] for it in parsed_items) - timedelta(days=3)
    max_date = max(it["end_date"] for it in parsed_items) + timedelta(days=3)
    span_days = max(1, (max_date - min_date).days)

    chart_x = CONTENT_X + TITLE_COL_W
    chart_w = CONTENT_W - TITLE_COL_W

    rows_per_page = 24
    chunks = [ordered[i:i + rows_per_page] for i in range(0, len(ordered), rows_per_page)]

    pages: list[list[str]] = []
    for chunk in chunks:
        page = []
        _page_header(page, logo, project_name, project_code, generated_at, progress_w)

        table_top = PAGE_HEIGHT - 90
        header_y = table_top
        week_starts = _week_starts(min_date, max_date)
        grid_bottom = MARGIN + 40

        # Los grupos de mes/año se derivan de las semanas (no de la fecha
        # exacta del dia 1) para que sus lineas divisorias caigan siempre
        # en un borde de semana y nunca corten un numero de semana a la mitad.
        month_groups = _week_groups(week_starts, min_date, span_days, chart_x, chart_w, lambda d: (d.year, d.month))
        year_groups = _week_groups(week_starts, min_date, span_days, chart_x, chart_w, lambda d: d.year)

        week_bounds: list[tuple[date, float, float]] = []
        for idx, w_start in enumerate(week_starts):
            wx = _date_x(w_start, min_date, span_days, chart_x, chart_w)
            next_wx = (
                _date_x(week_starts[idx + 1], min_date, span_days, chart_x, chart_w)
                if idx + 1 < len(week_starts) else chart_x + chart_w
            )
            week_bounds.append((w_start, wx, next_wx))

        # --- Fase 1: todas las lineas primero, para que el texto se dibuje
        # siempre encima y nunca quede cortado por una rejilla ---
        page.append("0.80 0.82 0.87 RG 0.5 w")
        page.append(f"{chart_x:.2f} {header_y - 12:.2f} m {chart_x + chart_w:.2f} {header_y - 12:.2f} l S")
        page.append("0.82 0.84 0.88 RG 0.5 w")
        page.append(f"{CONTENT_X:.2f} {header_y - 24:.2f} m {chart_x + chart_w:.2f} {header_y - 24:.2f} l S")

        for w_start, wx, _next_wx in week_bounds:
            if wx < chart_x - 0.5:
                continue
            page.append("0.90 0.91 0.94 RG 0.25 w")
            page.append(f"{wx:.2f} {header_y - 24:.2f} m {wx:.2f} {grid_bottom:.2f} l S")

        for _key, mx, _x1 in month_groups:
            page.append("0.68 0.70 0.76 RG 0.8 w")
            page.append(f"{mx:.2f} {header_y - 12:.2f} m {mx:.2f} {grid_bottom:.2f} l S")

        # --- Fase 2: texto encima de todas las lineas ---
        for yr, yx0, yx1 in year_groups:
            label = str(yr)
            label_x = max(yx0 + 2, (yx0 + yx1) / 2 - _text_width(label, 8, bold=True) / 2)
            pdf_text(page, label_x, header_y - 8, label, size=8, bold=True, color_rgb=YEAR_COLOR)

        pdf_text(page, CONTENT_X, header_y - 8, "Tarea", size=6.5, bold=True, color_rgb=MUTED)
        pdf_text(page, CONTENT_X + TITLE_W, header_y - 8, "Inicio", size=6.5, bold=True, color_rgb=MUTED)
        pdf_text(page, CONTENT_X + TITLE_W + START_W, header_y - 8, "Fin", size=6.5, bold=True, color_rgb=MUTED)
        pdf_text(page, CONTENT_X + TITLE_W + START_W + END_W, header_y - 8, "%", size=6.5, bold=True, color_rgb=MUTED)

        for (yr, mo), mx, next_x in month_groups:
            label = MONTH_NAMES[mo - 1]
            if (next_x - mx) >= _text_width(label, 6.8, bold=True) + 2:
                label_x = max(mx + 2, (mx + next_x) / 2 - _text_width(label, 6.8, bold=True) / 2)
                pdf_text(page, label_x, header_y - 20, label, size=6.8, bold=True, color_rgb=MONTH_LABEL_COLOR)

        for w_start, wx, next_wx in week_bounds:
            if wx < chart_x - 0.5:
                continue
            label = f"{w_start.day:02d}"
            label_x = (wx + next_wx) / 2 - _text_width(label, 4.6) / 2
            pdf_text(page, label_x, header_y - 31, label, size=4.6, color_rgb=WEEK_LABEL_COLOR)

        y = header_y - 42
        for item, depth in chunk:
            title = ("    " if depth else "") + item["title"]
            pdf_text(page, CONTENT_X, y - 11, title[:22], size=7.5, color_rgb=INK, bold=(depth == 0 and item["source"] != "manual"))
            pdf_text(page, CONTENT_X + TITLE_W, y - 11, item["start_date"].strftime("%d/%m/%y"), size=6.5, color_rgb=MUTED)
            pdf_text(page, CONTENT_X + TITLE_W + START_W, y - 11, item["end_date"].strftime("%d/%m/%y"), size=6.5, color_rgb=MUTED)
            pdf_text(page, CONTENT_X + TITLE_W + START_W + END_W, y - 11, f'{item.get("progress", 0)}%', size=6.5, color_rgb=MUTED)

            color = SOURCE_COLORS.get(item["source"], BRIGHT_BLUE)
            if item["is_milestone"]:
                cx = _date_x(item["start_date"], min_date, span_days, chart_x, chart_w)
                cy = y - ROW_H / 2
                r = 5.0
                page.append(f"{GOLD[0]:.2f} {GOLD[1]:.2f} {GOLD[2]:.2f} rg")
                page.append(f"{cx:.2f} {cy + r:.2f} m {cx + r:.2f} {cy:.2f} l {cx:.2f} {cy - r:.2f} l {cx - r:.2f} {cy:.2f} l h f")
            else:
                bx = _date_x(item["start_date"], min_date, span_days, chart_x, chart_w)
                bx_end = _date_x(item["end_date"], min_date, span_days, chart_x, chart_w)
                bar_h = 9.0 if depth == 0 else 6.5
                bar_w = max(3.0, bx_end - bx)
                bar_y = y - ROW_H / 2 - bar_h / 2
                pdf_rect(page, bx, bar_y, bar_w, bar_h, fill_rgb=_lighten(color), stroke_rgb=color, line_width=0.6)
                progress = max(0, min(100, item.get("progress", 0) or 0))
                if progress:
                    pdf_rect(page, bx, bar_y, bar_w * (progress / 100.0), bar_h, fill_rgb=ORANGE, stroke_rgb=None)
            y -= ROW_H

        _legend(page, MARGIN + 20)
        pages.append(page)

    return assemble_pdf(pages, page_size=(PAGE_WIDTH, PAGE_HEIGHT), images=_images(logo))


def _images(logo: PdfImage | None) -> dict[str, PdfImage]:
    return {"Logo": logo} if logo is not None else {}
