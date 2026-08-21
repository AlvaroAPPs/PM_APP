"""Generacion del Planning Gantt en PDF: cabecera con logo de Mecalux,
nombre/codigo de proyecto, y una fila por tarea/hito/subtarea con su
barra posicionada sobre un eje de meses. Reutiliza el motor generico de
reports/pdf_engine.py (sin dependencias externas).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
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


def _month_starts(min_date: date, max_date: date) -> list[date]:
    months = []
    cursor = date(min_date.year, min_date.month, 1)
    while cursor <= max_date:
        months.append(cursor)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months


def _date_x(d: date, min_date: date, span_days: int, chart_x: float, chart_w: float) -> float:
    offset = (d - min_date).days
    return chart_x + (offset / span_days) * chart_w


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
    entries = [("Fase", NAVY), ("Tarea", BRIGHT_BLUE), ("Del checklist", GREEN), ("Hito", GOLD), ("Avance", ORANGE)]
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
        month_starts = _month_starts(min_date, max_date)
        for m_start in month_starts:
            mx = max(chart_x, _date_x(m_start, min_date, span_days, chart_x, chart_w))
            pdf_text(page, mx + 2, header_y - 9, f"{MONTH_NAMES[m_start.month - 1]} {m_start.year}", size=6.5, bold=True, color_rgb=MUTED)

        pdf_text(page, CONTENT_X, header_y - 9, "Tarea", size=6.5, bold=True, color_rgb=MUTED)
        pdf_text(page, CONTENT_X + TITLE_W, header_y - 9, "Inicio", size=6.5, bold=True, color_rgb=MUTED)
        pdf_text(page, CONTENT_X + TITLE_W + START_W, header_y - 9, "Fin", size=6.5, bold=True, color_rgb=MUTED)
        pdf_text(page, CONTENT_X + TITLE_W + START_W + END_W, header_y - 9, "%", size=6.5, bold=True, color_rgb=MUTED)

        grid_bottom = MARGIN + 40
        for m_start in month_starts:
            mx = max(chart_x, _date_x(m_start, min_date, span_days, chart_x, chart_w))
            page.append("0.88 0.89 0.92 RG 0.4 w")
            page.append(f"{mx:.2f} {header_y - 12:.2f} m {mx:.2f} {grid_bottom:.2f} l S")

        y = header_y - 22
        for item, depth in chunk:
            title = ("    " if depth else "") + item["title"]
            pdf_text(page, CONTENT_X, y - 11, title[:22], size=7.5, color_rgb=INK, bold=(depth == 0 and item["source"] != "manual"))
            pdf_text(page, CONTENT_X + TITLE_W, y - 11, item["start_date"].strftime("%d/%m/%y"), size=6.5, color_rgb=MUTED)
            if not item["is_milestone"]:
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
