"""Datos para el informe 'Cierre de proyectos durante el ano'.

Fuente de datos: `all_orders_snapshot` (una fila por pedido en cada
importacion ALL/AllOrders, foto completa sin mezclar con el seguimiento
semanal incremental de OTS). Esta es la misma tabla que consulta el
usuario a mano en Excel, replicada aqui:

  Internal Status = Closed / Normal
  Project Type = OTSSoftware u OTSRobotic
  Dates End = mes del informe

Un "batch" es el conjunto de filas de una misma importacion ALL
(mismo import_file_id) -- representa el AllOrders completo tal y como
estaba en ese momento. Para "hoy" se usa el batch mas reciente; para
"hace 1/4 semanas" se usa el batch mas reciente que exista hasta esa
fecha de corte (requiere haber importado AllOrders con esa antiguedad).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import psycopg

DB_DSN = os.environ.get("DB_DSN", "postgresql://postgres:TU_PASSWORD@localhost:5432/mecalux")

GENERAL_INTERNAL_PROJECT_CODE = "AMPLIACIONES_VARIOS"

REPORT_PROJECT_TYPES = ("otssoftware", "otsrobotic")

MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _to_float(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def fetch_all_orders_batch_asof(cur: psycopg.Cursor, cutoff: datetime | None) -> list[dict]:
    """Filas del AllOrders completo mas reciente a la fecha de corte indicada.

    Cuando cutoff es None se usa la importacion ALL mas reciente que haya.
    Todas las filas devueltas pertenecen a la MISMA importacion (mismo
    import_file_id) -- no se mezclan datos de importaciones distintas.
    """
    cur.execute(
        """
        WITH batch AS (
            SELECT import_file_id
            FROM all_orders_snapshot
            WHERE %(cutoff)s::timestamptz IS NULL OR imported_at <= %(cutoff)s::timestamptz
            ORDER BY imported_at DESC
            LIMIT 1
        )
        SELECT
            s.project_code, s.project_name, s.team, s.project_manager,
            s.project_type, s.internal_status, s.date_end, s.ordered_total, s.real_hours
        FROM all_orders_snapshot s
        JOIN batch b ON b.import_file_id = s.import_file_id
        WHERE s.project_code <> %(excluded_code)s
          AND lower(s.project_type) = ANY(%(project_types)s)
        """,
        {
            "cutoff": cutoff,
            "excluded_code": GENERAL_INTERNAL_PROJECT_CODE,
            "project_types": list(REPORT_PROJECT_TYPES),
        },
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
        if status not in ("closed", "normal"):
            continue
        month_idx = date_end.month - 1
        hours = _to_float(row.get("ordered_total"))

        if status == "closed":
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
    now = datetime.now()
    cutoffs = [
        ("now", "Hoy", None),
        ("w1", "Hace 1 semana", now - timedelta(days=7)),
        ("w4", "Hace 4 semanas", now - timedelta(days=28)),
    ]

    projections: dict[str, dict] = {}
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            for key, label, cutoff in cutoffs:
                rows = fetch_all_orders_batch_asof(cur, cutoff)
                buckets = build_monthly_buckets(rows, year)
                projections[key] = {"label": label, **buckets}

    actual = projections["now"]
    return {
        "year": year,
        "generated_at": now,
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
