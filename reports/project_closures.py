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


def fetch_all_orders_batch_asof(cur: psycopg.Cursor, cutoff: date | None) -> list[dict]:
    """Filas del AllOrders completo mas reciente a la fecha de corte indicada.

    "Mas reciente" se determina por la fecha que declara el propio fichero
    (import_file.snapshot_year/snapshot_week, la que indica el usuario al
    subirlo), NO por cuando se inserto en la base de datos -- los ficheros
    antiguos se pueden cargar despues para completar el historico sin que
    tapen al AllOrders mas reciente. Cuando cutoff es None se usa el
    fichero mas reciente que haya. Todas las filas devueltas pertenecen a
    la MISMA importacion (mismo import_file_id).
    """
    cur.execute(
        """
        WITH batch AS (
            SELECT f.id AS import_file_id
            FROM import_file f
            WHERE EXISTS (SELECT 1 FROM all_orders_snapshot s WHERE s.import_file_id = f.id)
              AND (
                  %(cutoff)s::date IS NULL
                  OR to_date(
                      f.snapshot_year::text || to_char(f.snapshot_week, 'FM00') || '1',
                      'IYYYIWID'
                  ) <= %(cutoff)s::date
              )
            ORDER BY f.snapshot_year DESC, f.snapshot_week DESC
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


def _month_window(start: date, count: int) -> list[tuple[int, int]]:
    result = []
    y, m = start.year, start.month
    for _ in range(count):
        result.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


def fetch_latest_batch_ids(cur: psycopg.Cursor, limit: int = 2) -> list[int]:
    """import_file_id de las importaciones ALL mas recientes, por fecha real del fichero."""
    cur.execute(
        """
        SELECT f.id
        FROM import_file f
        WHERE EXISTS (SELECT 1 FROM all_orders_snapshot s WHERE s.import_file_id = f.id)
        ORDER BY f.snapshot_year DESC, f.snapshot_week DESC
        LIMIT %(limit)s
        """,
        {"limit": limit},
    )
    return [row[0] for row in cur.fetchall()]


def fetch_all_orders_rows_for_batch(cur: psycopg.Cursor, import_file_id: int) -> list[dict]:
    cur.execute(
        """
        SELECT project_code, project_name, team, project_manager, project_type,
               internal_status, order_phase, date_end, ordered_total, real_hours
        FROM all_orders_snapshot
        WHERE import_file_id = %(import_file_id)s
          AND project_code <> %(excluded_code)s
          AND lower(project_type) = ANY(%(project_types)s)
        """,
        {
            "import_file_id": import_file_id,
            "excluded_code": GENERAL_INTERNAL_PROJECT_CODE,
            "project_types": list(REPORT_PROJECT_TYPES),
        },
    )
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def fetch_upcoming_closures(cur: psycopg.Cursor, today: date) -> dict[tuple[int, int], dict]:
    """Cierres planificados (Internal Status = Normal) del mes actual y los 2 siguientes,
    segun la importacion AllOrders mas reciente."""
    months = _month_window(date(today.year, today.month, 1), 3)
    result: dict[tuple[int, int], dict] = {m: {"rows": [], "total_hours": 0.0} for m in months}

    batch_ids = fetch_latest_batch_ids(cur, 1)
    if not batch_ids:
        return result

    for row in fetch_all_orders_rows_for_batch(cur, batch_ids[0]):
        if (row.get("internal_status") or "").strip().lower() != "normal":
            continue
        date_end = row.get("date_end")
        if not date_end:
            continue
        key = (date_end.year, date_end.month)
        if key not in result:
            continue
        hours = _to_float(row.get("ordered_total"))
        result[key]["rows"].append(
            {
                "project_code": row.get("project_code"),
                "project_name": row.get("project_name"),
                "team": row.get("team"),
                "phase": row.get("order_phase"),
                "date_end": date_end,
                "hours": hours,
            }
        )
        result[key]["total_hours"] += hours

    for month_key in months:
        result[month_key]["rows"].sort(key=lambda r: r["hours"], reverse=True)
    return result


def fetch_month_changes(cur: psycopg.Cursor, today: date) -> dict[tuple[int, int], list[dict]]:
    """Proyectos cuyo mes de cierre (date_end) cambio entre las 2 importaciones
    AllOrders mas recientes, agrupados por cada uno de los 3 meses afectados
    (mes actual + 2 siguientes) -- solo cuenta si el mes cambia, no el dia."""
    months = _month_window(date(today.year, today.month, 1), 3)
    result: dict[tuple[int, int], list[dict]] = {m: [] for m in months}

    batch_ids = fetch_latest_batch_ids(cur, 2)
    if len(batch_ids) < 2:
        return result

    latest_rows = {r["project_code"]: r for r in fetch_all_orders_rows_for_batch(cur, batch_ids[0])}
    previous_rows = {r["project_code"]: r for r in fetch_all_orders_rows_for_batch(cur, batch_ids[1])}

    for code, new_row in latest_rows.items():
        old_row = previous_rows.get(code)
        if not old_row:
            continue
        new_end = new_row.get("date_end")
        old_end = old_row.get("date_end")
        if not new_end or not old_end:
            continue
        if (new_end.year, new_end.month) == (old_end.year, old_end.month):
            continue
        entry = {
            "project_code": code,
            "project_name": new_row.get("project_name"),
            "team": new_row.get("team"),
            "phase": new_row.get("order_phase"),
            "old_date_end": old_end,
            "new_date_end": new_end,
            "hours": _to_float(new_row.get("ordered_total")),
        }
        for month_key in months:
            if (old_end.year, old_end.month) == month_key or (new_end.year, new_end.month) == month_key:
                result[month_key].append(entry)

    for month_key in months:
        result[month_key].sort(key=lambda r: r["hours"], reverse=True)
    return result


def fetch_closure_report_data(year: int) -> dict:
    now = datetime.now()
    today = now.date()
    cutoffs = [
        ("now", "Hoy", None),
        ("w1", "Hace 1 semana", today - timedelta(days=7)),
        ("w4", "Hace 4 semanas", today - timedelta(days=28)),
    ]

    projections: dict[str, dict] = {}
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            for key, label, cutoff in cutoffs:
                rows = fetch_all_orders_batch_asof(cur, cutoff)
                buckets = build_monthly_buckets(rows, year)
                projections[key] = {"label": label, **buckets}

            upcoming_closures = fetch_upcoming_closures(cur, today)
            month_changes = fetch_month_changes(cur, today)

    actual = projections["now"]
    return {
        "year": year,
        "generated_at": now,
        "today": today,
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
        "upcoming_closures": upcoming_closures,
        "month_changes": month_changes,
    }
