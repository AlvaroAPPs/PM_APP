"""Informe de direccion "Estado Ampliaciones" (cada ~2 semanas).

Sustituye al Excel generador con macros (modGraficos, modCalculosSnapshotOTS,
modComparadorProyectos, modEntregasAcumuladas). La logica de calculo replica
esas macros tal cual para que las cifras coincidan con los informes previos.

Cada informe parte de un "corte" (`informe_cortes`): una importacion
AllOrders + una importacion OTS (horas reales) en una fecha. Al crear el corte
se calculan y congelan sus metricas, asi el historico de los graficos no se
recalcula en cada generacion. Los cortes son de tipo DIRECCION o INTERNO:

- Los graficos historicos solo muestran cortes DIRECCION.
- Las entradas/salidas se calculan contra el ultimo corte DIRECCION anterior
  (los INTERNO se ignoran), sea cual sea el tiempo transcurrido.

Fuente: `all_orders_snapshot` filtrado por equipos y tipo de proyecto
(OTSSoftware / OTSRobotic), igual que la hoja que se pegaba en el Excel.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date, timedelta

import psycopg

from reports.project_closures import (
    _effective_hours,
    _select_vanished_rows,
    build_vanished_rows,
    fetch_all_orders_rows_for_batch,
    fetch_closed_hours_tracking,
    fetch_vanished_closures,
    frozen_hours_map,
)

DB_DSN = os.environ.get("DB_DSN", "postgresql://postgres:TU_PASSWORD@localhost:5432/mecalux")

TIPO_DIRECCION = "DIRECCION"
TIPO_INTERNO = "INTERNO"

DEFAULT_TEAMS = [
    "AMPLIACIONES",
    "AMPLIACIONES T1",
    "AMPLIACIONES T2",
    "AMPLIACIONES T3",
    "AMPLIACIONES T4",
    "AMPLIACIONES BADAJOZ T1",
    "AMPLIACIONES BADAJOZ T2",
    "AMPLIACIONES CONSULTORIA",
    "Queue (OTS)",
    "Taller",
]
DEFAULT_PROJECT_TYPES = ["OTSSoftware", "OTSRobotic"]

# Entregas acumuladas del ano anterior (hoja HistoricoManual del Excel),
# guardadas en app_settings por ano: {"horas": [12], "proyectos": [12]}.
SETTING_ENTREGAS_PREFIX = "informe_direccion_entregas_"

MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


# ------------------------------------
# Almacenamiento
# ------------------------------------

def ensure_informe_storage(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS informe_cortes (
            id BIGSERIAL PRIMARY KEY,
            fecha_corte DATE NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('DIRECCION', 'INTERNO')) DEFAULT 'DIRECCION',
            origen TEXT NOT NULL CHECK (origen IN ('APP', 'EXCEL', 'MANUAL')) DEFAULT 'APP',
            all_orders_import_id BIGINT REFERENCES import_file(id) ON DELETE SET NULL,
            ots_import_id BIGINT REFERENCES import_file(id) ON DELETE SET NULL,
            equipos JSONB NOT NULL DEFAULT '[]'::jsonb,
            tipos_proyecto JSONB NOT NULL DEFAULT '[]'::jsonb,
            metricas JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_informe_cortes_fecha
        ON informe_cortes (fecha_corte);
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


# ------------------------------------
# Helpers numericos (mismo comportamiento que las macros)
# ------------------------------------

def _num(value: object) -> float:
    if value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(number) else number


def _round_excel(value: float) -> int:
    """WorksheetFunction.Round(x, 0): redondeo half away from zero."""
    return int(math.floor(abs(value) + 0.5)) * (1 if value >= 0 else -1)


def _norm(value: object) -> str:
    return "" if value is None else str(value).strip().upper()


def _clean(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in ("nan", "none") else text


def _ordered(row: dict) -> float:
    return _num(row.get("ordered_n")) + _num(row.get("ordered_e"))


def _is_normal(row: dict) -> bool:
    return _norm(row.get("internal_status")) == "NORMAL"


def _is_closed(row: dict) -> bool:
    return _norm(row.get("internal_status")) == "CLOSED"


def _size_group(hours: float) -> str:
    """Tramos de las macros: <=100 / >100 y <400 / >=400."""
    if hours <= 100:
        return "s"
    if hours < 400:
        return "m"
    return "l"


def _unique_by_code(rows: list[dict]) -> list[dict]:
    """Las macros de los graficos 1-5 cuentan solo la primera fila de cada codigo."""
    seen: set[str] = set()
    unique = []
    for row in rows:
        code = _clean(row.get("project_code"))
        if not code or code in seen:
            continue
        seen.add(code)
        unique.append(row)
    return unique


def _is_executable(row: dict, fecha_corte: date) -> bool:
    phase = _norm(row.get("order_phase"))
    if phase in ("STOPPED", "REMOTEHYPERCARE"):
        return False
    if phase == "DESIGN":
        design = row.get("date_design")
        if isinstance(design, date) and design > fecha_corte + timedelta(days=15):
            return False
    return True


def _pending_hours(row: dict) -> float:
    progress = _num(row.get("status_pct")) / 100.0
    progress = min(max(progress, 0.0), 1.0)
    return _ordered(row) * (1 - progress)


def _red_green(fact: float, base: float) -> tuple[float, float]:
    diff = fact - base
    return (diff, 0.0) if diff < 0 else (0.0, diff)


# ------------------------------------
# Calculo de metricas de un corte
# ------------------------------------

def calcular_metricas(rows: list[dict], real_hours: dict[str, float], fecha_corte: date) -> dict:
    """Metricas de los graficos 1-7 para las filas (ya filtradas) de un AllOrders.

    `real_hours`: horas reales del OTS por codigo de proyecto (columna Real).
    """
    unique_normal = [r for r in _unique_by_code(rows) if _is_normal(r)]

    # Grafico 1: proyectos en curso
    parados = sum(1 for r in unique_normal if _norm(r.get("order_phase")) == "STOPPED")
    g1 = {"totales": len(unique_normal), "activos": len(unique_normal) - parados, "parados": parados}

    # Graficos 2-5: horas totales / pendientes / ejecutables, por tramos
    tot = {"s": 0.0, "m": 0.0, "l": 0.0}
    pend = {"s": 0.0, "m": 0.0, "l": 0.0}
    ejec = {"s": 0.0, "m": 0.0, "l": 0.0}
    g_tot = g_pend = g_ejec = 0.0
    for row in unique_normal:
        ordered = _ordered(row)
        pending = _pending_hours(row)
        executable = pending if _is_executable(row, fecha_corte) else 0.0
        g_tot += ordered
        g_pend += pending
        g_ejec += executable
        # Igual que la macro: cada valor se clasifica en el tramo de su propio importe.
        tot[_size_group(ordered)] += ordered
        pend[_size_group(pending)] += pending
        ejec[_size_group(executable)] += executable

    g2 = {"totales": _round_excel(g_tot), "pendientes": _round_excel(g_pend), "ejecutables": _round_excel(g_ejec)}
    tramos = {
        group: {"total": _round_excel(tot[group]), "pendiente": _round_excel(pend[group]), "ejecutable": _round_excel(ejec[group])}
        for group in ("s", "m", "l")
    }

    # Graficos 6 y 7: facturacion vs horas invertidas / avance (todas las filas Normal)
    inv = {k: 0.0 for k in ("total", "s", "m", "l")}
    fact = {k: 0.0 for k in ("total", "s", "m", "l")}
    avance = {k: 0.0 for k in ("total", "s", "m", "l")}
    for row in rows:
        if not _is_normal(row):
            continue
        hours_offer = _ordered(row)
        pay_total = _num(row.get("payment_total"))
        price_hour = pay_total / hours_offer if hours_offer > 0 else 0.0
        code = _clean(row.get("project_code")).upper()
        row_inv = real_hours.get(code, 0.0) * price_hour
        row_fact = pay_total * _num(row.get("payment_inv")) / 100.0
        row_avance = pay_total * _num(row.get("status_pct")) / 100.0
        group = _size_group(hours_offer)
        for key in ("total", group):
            inv[key] += row_inv
            fact[key] += row_fact
            avance[key] += row_avance

    def _billing(base: dict) -> dict:
        result = {}
        for key in ("total", "s", "m", "l"):
            red, green = _red_green(fact[key], base[key])
            result[key] = {"base": base[key], "facturado": fact[key], "rojo": red, "verde": green}
        return result

    return {
        "proyectos": g1,
        "horas": g2,
        "tramos": tramos,
        "horas_vs_facturacion": _billing(inv),
        "avance_vs_facturacion": _billing(avance),
    }


def calcular_entregas(rows: list[dict], fecha_corte: date) -> dict:
    """Graficos 8 y 9: horas y n.o de proyectos cerrados acumulados por mes
    (Internal Status = Closed y fecha End en el ano del corte), hasta el mes del corte.

    Las horas de cada cierre siguen la misma prioridad que el informe de
    Cierre de proyectos (`_effective_hours`): correccion manual, horas
    congeladas al cerrarse y, si no hay ninguna, las horas del AllOrders."""
    horas = [0.0] * 12
    proyectos = [0] * 12
    for row in rows:
        if not _is_closed(row):
            continue
        end = row.get("date_end")
        if not isinstance(end, date) or end.year != fecha_corte.year:
            continue
        horas[end.month - 1] += _effective_hours(row) if "ordered_total" in row else _ordered(row)
        proyectos[end.month - 1] += 1

    def _cumulative(values: list) -> list:
        total = 0
        result = []
        for index, value in enumerate(values):
            if index + 1 <= fecha_corte.month:
                total += value
                result.append(total)
            else:
                result.append(None)
        return result

    return {"horas": _cumulative(horas), "proyectos": _cumulative(proyectos)}


def comparar_cortes(old_rows: list[dict], new_rows: list[dict]) -> dict:
    """Entradas/salidas entre dos AllOrders, cuadradas con las horas totales.

    Se trabaja sobre el mismo universo que el grafico de horas totales
    (proyectos en Normal, primera fila de cada codigo), de modo que
    entradas - salidas = horas totales nuevas - horas totales anteriores:

    - Entradas: proyectos que pasan a estar en Normal (nuevos o reactivados),
      con sus horas actuales, + cambios de horas de los que siguen en Normal.
    - Salidas: proyectos que dejan de estar en Normal (cerrados, desaparecidos
      del AllOrders u otro estado), con las horas que tenian en el corte anterior.
    """
    old_all = {_clean(r.get("project_code")): r for r in _unique_by_code(old_rows)}
    new_all = {_clean(r.get("project_code")): r for r in _unique_by_code(new_rows)}
    old_normal = {code: r for code, r in old_all.items() if _is_normal(r)}
    new_normal = {code: r for code, r in new_all.items() if _is_normal(r)}

    def _item(row: dict, hours: float, motivo: str) -> dict:
        return {
            "code": _clean(row.get("project_code")),
            "client": _clean(row.get("client")),
            "project_name": _clean(row.get("project_name")),
            "team": _clean(row.get("team")),
            "hours": hours,
            "motivo": motivo,
        }

    cambios = []
    nuevos = []
    cerrados = []
    for code, new in new_normal.items():
        new_hours = _ordered(new)
        old = old_normal.get(code)
        if old is None:
            previous = old_all.get(code)
            motivo = "Nuevo" if previous is None else f"Vuelve a Normal (antes {_clean(previous.get('internal_status')) or 'sin estado'})"
            nuevos.append(_item(new, new_hours, motivo))
            continue
        old_hours = _ordered(old)
        if round(old_hours, 6) != round(new_hours, 6):
            cambios.append({**_item(new, new_hours - old_hours, "Cambio de horas"),
                            "old_hours": old_hours, "new_hours": new_hours})
    for code, old in old_normal.items():
        if code in new_normal:
            continue
        current = new_all.get(code)
        if current is None:
            motivo = "Ya no aparece en el AllOrders"
        else:
            motivo = _clean(current.get("internal_status")).capitalize() or "Sin estado"
        cerrados.append(_item(old, _ordered(old), motivo))

    def _bucket(items: list[dict]) -> dict:
        """Tramos tal y como se presentan en la diapositiva: <100 / 100-400 / >400."""
        result = {"s": [], "m": [], "l": []}
        for item in sorted(items, key=lambda i: -i["hours"]):
            if item["hours"] > 400:
                result["l"].append(item)
            elif item["hours"] >= 100:
                result["m"].append(item)
            else:
                result["s"].append(item)
        return result

    cambios_horas = sum(item["hours"] for item in cambios)
    nuevos_tramos = _bucket(nuevos)
    salidas_tramos = _bucket(cerrados)
    return {
        "entradas": {
            "total_horas": cambios_horas + sum(item["hours"] for item in nuevos),
            "cambios_horas": cambios_horas,
            "cambios": cambios,
            "tramos": nuevos_tramos,
        },
        "salidas": {
            "total_horas": sum(item["hours"] for item in cerrados),
            "tramos": salidas_tramos,
        },
    }


# ------------------------------------
# Lectura de datos
# ------------------------------------

AO_COLUMNS = (
    "project_code", "project_name", "client", "team", "project_type", "internal_status",
    "order_phase", "date_design", "date_end", "ordered_n", "ordered_e",
    "status_pct", "payment_total", "payment_inv",
)


def fetch_all_orders_rows(cur: psycopg.Cursor, import_id: int, equipos: list[str], tipos: list[str]) -> list[dict]:
    cur.execute(
        f"""
        SELECT {", ".join(AO_COLUMNS)}
        FROM all_orders_snapshot
        WHERE import_file_id = %s
          AND LOWER(BTRIM(COALESCE(project_type, ''))) = ANY(%s)
          AND BTRIM(COALESCE(team, '')) = ANY(%s)
        ORDER BY id
        """,
        (import_id, [t.strip().lower() for t in tipos], [e.strip() for e in equipos]),
    )
    return [dict(zip(AO_COLUMNS, row)) for row in cur.fetchall()]


def fetch_real_hours(cur: psycopg.Cursor, ots_import_id: int | None) -> dict[str, float]:
    """Horas reales (columna Real del OTS) por codigo para la semana de esa importacion."""
    if not ots_import_id:
        return {}
    cur.execute(
        """
        SELECT UPPER(BTRIM(p.project_code)), ps.real_hours
        FROM import_file f
        JOIN project_snapshot ps
          ON ps.snapshot_year = f.snapshot_year AND ps.snapshot_week = f.snapshot_week
        JOIN projects p ON p.id = ps.project_id
        WHERE f.id = %s AND ps.real_hours IS NOT NULL
        """,
        (ots_import_id,),
    )
    return {code: _num(hours) for code, hours in cur.fetchall()}


def fetch_import_options(cur: psycopg.Cursor) -> dict:
    """Importaciones disponibles para crear cortes: AllOrders (con filas en
    all_orders_snapshot) y OTS (resto, salvo AllOrders sin filas), mas recientes primero."""
    cur.execute(
        """
        SELECT f.id, f.filename, f.snapshot_year, f.snapshot_week,
               (SELECT COUNT(*) FROM all_orders_snapshot a WHERE a.import_file_id = f.id) AS ao_rows,
               (SELECT COUNT(*) FROM all_orders_snapshot a WHERE a.import_file_id = f.id AND a.status_pct IS NOT NULL) AS ao_progress
        FROM import_file f
        ORDER BY f.snapshot_year DESC, f.snapshot_week DESC, f.id DESC
        """
    )
    all_orders, ots = [], []
    for import_id, filename, year, week, ao_rows, ao_progress in cur.fetchall():
        item = {"id": import_id, "filename": filename, "year": year, "week": week}
        if ao_rows:
            all_orders.append({**item, "rows": ao_rows, "has_progress": ao_progress > 0})
        elif "order" not in (filename or "").lower():
            ots.append(item)
    return {"all_orders": all_orders, "ots": ots}


def fetch_filter_options(cur: psycopg.Cursor, import_id: int) -> dict:
    """Equipos y tipos de proyecto que trae un AllOrders, para elegir el filtro."""
    result = {}
    for key, column in (("equipos", "team"), ("tipos", "project_type")):
        cur.execute(
            f"""
            SELECT DISTINCT BTRIM({column})
            FROM all_orders_snapshot
            WHERE import_file_id = %s AND NULLIF(BTRIM({column}), '') IS NOT NULL
            ORDER BY 1
            """,
            (import_id,),
        )
        result[key] = [row[0] for row in cur.fetchall()]
    return result


# ------------------------------------
# Cortes
# ------------------------------------

CORTE_COLUMNS = (
    "id", "fecha_corte", "tipo", "origen", "all_orders_import_id", "ots_import_id",
    "equipos", "tipos_proyecto", "metricas",
)


def list_cortes(cur: psycopg.Cursor, tipo: str | None = None) -> list[dict]:
    sql = f"SELECT {', '.join(CORTE_COLUMNS)} FROM informe_cortes"
    params: tuple = ()
    if tipo:
        sql += " WHERE tipo = %s"
        params = (tipo,)
    cur.execute(sql + " ORDER BY fecha_corte, id", params)
    return [dict(zip(CORTE_COLUMNS, row)) for row in cur.fetchall()]


def get_corte(cur: psycopg.Cursor, corte_id: int) -> dict | None:
    cur.execute(f"SELECT {', '.join(CORTE_COLUMNS)} FROM informe_cortes WHERE id = %s", (corte_id,))
    row = cur.fetchone()
    return dict(zip(CORTE_COLUMNS, row)) if row else None


def corte_anterior_direccion(cur: psycopg.Cursor, corte: dict) -> dict | None:
    """Ultimo corte DIRECCION anterior al dado (los INTERNO no cuentan)."""
    cur.execute(
        f"""
        SELECT {', '.join(CORTE_COLUMNS)} FROM informe_cortes
        WHERE tipo = 'DIRECCION' AND id <> %s
          AND (fecha_corte < %s OR (fecha_corte = %s AND id < %s))
        ORDER BY fecha_corte DESC, id DESC
        LIMIT 1
        """,
        (corte["id"], corte["fecha_corte"], corte["fecha_corte"], corte["id"]),
    )
    row = cur.fetchone()
    return dict(zip(CORTE_COLUMNS, row)) if row else None


def calcular_corte(
    cur: psycopg.Cursor,
    fecha_corte: date,
    all_orders_import_id: int,
    ots_import_id: int | None,
    equipos: list[str],
    tipos: list[str],
) -> dict:
    rows = fetch_all_orders_rows(cur, all_orders_import_id, equipos, tipos)
    metricas = calcular_metricas(rows, fetch_real_hours(cur, ots_import_id), fecha_corte)
    metricas["entregas"] = calcular_entregas(fetch_closed_rows(cur, all_orders_import_id, equipos, tipos), fecha_corte)
    metricas["filas"] = len(rows)
    return metricas


def fetch_closed_rows(cur: psycopg.Cursor, import_id: int, equipos: list[str], tipos: list[str]) -> list[dict]:
    """Filas del AllOrders para las entregas, con la misma logica que el informe
    de Cierre de proyectos: horas congeladas al cierre (o las aceptadas al
    revisar), correcciones manuales y proyectos cerrados que ya no aparecen en
    el AllOrders (salvo que se hayan excluido al revisarlos).

    Las revisiones y correcciones son las vigentes hoy, no las del dia del corte."""
    cur.execute("SELECT snapshot_year, snapshot_week FROM import_file WHERE id = %s", (import_id,))
    snapshot_year, snapshot_week = cur.fetchone()
    frozen = frozen_hours_map(fetch_closed_hours_tracking(cur))
    vanished_rows = build_vanished_rows(fetch_vanished_closures(cur), snapshot_year)
    extra = _select_vanished_rows(vanished_rows, snapshot_year, snapshot_week)
    equipos_set = {e.strip() for e in equipos}
    tipos_set = {t.strip().lower() for t in tipos}
    rows = []
    for row in fetch_all_orders_rows_for_batch(cur, import_id, frozen, extra):
        if (row.get("team") or "").strip() not in equipos_set:
            continue
        # Las filas de proyectos desaparecidos no traen tipo; ya vienen filtradas por tipo OTS.
        if row.get("project_type") is not None and row["project_type"].strip().lower() not in tipos_set:
            continue
        rows.append(row)
    return rows


def crear_corte(
    cur: psycopg.Cursor,
    fecha_corte: date,
    tipo: str,
    all_orders_import_id: int,
    ots_import_id: int | None,
    equipos: list[str],
    tipos: list[str],
) -> int:
    metricas = calcular_corte(cur, fecha_corte, all_orders_import_id, ots_import_id, equipos, tipos)
    cur.execute(
        """
        INSERT INTO informe_cortes (fecha_corte, tipo, origen, all_orders_import_id, ots_import_id,
                                    equipos, tipos_proyecto, metricas)
        VALUES (%s, %s, 'APP', %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (fecha_corte, tipo, all_orders_import_id, ots_import_id,
         json.dumps(equipos), json.dumps(tipos), json.dumps(metricas)),
    )
    return cur.fetchone()[0]


