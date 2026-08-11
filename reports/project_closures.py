"""Datos para el informe 'Cierre de proyectos durante el ano'.

Reglas de negocio (ver plan / conversacion con el usuario):
- Un proyecto cuenta como CERRADO en la fila de project_snapshot donde
  internal_status = 'closed' (en minusculas). Esa fila es unica por
  proyecto: en cuanto una importacion tipo ALL marca un proyecto como
  closed/hided se archiva (projects.is_historical = TRUE) y las
  importaciones ALL siguientes para ese proyecto se ignoran (ver
  app.py: import_excel, move_project_to_historical).
- El mes de cierre es el mes de esa fila `date_end`.
- Las horas cerradas son `real_hours` de esa misma fila.
- Un proyecto cuenta como PLANIFICADO (aun no cerrado) cuando su ultima
  fila conocida tiene internal_status = 'normal' y una `date_end`
  dentro del ano del informe. Las horas planificadas son
  `ordered_total` de esa fila.
- El proyecto paraguas interno AMPLIACIONES_VARIOS se excluye siempre.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import psycopg

DB_DSN = os.environ.get("DB_DSN", "postgresql://postgres:TU_PASSWORD@localhost:5432/mecalux")

GENERAL_INTERNAL_PROJECT_CODE = "AMPLIACIONES_VARIOS"

MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _to_float(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def fetch_projects_state_asof(cur: psycopg.Cursor, cutoff_date: date | None) -> list[dict]:
    """Ultima fila de snapshot de cada proyecto, opcionalmente 'as of' una fecha.

    Cuando cutoff_date es None, se usa la ultima fila conocida de cada
    proyecto (estado actual). Cuando se indica una fecha, se reconstruye
    el estado tal y como se veia esa semana, usando solo snapshots cuya
    semana ISO (year/week) ya habia ocurrido para esa fecha.
    """
    cur.execute(
        """
        WITH ranked AS (
            SELECT
                p.id AS project_id,
                p.project_code,
                p.project_name,
                p.team,
                p.project_manager,
                s.internal_status,
                s.date_end,
                s.real_hours,
                s.ordered_total,
                ROW_NUMBER() OVER (
                    PARTITION BY p.id
                    ORDER BY s.snapshot_year DESC, s.snapshot_week DESC
                ) AS rn
            FROM project_snapshot s
            JOIN projects p ON p.id = s.project_id
            WHERE p.project_code <> %(excluded_code)s
              AND (
                  %(cutoff)s::date IS NULL
                  OR to_date(
                      s.snapshot_year::text || to_char(s.snapshot_week, 'FM00') || '1',
                      'IYYYIWID'
                  ) <= %(cutoff)s::date
              )
        )
        SELECT project_id, project_code, project_name, team, project_manager,
               internal_status, date_end, real_hours, ordered_total
        FROM ranked
        WHERE rn = 1
        """,
        {"excluded_code": GENERAL_INTERNAL_PROJECT_CODE, "cutoff": cutoff_date},
    )
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def build_monthly_buckets(rows: list[dict], year: int) -> dict:
    closed_count = [0] * 12
    closed_hours = [0.0] * 12
    planned_count = [0] * 12
    planned_hours = [0.0] * 12
    closed_detail: list[dict] = []

    for row in rows:
        date_end = row.get("date_end")
        if not date_end or date_end.year != year:
            continue
        status = (row.get("internal_status") or "").strip().lower()
        month_idx = date_end.month - 1

        if status == "closed":
            hours = _to_float(row.get("real_hours"))
            closed_count[month_idx] += 1
            closed_hours[month_idx] += hours
            closed_detail.append(
                {
                    "project_code": row.get("project_code"),
                    "project_name": row.get("project_name"),
                    "team": row.get("team"),
                    "project_manager": row.get("project_manager"),
                    "date_end": date_end,
                    "hours": hours,
                }
            )
        elif status == "normal":
            planned_count[month_idx] += 1
            planned_hours[month_idx] += _to_float(row.get("ordered_total"))

    combined_count = [c + p for c, p in zip(closed_count, planned_count)]
    combined_hours = [c + p for c, p in zip(closed_hours, planned_hours)]

    def cumulative(values: list[float]) -> list[float]:
        total = 0.0
        result = []
        for value in values:
            total += value
            result.append(total)
        return result

    closed_detail.sort(key=lambda item: item["date_end"])

    return {
        "closed_count": closed_count,
        "closed_hours": closed_hours,
        "planned_count": planned_count,
        "planned_hours": planned_hours,
        "cumulative_count": cumulative(combined_count),
        "cumulative_hours": cumulative(combined_hours),
        "closed_detail": closed_detail,
        "total_closed_count": sum(closed_count),
        "total_closed_hours": sum(closed_hours),
    }


def fetch_closure_report_data(year: int) -> dict:
    today = date.today()
    cutoffs = [
        ("now", "Hoy", None),
        ("w1", "Hace 1 semana", today - timedelta(days=7)),
        ("w4", "Hace 4 semanas", today - timedelta(days=28)),
    ]

    projections: dict[str, dict] = {}
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            for key, label, cutoff in cutoffs:
                rows = fetch_projects_state_asof(cur, cutoff)
                buckets = build_monthly_buckets(rows, year)
                projections[key] = {"label": label, **buckets}

    actual = projections["now"]
    return {
        "year": year,
        "generated_at": datetime.now(),
        "month_labels": MONTH_LABELS,
        "actual": actual,
        "projections": projections,
        "closed_projects": actual["closed_detail"],
        "total_closed_count": actual["total_closed_count"],
        "total_closed_hours": actual["total_closed_hours"],
        "avg_hours_per_project": (
            actual["total_closed_hours"] / actual["total_closed_count"]
            if actual["total_closed_count"]
            else 0.0
        ),
    }
