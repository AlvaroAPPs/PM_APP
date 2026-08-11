"""Datos para el informe 'Cierre de proyectos durante el ano'.

Reglas de negocio (validadas contra datos reales, ver conversacion con
el usuario a partir del proyecto 2411024584):

- Un proyecto cuenta como CERRADO cuando tiene fila en
  `projects_historical` (equivalente a `projects.is_historical = TRUE`).
  Esta es la senal fiable que usa el resto de la app -- el campo
  `project_snapshot.internal_status = 'closed'` NO es fiable: el 23% de
  los proyectos archivados nunca tuvieron una fila con ese valor
  (confirmado con project_id 35591 / codigo 2411024584: is_historical,
  pero su unico snapshot dice internal_status = 'Normal').
- La fecha de cierre es `date_end` de la ultima fila conocida de
  `project_snapshot` de ese proyecto (independientemente de que su
  internal_status diga 'closed' o no).
- Las horas cerradas/planificadas son `ordered_total` (horas totales),
  no `real_hours`: real_hours falta en el 85% de los proyectos cerrados,
  mientras que ordered_total solo falta en el 8%.
- Un proyecto cuenta como PLANIFICADO (aun no cerrado) "a fecha de
  corte" cuando no tiene fila en `projects_historical`, o la tiene pero
  con `moved_to_historical_at` posterior a esa fecha de corte. Esto
  permite reconstruir el estado "hace 1/4 semanas" usando el timestamp
  real de archivado (fiable para cierres recientes; la migracion masiva
  de proyectos legacy ocurrio en 2026-02-09/18, muy anterior a cualquier
  corte de 1-4 semanas).
- El proyecto paraguas interno AMPLIACIONES_VARIOS se excluye siempre.

Nota: el pipeline de importacion (app.py: import_excel, rama ALL) se
corrigio para que a partir de ahora las filas de AllOrders persistan su
propio snapshot (fechas/horas) tanto al cerrar un proyecto como cuando
sigue activo. Antes solo se usaba para mover ordenes a historico, por
eso hay huecos de datos en importaciones anteriores a este cambio.
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
    """Estado de cada proyecto (excluyendo AMPLIACIONES_VARIOS) 'as of' una fecha.

    Devuelve, por proyecto: su snapshot mas reciente conocido hasta la
    fecha de corte (date_end, ordered_total, real_hours) y si ya estaba
    cerrado a esa fecha (is_closed), segun `projects_historical.moved_to_historical_at`.
    Cuando cutoff_date es None se usa el estado actual (ahora mismo).
    """
    cur.execute(
        """
        WITH snap AS (
            SELECT DISTINCT ON (s.project_id)
                s.project_id, s.date_end, s.ordered_total, s.real_hours
            FROM project_snapshot s
            WHERE %(cutoff)s::date IS NULL
               OR to_date(
                      s.snapshot_year::text || to_char(s.snapshot_week, 'FM00') || '1',
                      'IYYYIWID'
                  ) <= %(cutoff)s::date
            ORDER BY s.project_id, s.snapshot_year DESC, s.snapshot_week DESC
        )
        SELECT
            p.id AS project_id,
            p.project_code,
            p.project_name,
            p.team,
            p.project_manager,
            snap.date_end,
            snap.ordered_total,
            snap.real_hours,
            (
                h.project_code IS NOT NULL
                AND (
                    %(cutoff)s::timestamptz IS NULL
                    OR h.moved_to_historical_at <= %(cutoff)s::timestamptz
                )
            ) AS is_closed
        FROM projects p
        LEFT JOIN snap ON snap.project_id = p.id
        LEFT JOIN projects_historical h ON h.project_code = p.project_code
        WHERE p.project_code <> %(excluded_code)s
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
        month_idx = date_end.month - 1
        hours = _to_float(row.get("ordered_total"))

        if row.get("is_closed"):
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
                    "real_hours": _to_float(row.get("real_hours")),
                }
            )
        else:
            planned_count[month_idx] += 1
            planned_hours[month_idx] += hours

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