def recalcular_corte(cur: psycopg.Cursor, corte: dict) -> None:
    if not corte.get("all_orders_import_id"):
        raise ValueError("El corte no tiene importacion AllOrders asociada; no se puede recalcular.")
    metricas = calcular_corte(
        cur, corte["fecha_corte"], corte["all_orders_import_id"], corte.get("ots_import_id"),
        corte["equipos"] or DEFAULT_TEAMS, corte["tipos_proyecto"] or DEFAULT_PROJECT_TYPES,
    )
    cur.execute(
        "UPDATE informe_cortes SET metricas = %s, origen = 'APP', updated_at = now() WHERE id = %s",
        (json.dumps(metricas), corte["id"]),
    )


def datos_presentacion(cur: psycopg.Cursor, corte: dict) -> dict:
    """Todo lo necesario para generar el informe de un corte.

    El historico de graficos usa solo cortes DIRECCION hasta este (incluido;
    si el propio corte es INTERNO se anade al final para poder revisarlo).
    El delta de entradas/salidas se calcula contra el ultimo DIRECCION anterior.
    """
    historico = [c for c in list_cortes(cur, TIPO_DIRECCION)
                 if (c["fecha_corte"], c["id"]) <= (corte["fecha_corte"], corte["id"])]
    if corte["tipo"] != TIPO_DIRECCION:
        historico.append(corte)

    anterior = corte_anterior_direccion(cur, corte)
    delta = None
    aviso_delta = None
    if anterior is None:
        aviso_delta = "No hay un corte de direccion anterior con el que comparar."
    elif not anterior.get("all_orders_import_id") or not corte.get("all_orders_import_id"):
        aviso_delta = (f"El corte del {anterior['fecha_corte']:%d/%m/%Y} o este no tienen AllOrders asociado; "
                       "no se pueden calcular entradas/salidas.")
    else:
        equipos = corte["equipos"] or DEFAULT_TEAMS
        tipos = corte["tipos_proyecto"] or DEFAULT_PROJECT_TYPES
        delta = comparar_cortes(
            fetch_all_orders_rows(cur, anterior["all_orders_import_id"], equipos, tipos),
            fetch_all_orders_rows(cur, corte["all_orders_import_id"], equipos, tipos),
        )
        # Cuadre con la diapositiva de horas: el neto debe coincidir con la
        # variacion de horas totales guardada en los dos cortes (redondeadas).
        neto = delta["entradas"]["total_horas"] - delta["salidas"]["total_horas"]
        variacion = (corte["metricas"].get("horas") or {}).get("totales", 0) - \
            (anterior["metricas"].get("horas") or {}).get("totales", 0)
        delta["cuadre"] = {"neto": neto, "variacion_totales": variacion, "diferencia": variacion - neto}

    return {
        "corte": corte,
        "historico": historico,
        "anterior": anterior,
        "delta": delta,
        "aviso_delta": aviso_delta,
        "entregas_anterior": get_entregas_anio(cur, corte["fecha_corte"].year - 1),
    }


def get_entregas_anio(cur: psycopg.Cursor, year: int) -> dict | None:
    cur.execute("SELECT value FROM app_settings WHERE key = %s", (f"{SETTING_ENTREGAS_PREFIX}{year}",))
    row = cur.fetchone()
    return json.loads(row[0]) if row and row[0] else None


def set_entregas_anio(cur: psycopg.Cursor, year: int, horas: list, proyectos: list) -> None:
    cur.execute(
        """
        INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, now())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """,
        (f"{SETTING_ENTREGAS_PREFIX}{year}", json.dumps({"horas": horas, "proyectos": proyectos})),
    )
