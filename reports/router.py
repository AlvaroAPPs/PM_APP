from __future__ import annotations

import io
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates

from reports.pdf_engine import (
    PAGE_HEIGHT,
    PAGE_WIDTH,
    assemble_pdf,
    pdf_grouped_bar_chart,
    pdf_multi_line_chart,
    pdf_rect,
    pdf_table,
    pdf_text,
)
from reports.project_closures import fetch_closure_report_data

router = APIRouter(tags=["reports"])
templates = Jinja2Templates(directory="templates")

NAVY = (0.122, 0.227, 0.373)
AMBER = (0.725, 0.459, 0.047)
GREEN = (0.082, 0.451, 0.278)
INK = (0.125, 0.122, 0.110)
MUTED = (0.42, 0.42, 0.39)

MARGIN = 15.0
CONTENT_X = MARGIN + 10
CONTENT_W = PAGE_WIDTH - (2 * MARGIN) - 20


def _fmt_int(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _fmt_hours(value: float) -> str:
    return f"{value:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _fmt_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "N/A"


def _clean_text(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in ("", "nan", "none") else text


def _page_frame(page: list[str], subtitle: str, year: int, generated_at) -> None:
    pdf_rect(page, MARGIN, MARGIN, PAGE_WIDTH - (2 * MARGIN), PAGE_HEIGHT - (2 * MARGIN),
             fill_rgb=(0.98, 0.98, 0.97), stroke_rgb=(0.90, 0.91, 0.93), line_width=0.8)
    pdf_rect(page, CONTENT_X, PAGE_HEIGHT - 60, CONTENT_W, 35, fill_rgb=NAVY, stroke_rgb=None)
    pdf_text(page, CONTENT_X + 10, PAGE_HEIGHT - 38, f"Cierre de proyectos {year}", size=15, bold=True,
              color_rgb=(1.0, 1.0, 1.0))
    pdf_text(page, CONTENT_X + 10, PAGE_HEIGHT - 52, subtitle, size=8, color_rgb=(0.85, 0.88, 0.93))
    pdf_text(page, CONTENT_X + CONTENT_W - 190, PAGE_HEIGHT - 38,
              f"Generado: {generated_at.strftime('%d/%m/%Y %H:%M')}", size=7.5, color_rgb=(0.85, 0.88, 0.93))


def _kpi_card(page: list[str], x: float, y: float, w: float, h: float, label: str, value: str) -> None:
    pdf_rect(page, x, y, w, h, fill_rgb=(0.92, 0.93, 0.95), stroke_rgb=(0.83, 0.85, 0.89))
    pdf_text(page, x + 10, y + h - 16, label, size=8, bold=True, color_rgb=MUTED)
    pdf_text(page, x + 10, y + 10, value, size=17, bold=True, color_rgb=INK)


def build_closure_report_pages(data: dict) -> list[list[str]]:
    year = data["year"]
    generated_at = data["generated_at"]
    labels = data["month_labels"]
    actual = data["actual"]
    projections = data["projections"]
    closed_projects = data["closed_projects"]
    pages: list[list[str]] = []

    # --- Pagina 1: cierres reales ---
    page1: list[str] = []
    _page_frame(page1, "Resumen de cierres reales del ano", year, generated_at)

    card_y = PAGE_HEIGHT - 110
    card_w = (CONTENT_W - 20) / 3
    _kpi_card(page1, CONTENT_X, card_y, card_w, 38, "Proyectos cerrados", _fmt_int(data["total_closed_count"]))
    _kpi_card(page1, CONTENT_X + card_w + 10, card_y, card_w, 38, "Horas totales cerradas", f'{_fmt_hours(data["total_closed_hours"])} h')
    _kpi_card(page1, CONTENT_X + 2 * (card_w + 10), card_y, card_w, 38, "Horas medias / proyecto",
              f'{_fmt_hours(data["avg_hours_per_project"])} h')

    chart_h = 280
    chart_y = card_y - 20 - chart_h
    chart_w = (CONTENT_W - 15) / 2
    pdf_grouped_bar_chart(
        page1, CONTENT_X, chart_y, chart_w, chart_h,
        "Proyectos cerrados por mes",
        labels,
        [("Proyectos", NAVY, [float(v) for v in actual["closed_count"]])],
        show_value_labels=True,
    )
    pdf_grouped_bar_chart(
        page1, CONTENT_X + chart_w + 15, chart_y, chart_w, chart_h,
        "Horas totales cerradas por mes",
        labels,
        [("Horas", AMBER, actual["closed_hours"])],
        show_value_labels=True,
    )
    pages.append(page1)

    # --- Pagina(s): detalle de proyectos cerrados ---
    headers = ["Codigo", "Proyecto", "Equipo", "PM", "Fecha cierre", "Horas totales", "Horas reales"]
    col_widths = [85, 200, 140, 140, 75, 75, 75]
    rows_per_page = 26
    detail_rows = [
        [
            _clean_text(item.get("project_code")),
            _clean_text(item.get("project_name")),
            _clean_text(item.get("team")),
            _clean_text(item.get("project_manager")),
            _fmt_date(item.get("date_end")),
            _fmt_hours(item.get("hours") or 0.0),
            _fmt_hours(item.get("real_hours") or 0.0),
        ]
        for item in closed_projects
    ]
    chunks = [detail_rows[i:i + rows_per_page] for i in range(0, len(detail_rows), rows_per_page)] or [[]]
    for chunk in chunks:
        page: list[str] = []
        _page_frame(page, "Detalle de proyectos cerrados", year, generated_at)
        table_top = PAGE_HEIGHT - 80
        if not chunk:
            pdf_text(page, CONTENT_X, table_top - 20, f"No hay proyectos cerrados en {year}.", size=10)
        else:
            pdf_table(page, CONTENT_X, table_top, col_widths, headers, chunk, row_height=15)
        pages.append(page)

    # --- Pagina final: proyeccion ---
    page_proj: list[str] = []
    _page_frame(page_proj, "Proyeccion acumulada hasta fin de ano", year, generated_at)

    series_colors = {"now": NAVY, "w1": AMBER, "w4": GREEN}
    count_series = [
        (projections[key]["label"], series_colors[key], projections[key]["cumulative_count"])
        for key in ("now", "w1", "w4")
    ]
    hours_series = [
        (projections[key]["label"], series_colors[key], projections[key]["cumulative_hours"])
        for key in ("now", "w1", "w4")
    ]
    chart_h2 = 300
    chart_y2 = PAGE_HEIGHT - 100 - chart_h2
    pdf_multi_line_chart(
        page_proj, CONTENT_X, chart_y2, chart_w, chart_h2,
        "Proyeccion acumulada de proyectos cerrados",
        labels, count_series,
    )
    pdf_multi_line_chart(
        page_proj, CONTENT_X + chart_w + 15, chart_y2, chart_w, chart_h2,
        "Proyeccion acumulada de horas cerradas",
        labels, hours_series,
    )
    note_lines = [
        "Metodologia: un proyecto cuenta como cerrado cuando tiene fila en projects_historical (archivado); el mes de cierre es el mes",
        "de su fecha de fin (date_end) mas reciente conocida. Un proyecto cuenta como planificado mientras no este archivado a la fecha",
        "de corte indicada (hoy / hace 1 semana / hace 4 semanas), usando el momento real de archivado para reconstruir el estado pasado.",
        "Las horas son siempre horas totales (ordered_total). La proyeccion acumulada suma cerrado + planificado mes a mes.",
        "Se excluye AMPLIACIONES_VARIOS.",
    ]
    y = chart_y2 - 20
    for line in note_lines:
        pdf_text(page_proj, CONTENT_X, y, line, size=7, color_rgb=MUTED)
        y -= 11
    pages.append(page_proj)

    return pages


@router.get("/informes")
def reports_home(request: Request):
    current_year = date.today().year
    years = [current_year, current_year - 1, current_year - 2]
    return templates.TemplateResponse(
        "reports.html",
        {"request": request, "years": years, "current_year": current_year},
    )


@router.get("/informes/cierre-proyectos.pdf")
def project_closures_pdf(year: int = date.today().year):
    data = fetch_closure_report_data(year)
    pages = build_closure_report_pages(data)
    pdf_bytes = assemble_pdf(pages, page_size=(PAGE_WIDTH, PAGE_HEIGHT))
    filename = f"cierre_proyectos_{year}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
