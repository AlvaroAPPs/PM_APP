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
estaba en ese momento. Para "hoy" se usa el ultimo batch disponible;
para "hace 1/4 semanas" se usa el batch anterior y el que hace 4
posiciones (no una fecha de calendario -7/-28 dias, que puede coincidir
con "hoy" si no hay importaciones repartidas en esas fechas exactas).
"""

from __future__ import annotations

import os
from datetime import date, datetime

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


def _effective_hours(row: dict) -> float:
    """Horas a usar en calculos/informe, por orden de prioridad:
    1. correccion manual (projects_historical.closed_hours_override),
    2. horas congeladas del cierre (`frozen_hours`, solo filas cerradas:
       las del momento en que el proyecto se cerro, o las que el usuario
       acepto al revisar un cambio en origen),
    3. horas totales del pedido en ese Excel (ordered_total).
    Pendientes/planificados no tienen (1) ni (2), asi que usan (3)."""
    override = row.get("closed_hours_override")
    if override is not None:
        return _to_float(override)
    frozen = row.get("frozen_hours")
    if frozen is not None:
        return _to_float(frozen)
    return _to_float(row.get("ordered_total"))


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
        hours = _effective_hours(row)

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
        "combined_count": combined_count,
        "combined_hours": combined_hours,
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


# Si la misma semana (snapshot_year, snapshot_week) se importa varias veces
# (p.ej. una recarga tras un problema), un "batch" debe contar una sola vez:
# nos quedamos con el import_file mas reciente (uploaded_at, con el id como
# desempate) de cada semana, y descartamos el resto para todo el informe.
_LATEST_PER_WEEK_SQL = """
    SELECT id, snapshot_year, snapshot_week
    FROM (
        SELECT DISTINCT ON (f.snapshot_year, f.snapshot_week)
               f.id, f.snapshot_year, f.snapshot_week
        FROM import_file f
        WHERE EXISTS (SELECT 1 FROM all_orders_snapshot s WHERE s.import_file_id = f.id)
        ORDER BY f.snapshot_year, f.snapshot_week, f.uploaded_at DESC, f.id DESC
    ) dedup
