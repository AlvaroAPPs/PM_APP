"""Tablas de objetivos por hito (diapositivas 12-16) y hitos retrasados (17-18)
del informe de direccion.

Reglas (acordadas con jefatura de proyectos):

- Columnas: mes anterior, mes actual y mes siguiente a la fecha del corte.
- Un proyecto esta en la columna del mes en que cae la fecha del hito en el
  AllOrders del corte (se recalcula en cada informe). Solo Normal y Closed.
- Tramos por horas del pedido: <100 h, entre 100 y 400 h, >400 h.
- Conseguido (azul): el hito tiene su OK marcado.
- Replanificado respecto al corte DIRECCION anterior (la fecha del hito se ha
  ido a un mes posterior, o ha desaparecido): el proyecto se queda tambien en
  su columna antigua marcado en NARANJA si se ha movido al mes siguiente, o en
  ROJO si se ha movido mas de un mes, se ha quedado sin fecha o se ha parado.
  Solo la PRIMERA vez que se replanifica ese hito; si ya se replanifico en un
  informe anterior, simplemente aparece en su nueva columna sin marcar.
- Meses ya pasados: lo que no esta conseguido sale en rojo (retrasado).
- Hitos retrasados: los proyectos de 100 h o mas marcados en naranja o rojo,
  con un motivo que se escribe en la app (con el ultimo comentario como pista).
"""

from __future__ import annotations

import json
from datetime import date

import psycopg

from reports.informe_direccion import DEFAULT_PROJECT_TYPES, DEFAULT_TEAMS, list_cortes

HITOS = (
    # clave, columna de fecha, columna OK, titulo
    ("K", "date_kickoff", "kickoff_ok", "Kick-off"),
    ("D", "date_design", "design_ok", "Diseño"),
    ("V", "date_validation", "validation_ok", "Validación"),
    ("G", "date_golive", "golive_ok", "Go-live"),
    ("E", "date_end", "end_ok", "End"),
)
HITO_TITULOS = {key: title for key, _d, _o, title in HITOS}

ESTADO_OK = "ok"
ESTADO_PENDIENTE = "pendiente"
ESTADO_NARANJA = "naranja"
ESTADO_ROJO = "rojo"

TRAMOS = ("s", "m", "l")
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
         "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]

ROW_COLUMNS = (
    "project_code", "project_name", "client", "team", "project_type", "internal_status", "order_phase",
    "ordered_n", "ordered_e", "comments",
    "date_kickoff", "date_design", "date_validation", "date_golive", "date_end",
    "kickoff_ok", "design_ok", "validation_ok", "golive_ok", "end_ok",
)


# ------------------------------------
# Almacenamiento: nombres cortos y motivos de retraso
# ------------------------------------

