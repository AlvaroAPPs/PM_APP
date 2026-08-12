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
BRIGHT_BLUE = (0.20, 0.55, 0.95)
BRIGHT_GOLD = (1.00, 0.72, 0.15)

MARGIN = 15.0
CONTENT_X = MARGIN + 10
CONTENT_W = PAGE_WIDTH - (2 * MARGIN) - 20

FULL_MONTH_NAMES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def _month_title(month_key: tuple[int, int]) -> str:
    year, month = month_key
    return f"{FULL_MONTH_NAMES[month - 1]} {year}"


def _fmt_int(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _fmt_hours(value: float) -> str:
    return f"{value:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _fmt_hours_signed(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}{_fmt_hours(abs(value))}"


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
    pdf_text(page, x + 10, y + h - 15, label, size=7.5, bold=True, color_rgb=MUTED)
    pdf_text(page, x + 10, y + 11, value, size=15, bold=True, color_rgb=INK)


UPCOMING_HEADERS = ["Proyecto", "Codigo", "Horas totales", "Estado", "Fecha cierre"]
UPCOMING_COL_WIDTHS = [360.0, 100.0, 100.0, 110.0, 110.0]


def _upcoming_closures_pages(month_key: tuple[int, int], info: dict, year: int, generated_at) -> list[list[str]]:
    """Una seccion por equipo (tabla independiente) para los cierres del mes,
    con el estado (Cerrado/Pendiente) coloreado y el total de horas del mes
    entre parentesis en el titulo."""
    title = f"Proximos cierres - {_month_title(month_key)} ({_fmt_hours(info['total_hours'])} h)"
    subtitle = "Proximos cierres"

    teams: dict[str, list[dict]] = {}
    for item in info["rows"]:
        team = _clean_text(item.get("team")) or "Sin equipo"
        teams.setdefault(team, []).append(item)
    for rows in teams.values():
        rows.sort(key=lambda r: r["hours"], reverse=True)

    pages: list[list[str]] = []
    page: list[str] = []
    top = PAGE_HEIGHT - 100

    def new_page() -> float:
        nonlocal page
        page = []
        _page_frame(page, subtitle, year, generated_at)
        pdf_text(page, CONTENT_X, PAGE_HEIGHT - 78, title, size=11, bold=True, color_rgb=INK)
        pages.append(page)
        return top

    y = new_page()

    if not teams:
        pdf_text(page, CONTENT_X, y - 20, f"No hay cierres para {_month_title(month_key)}.", size=10)

    total_w = sum(UPCOMING_COL_WIDTHS)
    row_h = 14.0
    header_h = 18.0
    subtotal_h = 16.0
    gap_h = 10.0

    for team_name in sorted(teams):
        rows = teams[team_name]
        block_h = header_h + (len(rows) * row_h) + subtotal_h + gap_h
        if y - block_h < MARGIN + 25 and y != top:
            y = new_page()

        pdf_rect(page, CONTENT_X, y - header_h, total_w, header_h, fill_rgb=(0.90, 0.91, 0.94), stroke_rgb=(0.82, 0.84, 0.88))
        pdf_text(page, CONTENT_X + 6, y - header_h + 5, f"Equipo: {team_name}", size=8.5, bold=True, color_rgb=INK)
        cx = CONTENT_X
        for header, cw in zip(UPCOMING_HEADERS, UPCOMING_COL_WIDTHS):
            if header != "Proyecto":
                pdf_text(page, cx + 5, y - header_h + 5, header, size=7, bold=True, color_rgb=MUTED)
            cx += cw
        y -= header_h

        team_hours = 0.0
        for row_idx, item in enumerate(rows):
            if row_idx % 2 == 1:
                pdf_rect(page, CONTENT_X, y - row_h, total_w, row_h, fill_rgb=(0.97, 0.97, 0.96), stroke_rgb=None)
            is_closed = item.get("status") == "Cerrado"
            status_color = GREEN if is_closed else MUTED
            cells = [
                _clean_text(item.get("project_name")),
                _clean_text(item.get("project_code")),
                _fmt_hours(item.get("hours") or 0.0),
                item.get("status") or "",
                _fmt_date(item.get("date_end")),
            ]
            cx = CONTENT_X
            for col_idx, (value, cw) in enumerate(zip(cells, UPCOMING_COL_WIDTHS)):
                color = status_color if col_idx == 3 else INK
                pdf_text(page, cx + 5, y - row_h + 4.5, value, size=7.5, bold=(col_idx == 3), color_rgb=color)
                cx += cw
            team_hours += item.get("hours") or 0.0
            y -= row_h

        pdf_text(page, CONTENT_X, y - 11, f"Subtotal {team_name}: {_fmt_hours(team_hours)} h ({_fmt_int(len(rows))} proyectos)",
                  size=7.5, bold=True, color_rgb=INK)
        y -= subtotal_h + gap_h

    if teams:
        pdf_text(page, CONTENT_X, max(MARGIN + 12, y - 4),
                  f"Total horas a cerrar en {_month_title(month_key)}: {_fmt_hours(info['total_hours'])} h ({_fmt_int(len(info['rows']))} proyectos)",
                  size=9, bold=True, color_rgb=INK)

    return pages


CHANGES_HEADERS = ["Proyecto", "Codigo", "Horas totales", "Estado", "Mes anterior", "Mes nuevo"]
CHANGES_COL_WIDTHS = [300.0, 90.0, 90.0, 100.0, 100.0, 100.0]


def _change_direction(item: dict, month_key: tuple[int, int]) -> str | None:
    new_month = (item["new_date_end"].year, item["new_date_end"].month)
    old_month = (item["old_date_end"].year, item["old_date_end"].month)
    if new_month == month_key:
        return "in"
    if old_month == month_key:
        return "out"
    return None


def _month_changes_pages(month_key: tuple[int, int], changes: list[dict], year: int, generated_at) -> list[list[str]]:
    """Una tabla independiente por equipo, igual que en Proximos cierres,
    con el gradiente de horas (entran - salen) por equipo y en el titulo."""
    entries = []
    for item in changes:
        direction = _change_direction(item, month_key)
        if direction is None:
            continue
        entries.append((item, direction))

    total_gradient = sum(item["hours"] if d == "in" else -item["hours"] for item, d in entries)
    title = f"Cambios de fecha de cierre - {_month_title(month_key)} (gradiente total: {_fmt_hours_signed(total_gradient)} h)"
    subtitle = "Cambios de fecha de cierre"

    teams: dict[str, list[tuple[dict, str]]] = {}
    for item, direction in entries:
        team = _clean_text(item.get("team")) or "Sin equipo"
        teams.setdefault(team, []).append((item, direction))
    for rows in teams.values():
        rows.sort(key=lambda pair: pair[0]["hours"], reverse=True)

    pages: list[list[str]] = []
    page: list[str] = []
    top = PAGE_HEIGHT - 100

    def new_page() -> float:
        nonlocal page
        page = []
        _page_frame(page, subtitle, year, generated_at)
        pdf_text(page, CONTENT_X, PAGE_HEIGHT - 78, title, size=11, bold=True, color_rgb=INK)
        pages.append(page)
        return top

    y = new_page()

    if not teams:
        pdf_text(page, CONTENT_X, y - 20, f"No hay cambios de mes de cierre para {_month_title(month_key)} desde el snapshot anterior.", size=10)

    total_w = sum(CHANGES_COL_WIDTHS)
    row_h = 14.0
    header_h = 18.0
    subtotal_h = 16.0
    gap_h = 10.0

    for team_name in sorted(teams):
        rows = teams[team_name]
        block_h = header_h + (len(rows) * row_h) + subtotal_h + gap_h
        if y - block_h < MARGIN + 25 and y != top:
            y = new_page()

        pdf_rect(page, CONTENT_X, y - header_h, total_w, header_h, fill_rgb=(0.90, 0.91, 0.94), stroke_rgb=(0.82, 0.84, 0.88))
        pdf_text(page, CONTENT_X + 6, y - header_h + 5, f"Equipo: {team_name}", size=8.5, bold=True, color_rgb=INK)
        cx = CONTENT_X
        for header, cw in zip(CHANGES_HEADERS, CHANGES_COL_WIDTHS):
            if header != "Proyecto":
                pdf_text(page, cx + 5, y - header_h + 5, header, size=7, bold=True, color_rgb=MUTED)
            cx += cw
        y -= header_h

        team_gradient = 0.0
        for row_idx, (item, direction) in enumerate(rows):
            if row_idx % 2 == 1:
                pdf_rect(page, CONTENT_X, y - row_h, total_w, row_h, fill_rgb=(0.97, 0.97, 0.96), stroke_rgb=None)
            hours = item.get("hours") or 0.0
            team_gradient += hours if direction == "in" else -hours
            cells = [
                _clean_text(item.get("project_name")),
                _clean_text(item.get("project_code")),
                _fmt_hours(hours),
                _clean_text(item.get("phase")),
                _month_title((item["old_date_end"].year, item["old_date_end"].month)),
                _month_title((item["new_date_end"].year, item["new_date_end"].month)),
            ]
            cx = CONTENT_X
            for value, cw in zip(cells, CHANGES_COL_WIDTHS):
                pdf_text(page, cx + 5, y - row_h + 4.5, value, size=7.5, color_rgb=INK)
                cx += cw
            y -= row_h

        pdf_text(page, CONTENT_X, y - 11, f"Gradiente {team_name}: {_fmt_hours_signed(team_gradient)} h ({_fmt_int(len(rows))} cambios)",
                  size=7.5, bold=True, color_rgb=INK)
        y -= subtotal_h + gap_h

    return pages


def build_closure_report_pages(data: dict) -> list[list[str]]:
    year = data["year"]
    generated_at = data["generated_at"]
    labels = data["month_labels"]
    actual = data["actual"]
    projections = data["projections"]
    chart_w = (CONTENT_W - 15) / 2
    pages: list[list[str]] = []

    # --- Pagina 1: cierres reales ---
    page1: list[str] = []
    _page_frame(page1, "Resumen de cierres reales del ano", year, generated_at)

    card_y = PAGE_HEIGHT - 120
    card_h = 48
    card_gap = 10
    card_w = (CONTENT_W - (4 * card_gap)) / 5
    year_total_count = actual["cumulative_count"][-1] if actual["cumulative_count"] else 0.0
    year_total_hours = actual["cumulative_hours"][-1] if actual["cumulative_hours"] else 0.0
    kpi_cards = [
        ("Proyectos cerrados", _fmt_int(data["total_closed_count"])),
        ("Horas totales cerradas", f'{_fmt_hours(data["total_closed_hours"])} h'),
        ("Horas medias / proyecto", f'{_fmt_hours(data["avg_hours_per_project"])} h'),
        (f"Cierres {year} (proyectos)", _fmt_int(year_total_count)),
        (f"Cierres {year} (horas)", f'{_fmt_hours(year_total_hours)} h'),
    ]
    for idx, (label, value) in enumerate(kpi_cards):
        _kpi_card(page1, CONTENT_X + idx * (card_w + card_gap), card_y, card_w, card_h, label, value)

    chart_h = 260
    chart_y = card_y - 20 - chart_h
    pdf_grouped_bar_chart(
        page1, CONTENT_X, chart_y, chart_w, chart_h,
        "Proyectos cerrados y planificados por mes",
        labels,
        [
            ("Cerrados", NAVY, [float(v) for v in actual["closed_count"]]),
            ("Planificados", BRIGHT_BLUE, [float(v) for v in actual["planned_count"]]),
        ],
        show_value_labels=True,
        stacked=True,
    )
    pdf_grouped_bar_chart(
        page1, CONTENT_X + chart_w + 15, chart_y, chart_w, chart_h,
        "Horas totales cerradas y planificadas por mes",
        labels,
        [
            ("Horas cerradas", AMBER, actual["closed_hours"]),
            ("Horas planificadas", BRIGHT_GOLD, actual["planned_hours"]),
        ],
        show_value_labels=True,
        stacked=True,
    )
    pages.append(page1)

    # --- Pagina: proyecciones (graficas) ---
    page_proj: list[str] = []
    _page_frame(page_proj, "Proyecciones", year, generated_at)
    pdf_text(page_proj, CONTENT_X, PAGE_HEIGHT - 78, "Proyecciones", size=13, bold=True, color_rgb=INK)

    series_colors = {"now": NAVY, "w1": AMBER, "w4": GREEN}
    count_series = [
        (projections[key]["label"], series_colors[key], projections[key]["cumulative_count"])
        for key in ("now", "w1", "w4")
    ]
    hours_series = [
        (projections[key]["label"], series_colors[key], projections[key]["cumulative_hours"])
        for key in ("now", "w1", "w4")
    ]
    chart_h2 = 260
    chart_y2 = PAGE_HEIGHT - 108 - chart_h2
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
    pages.append(page_proj)

    # --- Pagina: evolucion total por semana ---
    page_data: list[str] = []
    _page_frame(page_data, "Proyecciones", year, generated_at)
    pdf_text(page_data, CONTENT_X, PAGE_HEIGHT - 78, "Evolucion total por semana", size=11, bold=True, color_rgb=INK)
    pdf_text(
        page_data, CONTENT_X, PAGE_HEIGHT - 92,
        f"Total de proyectos y horas de {year} (cerrados + planificados), y la parte ya cerrada, en cada importacion AllOrders.",
        size=8, color_rgb=MUTED,
    )

    snapshot_headers = ["Nº semana", "N Proyectos", "Horas proyectos", "Proyectos cerrados", "Horas cerradas"]
    snapshot_col_widths = [90, 110, 120, 120, 120]
    snapshot_rows = [
        [
            f"{item['snapshot_year']}-W{item['snapshot_week']:02d}",
            _fmt_int(item["total_count"]),
            f'{_fmt_hours(item["total_hours"])} h',
            _fmt_int(item["closed_count"]),
            f'{_fmt_hours(item["closed_hours"])} h',
        ]
        for item in data["snapshot_year_totals"]
    ]
    table_top = PAGE_HEIGHT - 112
    if not snapshot_rows:
        pdf_text(page_data, CONTENT_X, table_top - 20, "No hay importaciones AllOrders disponibles.", size=10)
    else:
        pdf_table(page_data, CONTENT_X, table_top, snapshot_col_widths, snapshot_headers, snapshot_rows, row_height=15)
    pages.append(page_data)

    # --- Paginas: proximos cierres (mes actual + 2 siguientes), por equipo ---
    for month_key, info in data["upcoming_closures"].items():
        pages.extend(_upcoming_closures_pages(month_key, info, year, generated_at))

    # --- Paginas: cambios de fecha de cierre (mes actual + 2 siguientes), por equipo ---
    for month_key, changes in data["month_changes"].items():
        pages.extend(_month_changes_pages(month_key, changes, year, generated_at))

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