"""


def fetch_latest_batch_ids(cur: psycopg.Cursor, limit: int = 2) -> list[int]:
    """import_file_id de las semanas ALL mas recientes (una por semana, la
    ultima subida de cada una si se repitio), por fecha real del fichero."""
    cur.execute(
        f"""
        {_LATEST_PER_WEEK_SQL}
        ORDER BY snapshot_year DESC, snapshot_week DESC
        LIMIT %(limit)s
        """,
        {"limit": limit},
    )
    return [row[0] for row in cur.fetchall()]


HOURS_TOLERANCE = 0.005

CLOSED_HOURS_REVIEW_DDL = """
    CREATE TABLE IF NOT EXISTS closed_hours_review (
        project_code TEXT PRIMARY KEY,
        accepted_hours NUMERIC,
        dismissed_source_hours NUMERIC,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
"""


def ensure_closed_hours_review_storage(cur: psycopg.Cursor) -> None:
    cur.execute(CLOSED_HOURS_REVIEW_DDL)


def fetch_closed_hours_tracking(cur: psycopg.Cursor) -> dict[str, dict]:
    """Horas de cierre 'congeladas' de cada proyecto que en el ultimo AllOrders
    esta Closed, y si el Excel las ha cambiado desde entonces.

    Horas congeladas = ordered_total de la primera semana de la racha actual
    de Closed (si el proyecto se reabrio y volvio a cerrar, cuenta la ultima
    racha), salvo que el usuario haya aceptado un nuevo valor al revisarlo.
    Una semana subida varias veces cuenta una sola vez (la ultima carga).

    Cada entrada trae `pending_review`: el Excel actual difiere de lo
    congelado, no hay correccion manual y el usuario no ha descartado ya
    ese mismo valor. Es lo que se avisa para revisar."""
    ensure_closed_hours_review_storage(cur)
    cur.execute(
        f"""
        SELECT s.project_code, s.project_name, s.team, lower(s.internal_status),
               s.ordered_total, b.snapshot_year, b.snapshot_week
        FROM all_orders_snapshot s
        JOIN ({_LATEST_PER_WEEK_SQL}) b ON b.id = s.import_file_id
        WHERE s.project_code <> %(excluded_code)s
          AND lower(s.project_type) = ANY(%(project_types)s)
        ORDER BY s.project_code, b.snapshot_year, b.snapshot_week
        """,
        {"excluded_code": GENERAL_INTERNAL_PROJECT_CODE, "project_types": list(REPORT_PROJECT_TYPES)},
    )

    streaks: dict[str, dict] = {}
    for code, name, team, status, hours, year, week in cur.fetchall():
        if status == "normal":
            streaks.pop(code, None)
            continue
        if status != "closed":
            continue
        entry = streaks.get(code)
        if entry is None:
            entry = {
                "project_code": code,
                "baseline_hours": None if hours is None else float(hours),
                "baseline_year": year,
                "baseline_week": week,
                "changed_year": None,
                "changed_week": None,
            }
            streaks[code] = entry
        latest_hours = None if hours is None else float(hours)
        entry.update(project_name=name, team=team, latest_hours=latest_hours, latest_year=year, latest_week=week)
        if (
            entry["changed_week"] is None
            and abs(_to_float(latest_hours) - _to_float(entry["baseline_hours"])) > HOURS_TOLERANCE
        ):
            entry["changed_year"], entry["changed_week"] = year, week

    # Solo cuentan los que siguen Closed en el ultimo AllOrders cargado.
    latest_batch = fetch_latest_batch_ids(cur, 1)
    if latest_batch:
        cur.execute(
            "SELECT project_code FROM all_orders_snapshot WHERE import_file_id = %s AND lower(internal_status) = 'closed'",
            (latest_batch[0],),
        )
        closed_now = {row[0] for row in cur.fetchall()}
        streaks = {code: entry for code, entry in streaks.items() if code in closed_now}

    cur.execute("SELECT project_code, accepted_hours, dismissed_source_hours FROM closed_hours_review")
    reviews = {row[0]: row for row in cur.fetchall()}
    cur.execute("SELECT project_code, closed_hours_override FROM projects_historical WHERE closed_hours_override IS NOT NULL")
    overrides = {row[0]: float(row[1]) for row in cur.fetchall()}

    for code, entry in streaks.items():
        review = reviews.get(code)
        accepted = float(review[1]) if review and review[1] is not None else None
        dismissed = float(review[2]) if review and review[2] is not None else None
        frozen = accepted if accepted is not None else entry["baseline_hours"]
        latest = _to_float(entry["latest_hours"])
        differs = frozen is not None and abs(latest - frozen) > HOURS_TOLERANCE
        already_dismissed = dismissed is not None and abs(dismissed - latest) <= HOURS_TOLERANCE
        entry["frozen_hours"] = frozen
        entry["manual_override"] = overrides.get(code)
        entry["pending_review"] = bool(differs and code not in overrides and not already_dismissed)
    return streaks


def count_pending_hours_reviews() -> int:
    """Numero de proyectos cerrados con horas cambiadas en origen pendientes de
    revisar (para avisar en la pantalla de Informes). Si la base de datos no
    responde devuelve 0: es solo un aviso, no debe romper la pantalla."""
    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                tracking = fetch_closed_hours_tracking(cur)
            conn.commit()
    except psycopg.Error:
        return 0
    return sum(1 for entry in tracking.values() if entry["pending_review"])


def frozen_hours_map(tracking: dict[str, dict]) -> dict[str, float]:
    return {code: entry["frozen_hours"] for code, entry in tracking.items() if entry["frozen_hours"] is not None}


def save_closed_hours_review(cur: psycopg.Cursor, project_code: str, action: str, source_hours: float) -> None:
    """action='keep': mantener las horas congeladas y no volver a avisar mientras
    el Excel siga con ese mismo valor. action='accept': pasar a usar las horas
    actuales del Excel como nuevas horas congeladas."""
    ensure_closed_hours_review_storage(cur)
    if action == "accept":
        cur.execute(
            """
            INSERT INTO closed_hours_review (project_code, accepted_hours, dismissed_source_hours, updated_at)
            VALUES (%s, %s, NULL, now())
            ON CONFLICT (project_code) DO UPDATE
            SET accepted_hours = EXCLUDED.accepted_hours, dismissed_source_hours = NULL, updated_at = now()
            """,
            (project_code, source_hours),
        )
    elif action == "keep":
        cur.execute(
            """
            INSERT INTO closed_hours_review (project_code, dismissed_source_hours, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT (project_code) DO UPDATE
            SET dismissed_source_hours = EXCLUDED.dismissed_source_hours, updated_at = now()
            """,
            (project_code, source_hours),
        )
    else:
        raise ValueError(f"accion desconocida: {action}")


def fetch_all_orders_rows_for_batch(
    cur: psycopg.Cursor, import_file_id: int, frozen: dict[str, float] | None = None
) -> list[dict]:
    cur.execute(
        """
        SELECT s.project_code, s.project_name, s.team, s.project_manager, s.project_type,
               s.internal_status, s.order_phase, s.date_end, s.ordered_total, s.real_hours,
               h.closed_hours_override
        FROM all_orders_snapshot s
        LEFT JOIN projects_historical h
          ON UPPER(BTRIM(h.project_code)) = UPPER(BTRIM(s.project_code))
        WHERE s.import_file_id = %(import_file_id)s
          AND s.project_code <> %(excluded_code)s
          AND lower(s.project_type) = ANY(%(project_types)s)
        """,
        {
            "import_file_id": import_file_id,
            "excluded_code": GENERAL_INTERNAL_PROJECT_CODE,
            "project_types": list(REPORT_PROJECT_TYPES),
        },
    )
    columns = [desc[0] for desc in cur.description]
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    if frozen:
        for row in rows:
            if (row.get("internal_status") or "").strip().lower() == "closed" and row["project_code"] in frozen:
                row["frozen_hours"] = frozen[row["project_code"]]
    return rows


def fetch_snapshot_year_totals(cur: psycopg.Cursor, year: int, frozen: dict[str, float] | None = None) -> list[dict]:
    """Evolucion del total del ano (cerrado + planificado) segun cada
    semana AllOrders disponible (una por semana, la ultima subida de cada
    una si se repitio), ordenado de la mas antigua a la mas reciente --
    para ver como cambia la previsión con cada snapshot."""
    cur.execute(
        f"""
        {_LATEST_PER_WEEK_SQL}
        ORDER BY snapshot_year ASC, snapshot_week ASC
        """
    )
    batches = cur.fetchall()
    result: list[dict] = []
    for import_file_id, snapshot_year, snapshot_week in batches:
        rows = fetch_all_orders_rows_for_batch(cur, import_file_id, frozen)
        buckets = build_monthly_buckets(rows, year)
        result.append(
            {
                "snapshot_year": snapshot_year,
                "snapshot_week": snapshot_week,
                "total_count": buckets["cumulative_count"][-1] if buckets["cumulative_count"] else 0.0,
                "total_hours": buckets["cumulative_hours"][-1] if buckets["cumulative_hours"] else 0.0,
                "closed_count": buckets["total_closed_count"],
                "closed_hours": buckets["total_closed_hours"],
            }
        )
    return result


def fetch_upcoming_closures(
    cur: psycopg.Cursor, today: date, frozen: dict[str, float] | None = None
) -> dict[tuple[int, int], dict]:
    """Cierres (cerrados y pendientes) del mes actual y los 2 siguientes,
    segun la importacion AllOrders mas reciente. `status` indica si ese
    pedido ya esta Cerrado o sigue Pendiente."""
    months = _month_window(date(today.year, today.month, 1), 3)
    result: dict[tuple[int, int], dict] = {m: {"rows": [], "total_hours": 0.0} for m in months}

    batch_ids = fetch_latest_batch_ids(cur, 1)
    if not batch_ids:
        return result

    for row in fetch_all_orders_rows_for_batch(cur, batch_ids[0], frozen):
        status_raw = (row.get("internal_status") or "").strip().lower()
        if status_raw not in ("closed", "normal"):
            continue
        date_end = row.get("date_end")
        if not date_end:
            continue
        key = (date_end.year, date_end.month)
        if key not in result:
            continue
        hours = _effective_hours(row)
        result[key]["rows"].append(
            {
                "project_code": row.get("project_code"),
                "project_name": row.get("project_name"),
                "team": row.get("team"),
                "status": "Cerrado" if status_raw == "closed" else "Pendiente",
                "date_end": date_end,
                "hours": hours,
            }
        )
        result[key]["total_hours"] += hours

    for month_key in months:
        result[month_key]["rows"].sort(key=lambda r: r["hours"], reverse=True)
    return result


def fetch_month_changes(
    cur: psycopg.Cursor, today: date, frozen: dict[str, float] | None = None
) -> dict[tuple[int, int], list[dict]]:
    """Proyectos cuyo mes de cierre (date_end) cambio entre las 2 importaciones
    AllOrders mas recientes, agrupados por cada uno de los 3 meses afectados
    (mes actual + 2 siguientes) -- solo cuenta si el mes cambia, no el dia."""
    months = _month_window(date(today.year, today.month, 1), 3)
    result: dict[tuple[int, int], list[dict]] = {m: [] for m in months}

    batch_ids = fetch_latest_batch_ids(cur, 2)
    if len(batch_ids) < 2:
        return result

    latest_rows = {r["project_code"]: r for r in fetch_all_orders_rows_for_batch(cur, batch_ids[0], frozen)}
    previous_rows = {r["project_code"]: r for r in fetch_all_orders_rows_for_batch(cur, batch_ids[1], frozen)}

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
            "hours": _effective_hours(new_row),
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
    # Posiciones ordinales entre los snapshots disponibles, no fechas de
    # calendario: el snapshot mas reciente, el inmediatamente anterior y
    # el que hace 4 importaciones. Con cadencia semanal de AllOrders esto
    # equivale aproximadamente a hoy / hace 1 semana / hace 4 semanas,
    # pero no depende de que existan importaciones justo en esos dias.
    snapshot_specs = [
        ("now", "Semana actual", 0),
        ("w1", "Semana Anterior", 1),
        ("w4", "Mes anterior", 4),
    ]

    projections: dict[str, dict] = {}
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            tracking = fetch_closed_hours_tracking(cur)
            frozen = frozen_hours_map(tracking)
            pending_review_count = sum(1 for entry in tracking.values() if entry["pending_review"])

            batch_ids = fetch_latest_batch_ids(cur, limit=5)
            for key, label, offset in snapshot_specs:
                rows = fetch_all_orders_rows_for_batch(cur, batch_ids[offset], frozen) if offset < len(batch_ids) else []
                buckets = build_monthly_buckets(rows, year)
                projections[key] = {"label": label, **buckets}

            upcoming_closures = fetch_upcoming_closures(cur, today, frozen)
            month_changes = fetch_month_changes(cur, today, frozen)
            snapshot_year_totals = fetch_snapshot_year_totals(cur, year, frozen)

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
        "snapshot_year_totals": snapshot_year_totals,
        "pending_review_count": pending_review_count,
    }