def ensure_objetivos_storage(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS informe_nombres (
            project_code TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS informe_motivos (
            corte_id BIGINT NOT NULL REFERENCES informe_cortes(id) ON DELETE CASCADE,
            project_code TEXT NOT NULL,
            hito TEXT NOT NULL,
            motivo TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (corte_id, project_code, hito)
        );
        """
    )


def fetch_nombres(cur: psycopg.Cursor) -> dict[str, str]:
    cur.execute("SELECT project_code, nombre FROM informe_nombres")
    return dict(cur.fetchall())


def set_nombre(cur: psycopg.Cursor, project_code: str, nombre: str) -> None:
    nombre = (nombre or "").strip()
    if not nombre:
        cur.execute("DELETE FROM informe_nombres WHERE project_code = %s", (project_code,))
        return
    cur.execute(
        """
        INSERT INTO informe_nombres (project_code, nombre, updated_at) VALUES (%s, %s, now())
        ON CONFLICT (project_code) DO UPDATE SET nombre = EXCLUDED.nombre, updated_at = now()
        """,
        (project_code, nombre),
    )


def fetch_motivos(cur: psycopg.Cursor, corte: dict) -> dict[tuple[str, str], dict]:
    """Motivos del corte; si un proyecto+hito no tiene, se propone el ultimo
    que se escribio para ese mismo proyecto+hito en un corte anterior."""
    cur.execute(
        """
        SELECT DISTINCT ON (m.project_code, m.hito) m.project_code, m.hito, m.motivo, m.corte_id
        FROM informe_motivos m
        JOIN informe_cortes c ON c.id = m.corte_id
        WHERE c.fecha_corte <= %s AND BTRIM(m.motivo) <> ''
        ORDER BY m.project_code, m.hito, (m.corte_id = %s) DESC, c.fecha_corte DESC, m.corte_id DESC
        """,
        (corte["fecha_corte"], corte["id"]),
    )
    return {
        (code, hito): {"motivo": motivo, "heredado": corte_id != corte["id"]}
        for code, hito, motivo, corte_id in cur.fetchall()
    }


def set_motivo(cur: psycopg.Cursor, corte_id: int, project_code: str, hito: str, motivo: str) -> None:
    cur.execute(
        """
        INSERT INTO informe_motivos (corte_id, project_code, hito, motivo, updated_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (corte_id, project_code, hito) DO UPDATE SET motivo = EXCLUDED.motivo, updated_at = now()
        """,
        (corte_id, project_code, hito, (motivo or "").strip()),
    )


# ------------------------------------
# Calculo
# ------------------------------------

def _month(value) -> tuple[int, int] | None:
    return (value.year, value.month) if isinstance(value, date) else None


def _add_months(ym: tuple[int, int], delta: int) -> tuple[int, int]:
    index = ym[0] * 12 + (ym[1] - 1) + delta
    return index // 12, index % 12 + 1


def _hours(row: dict) -> float:
    total = 0.0
    for key in ("ordered_n", "ordered_e"):
        try:
            total += float(row.get(key) or 0)
        except (TypeError, ValueError):
            pass
    return total


def _tramo(hours: float) -> str:
    if hours < 100:
        return "s"
    if hours <= 400:
        return "m"
    return "l"


def _status(row: dict) -> str:
    return (row.get("internal_status") or "").strip().lower()


def _stopped(row: dict | None) -> bool:
    return bool(row) and (row.get("order_phase") or "").strip().upper() == "STOPPED"


def _is_later(new: tuple[int, int] | None, old: tuple[int, int]) -> bool:
    """La fecha del hito se ha ido a un mes posterior o se ha quedado sin fecha."""
    return new is None or new > old


def fetch_rows(cur: psycopg.Cursor, import_id: int, equipos: list[str], tipos: list[str]) -> dict[str, dict]:
    """Filas Normal/Closed de un AllOrders por codigo (primera fila de cada codigo)."""
    cur.execute(
        f"""
        SELECT {", ".join(ROW_COLUMNS)}
        FROM all_orders_snapshot
        WHERE import_file_id = %s
          AND LOWER(BTRIM(COALESCE(project_type, ''))) = ANY(%s)
          AND BTRIM(COALESCE(team, '')) = ANY(%s)
          AND LOWER(BTRIM(COALESCE(internal_status, ''))) IN ('normal', 'closed')
        ORDER BY id
        """,
        (import_id, [t.strip().lower() for t in tipos], [e.strip() for e in equipos]),
    )
    rows: dict[str, dict] = {}
    for values in cur.fetchall():
        row = dict(zip(ROW_COLUMNS, values))
        rows.setdefault((row["project_code"] or "").strip(), row)
    return rows


def replanificados_previos(history: list[dict[str, dict]]) -> set[tuple[str, str]]:
    """(codigo, hito) que ya se marcaron como replanificados en algun informe
    anterior: entre dos cortes DIRECCION consecutivos la fecha se fue a un mes
    posterior (o se quedo sin fecha)."""
    seen: set[tuple[str, str]] = set()
    for older, newer in zip(history, history[1:]):
        for code, old in older.items():
            new = newer.get(code)
            for key, date_col, _ok, _title in HITOS:
                old_month = _month(old.get(date_col))
                if old_month is None:
                    continue
                new_month = _month(new.get(date_col)) if new else None
                if new is not None and _is_later(new_month, old_month):
                    seen.add((code, key))
    return seen


def calcular_objetivos(
    fecha_corte: date,
    actual: dict[str, dict],
    anterior: dict[str, dict] | None,
    ya_replanificados: set[tuple[str, str]],
    nombres: dict[str, str],
) -> dict:
    """Tablas por hito: {hito: {"meses": [...], "celdas": {(ym, tramo): [entradas]}}}.

    Cada entrada: code, nombre, horas, estado, nuevo_mes (si se replanifico), comentario."""
    current = (fecha_corte.year, fecha_corte.month)
    meses = [_add_months(current, -1), current, _add_months(current, 1)]
    resultado = {}

    for key, date_col, ok_col, title in HITOS:
        celdas: dict[tuple, list[dict]] = {(ym, t): [] for ym in meses for t in TRAMOS}

        def _entrada(code: str, row: dict, estado: str, nuevo_mes=None) -> dict:
            return {
                "code": code,
                "nombre": nombres.get(code) or (row.get("project_name") or code).strip(),
                "horas": _hours(row),
                "estado": estado,
                "nuevo_mes": nuevo_mes,
                "comentario": (row.get("comments") or "").strip(),
            }

        for code, row in actual.items():
            month = _month(row.get(date_col))
            tramo = _tramo(_hours(row))
            previous = anterior.get(code) if anterior is not None else None
            old_month = _month(previous.get(date_col)) if previous else None

            replanned = (
                previous is not None
                and old_month in meses
                and old_month != month
                and _is_later(month, old_month)
                and (code, key) not in ya_replanificados
                and not row.get(ok_col)
            )
            stopped_now = _stopped(row) and not _stopped(previous) and not row.get(ok_col)

            if replanned:
                if month is not None and month == _add_months(old_month, 1) and not _stopped(row):
                    estado = ESTADO_NARANJA
                else:
                    estado = ESTADO_ROJO
                celdas[(old_month, tramo)].append(_entrada(code, row, estado, month))

            if month in meses:
                if row.get(ok_col):
                    estado = ESTADO_OK
                elif (stopped_now and month == old_month) or month < current:
                    estado = ESTADO_ROJO
                else:
                    estado = ESTADO_PENDIENTE
                celdas[(month, tramo)].append(_entrada(code, row, estado))

        for entries in celdas.values():
            entries.sort(key=lambda e: e["nombre"].upper())
        resultado[key] = {"titulo": title, "meses": meses, "celdas": celdas}
    return resultado


def retrasados(objetivos: dict, motivos: dict[tuple[str, str], dict]) -> dict[str, list[dict]]:
    """Proyectos de 100 h o mas marcados en naranja o rojo, por hito."""
    result: dict[str, list[dict]] = {}
    for key, tabla in objetivos.items():
        vistos: set[str] = set()
        items = []
        for (_ym, tramo), entries in tabla["celdas"].items():
            if tramo == "s":
                continue
            for entry in entries:
                if entry["estado"] not in (ESTADO_NARANJA, ESTADO_ROJO) or entry["code"] in vistos:
                    continue
                vistos.add(entry["code"])
                motivo = motivos.get((entry["code"], key)) or {}
                items.append({**entry, "hito": key, "motivo": motivo.get("motivo", ""),
                              "motivo_heredado": motivo.get("heredado", False)})
        items.sort(key=lambda e: e["nombre"].upper())
        if items:
            result[key] = items
    return result


def datos_objetivos(cur: psycopg.Cursor, corte: dict) -> dict:
    """Tablas de objetivos y retrasados de un corte, comparando con los cortes
    DIRECCION anteriores (los INTERNO no cuentan)."""
    ensure_objetivos_storage(cur)
    if not corte.get("all_orders_import_id"):
        return {"aviso": "El corte no tiene AllOrders asociado.", "objetivos": {}, "retrasados": {}}

    equipos = corte["equipos"] or DEFAULT_TEAMS
    tipos = corte["tipos_proyecto"] or DEFAULT_PROJECT_TYPES
    anteriores = [
        c for c in list_cortes(cur, "DIRECCION")
        if (c["fecha_corte"], c["id"]) < (corte["fecha_corte"], corte["id"]) and c.get("all_orders_import_id")
    ]
    history = [fetch_rows(cur, c["all_orders_import_id"], equipos, tipos) for c in anteriores]
    actual = fetch_rows(cur, corte["all_orders_import_id"], equipos, tipos)
    anterior = history[-1] if history else None

    cur.execute(
        "SELECT COUNT(*) FROM all_orders_snapshot WHERE import_file_id = %s AND kickoff_ok IS NOT NULL",
        (corte["all_orders_import_id"],),
    )
    sin_ok = cur.fetchone()[0] == 0
    objetivos = calcular_objetivos(corte["fecha_corte"], actual, anterior, replanificados_previos(history),
                                   fetch_nombres(cur))
    avisos = []
    if sin_ok:
        avisos.append("Este AllOrders se importó sin los OK de los hitos: vuelve a importarlo para ver los conseguidos.")
    if anterior is None:
        avisos.append("No hay corte de dirección anterior con AllOrders: no se pueden marcar replanificaciones.")
    return {
        "aviso": " ".join(avisos) or None,
        "anterior": anteriores[-1]["fecha_corte"] if anteriores else None,
        "objetivos": objetivos,
        "retrasados": retrasados(objetivos, fetch_motivos(cur, corte)),
    }


def mes_titulo(ym: tuple[int, int]) -> str:
    return MESES[ym[1] - 1]


def serializar(datos: dict) -> dict:
    """Version JSON de datos_objetivos para la pantalla."""
    objetivos = {}
    for key, tabla in datos["objetivos"].items():
        objetivos[key] = {
            "titulo": tabla["titulo"],
            "meses": [mes_titulo(ym) for ym in tabla["meses"]],
            "celdas": {
                f"{ym[0]}-{ym[1]:02d}|{tramo}": [
                    {**e, "nuevo_mes": mes_titulo(e["nuevo_mes"]) if e["nuevo_mes"] else None} for e in entries
                ]
                for (ym, tramo), entries in tabla["celdas"].items()
            },
            "claves_meses": [f"{ym[0]}-{ym[1]:02d}" for ym in tabla["meses"]],
        }
    return json.loads(json.dumps({
        "aviso": datos.get("aviso"),
        "anterior": datos.get("anterior"),
        "objetivos": objetivos,
        "retrasados": {
            key: [{**e, "nuevo_mes": mes_titulo(e["nuevo_mes"]) if e["nuevo_mes"] else None} for e in items]
            for key, items in datos["retrasados"].items()
        },
        "titulos": HITO_TITULOS,
    }, default=str))
