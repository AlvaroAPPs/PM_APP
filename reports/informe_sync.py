"""Exportar / importar el informe de direccion entre bases de datos de distintas personas.

Cada persona tiene su propia base de datos (con los mismos AllOrders y OTS
cargados) y los informes se van alternando. El fichero de exportacion lleva:

- los ultimos cortes DIRECCION, autosuficientes: cifras congeladas, detalle de
  proyectos, motivos de retraso y el nombre de las importaciones de origen;
- los nombres cortos de proyecto y las entregas del ano anterior;
- las decisiones de revision de horas cerradas (correcciones manuales, horas
  aceptadas/descartadas y cerrados desaparecidos), con quien las ha validado.

Al importar solo se anaden los cortes cuya fecha no exista ya como corte
DIRECCION. Las decisiones siguen una doble validacion:

- Una decision esta CONFIRMADA cuando la han validado dos personas distintas.
- Si no hay decision local, se anade la del fichero.
- Si coinciden, se suman las validaciones (y puede quedar confirmada).
- Si difieren: una confirmada pisa a una que no lo esta, y entre dos
  confirmadas gana la mas reciente. Si ninguna esta confirmada se crea un
  CONFLICTO pendiente; mientras tanto se usa el valor local. Al resolverlo, la
  eleccion cuenta como validacion de quien resuelve.

La "firma" de cada persona es el nombre de PM configurado en la app.
"""

from __future__ import annotations

import gzip
import json
import unicodedata
from datetime import date, datetime, timezone

import psycopg

from reports.informe_direccion import (
    SETTING_ENTREGAS_PREFIX,
    TIPO_DIRECCION,
    detalle_json,
    completar_detalles,
    ensure_informe_storage,
    guardar_detalle,
    list_cortes,
)
from reports.informe_objetivos import HISTORICO_CORTES, ensure_objetivos_storage
from reports.project_closures import ensure_closed_hours_review_storage

FORMATO = "informe-direccion"
VERSION = 1
CORTES_EXPORTADOS = HISTORICO_CORTES

APP_SETTING_PM_NAME = "pm_name"

TIPO_OVERRIDE = "override"
TIPO_REVISION = "revision"
TIPO_DESAPARECIDO = "desaparecido"
TIPO_TITULOS = {
    TIPO_OVERRIDE: "Corrección manual de horas",
    TIPO_REVISION: "Revisión de horas cambiadas",
    TIPO_DESAPARECIDO: "Cerrado desaparecido",
}
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ------------------------------------
# Almacenamiento
# ------------------------------------

def ensure_sync_storage(cur: psycopg.Cursor) -> None:
    ensure_informe_storage(cur)
    ensure_objetivos_storage(cur)
    ensure_closed_hours_review_storage(cur)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_validaciones (
            tipo TEXT NOT NULL,
            project_code TEXT NOT NULL,
            valor JSONB NOT NULL,
            validado_por JSONB NOT NULL DEFAULT '[]'::jsonb,
            decidido_at TIMESTAMPTZ,
            PRIMARY KEY (tipo, project_code)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_conflictos (
            tipo TEXT NOT NULL,
            project_code TEXT NOT NULL,
            valor_remoto JSONB NOT NULL,
            remoto_por JSONB NOT NULL DEFAULT '[]'::jsonb,
            remoto_at TIMESTAMPTZ,
            detectado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tipo, project_code)
        );
        """
    )


def mi_nombre(cur: psycopg.Cursor) -> str | None:
    """Nombre de PM guardado en Configuracion (sin el valor por defecto de la app)."""
    cur.execute("SELECT value FROM app_settings WHERE key = %s", (APP_SETTING_PM_NAME,))
    row = cur.fetchone()
    name = (row[0] or "").strip() if row else ""
    return name or None


# ------------------------------------
# Decisiones de horas: valor actual en las tablas de la app
# ------------------------------------

def _round(value) -> float | None:
    return None if value is None else round(float(value), 3)


def decisiones_actuales(cur: psycopg.Cursor) -> dict[tuple[str, str], dict]:
    """(tipo, codigo) -> {"valor": ..., "at": fecha de la decision si se sabe}."""
    result: dict[tuple[str, str], dict] = {}
    cur.execute("SELECT project_code, closed_hours_override FROM projects_historical WHERE closed_hours_override IS NOT NULL")
    for code, hours in cur.fetchall():
        result[(TIPO_OVERRIDE, code)] = {"valor": {"horas": _round(hours)}, "at": None}
    cur.execute("SELECT project_code, accepted_hours, dismissed_source_hours, updated_at FROM closed_hours_review")
    for code, accepted, dismissed, updated_at in cur.fetchall():
        result[(TIPO_REVISION, code)] = {
            "valor": {"aceptadas": _round(accepted), "descartadas": _round(dismissed)}, "at": updated_at}
    cur.execute("SELECT project_code, action, updated_at FROM vanished_closure_review")
    for code, action, updated_at in cur.fetchall():
        result[(TIPO_DESAPARECIDO, code)] = {"valor": {"accion": action}, "at": updated_at}
    return result


def _vacio(tipo: str) -> dict:
    return {TIPO_OVERRIDE: {"horas": None},
            TIPO_REVISION: {"aceptadas": None, "descartadas": None},
            TIPO_DESAPARECIDO: {"accion": None}}[tipo]


def aplicar_valor(cur: psycopg.Cursor, tipo: str, code: str, valor: dict) -> bool:
    """Escribe el valor en las tablas de la app. False si no se puede (p. ej. el
    proyecto no esta en historicos de esta base de datos)."""
    if tipo == TIPO_OVERRIDE:
        cur.execute("UPDATE projects_historical SET closed_hours_override = %s WHERE project_code = %s RETURNING id",
                    (valor.get("horas"), code))
        return cur.fetchone() is not None
    if tipo == TIPO_REVISION:
        if valor.get("aceptadas") is None and valor.get("descartadas") is None:
            cur.execute("DELETE FROM closed_hours_review WHERE project_code = %s", (code,))
        else:
            cur.execute(
                """
                INSERT INTO closed_hours_review (project_code, accepted_hours, dismissed_source_hours, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (project_code) DO UPDATE
                SET accepted_hours = EXCLUDED.accepted_hours,
                    dismissed_source_hours = EXCLUDED.dismissed_source_hours, updated_at = now()
                """,
                (code, valor.get("aceptadas"), valor.get("descartadas")),
            )
        return True
    if tipo == TIPO_DESAPARECIDO:
        if valor.get("accion") is None:
            cur.execute("DELETE FROM vanished_closure_review WHERE project_code = %s", (code,))
        else:
            cur.execute(
                """
                INSERT INTO vanished_closure_review (project_code, action, updated_at) VALUES (%s, %s, now())
                ON CONFLICT (project_code) DO UPDATE SET action = EXCLUDED.action, updated_at = now()
                """,
                (code, valor["accion"]),
            )
        return True
    raise ValueError(f"tipo de decision desconocido: {tipo}")


# ------------------------------------
# Registro de validaciones
# ------------------------------------

def _registro(cur: psycopg.Cursor) -> dict[tuple[str, str], dict]:
    cur.execute("SELECT tipo, project_code, valor, validado_por, decidido_at FROM decision_validaciones")
    return {(t, c): {"valor": v, "validado_por": list(p or []), "at": at} for t, c, v, p, at in cur.fetchall()}


def _guardar_registro(cur: psycopg.Cursor, tipo: str, code: str, valor: dict, validadores: list[str], at) -> None:
    cur.execute(
        """
        INSERT INTO decision_validaciones (tipo, project_code, valor, validado_por, decidido_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (tipo, project_code) DO UPDATE
        SET valor = EXCLUDED.valor, validado_por = EXCLUDED.validado_por, decidido_at = EXCLUDED.decidido_at
        """,
        (tipo, code, json.dumps(valor), json.dumps(sorted(set(validadores))), at),
    )


def sincronizar_registro(cur: psycopg.Cursor, yo: str) -> None:
    """Pone al dia el registro con lo que hay ahora en las tablas de la app.
    Una decision nueva o cambiada localmente queda validada solo por `yo`, y
    resuelve (borra) cualquier conflicto pendiente de ese proyecto."""
    actuales = decisiones_actuales(cur)
    registro = _registro(cur)
    primera_vez = not registro
    now = datetime.now(timezone.utc)
    for key in set(actuales) | set(registro):
        tipo, code = key
        actual = actuales.get(key)
        valor = actual["valor"] if actual else _vacio(tipo)
        reg = registro.get(key)
        if reg is not None and reg["valor"] == valor:
            continue
        if reg is None and actual is None:
            continue
        at = (actual or {}).get("at") or now
        if primera_vez and tipo == TIPO_OVERRIDE:
            at = None  # correccion anterior a este registro, sin fecha: cuenta como la mas antigua
        _guardar_registro(cur, tipo, code, valor, [yo], at)
        cur.execute("DELETE FROM decision_conflictos WHERE tipo = %s AND project_code = %s", (tipo, code))


def _confirmada(validadores: list[str]) -> bool:
    return len(set(validadores)) >= 2


def _ts(value) -> datetime:
    if value is None:
        return EPOCH
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def importar_decision(cur: psycopg.Cursor, yo: str, remota: dict, registro: dict) -> tuple[str, str]:
    """Aplica una decision del fichero segun la doble validacion. Devuelve (resultado, detalle)."""
    tipo, code = remota["tipo"], remota["project_code"]
    valor_r, por_r, at_r = remota["valor"], list(remota.get("validado_por") or []), remota.get("decidido_at")
    local = registro.get((tipo, code))

    if local is None:
        if not aplicar_valor(cur, tipo, code, valor_r):
            return "omitida", "el proyecto no está en tus históricos"
        _guardar_registro(cur, tipo, code, valor_r, por_r, _ts(at_r))
        return "anadida", ""

    if local["valor"] == valor_r:
        juntos = sorted(set(local["validado_por"]) | set(por_r))
        if juntos == sorted(set(local["validado_por"])):
            return "igual", ""
        at = max(_ts(local["at"]), _ts(at_r))
        _guardar_registro(cur, tipo, code, valor_r, juntos, at)
        return ("confirmada" if _confirmada(juntos) else "igual"), ", ".join(juntos)

    conf_l, conf_r = _confirmada(local["validado_por"]), _confirmada(por_r)
    if conf_r and (not conf_l or _ts(at_r) > _ts(local["at"])):
        if not aplicar_valor(cur, tipo, code, valor_r):
            return "omitida", "el proyecto no está en tus históricos"
        _guardar_registro(cur, tipo, code, valor_r, por_r, _ts(at_r))
        cur.execute("DELETE FROM decision_conflictos WHERE tipo = %s AND project_code = %s", (tipo, code))
        return "sustituida", f"confirmada por {', '.join(por_r)}"
    if conf_l:
        return "mantenida", "la tuya está confirmada"

    cur.execute(
        """
        INSERT INTO decision_conflictos (tipo, project_code, valor_remoto, remoto_por, remoto_at, detectado_at)
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT (tipo, project_code) DO UPDATE
        SET valor_remoto = EXCLUDED.valor_remoto, remoto_por = EXCLUDED.remoto_por,
            remoto_at = EXCLUDED.remoto_at, detectado_at = now()
        """,
        (tipo, code, json.dumps(valor_r), json.dumps(por_r), _ts(at_r)),
    )
    return "conflicto", f"validada por {', '.join(por_r) or 'nadie'}"


def listar_conflictos(cur: psycopg.Cursor) -> list[dict]:
    cur.execute(
        """
        SELECT c.tipo, c.project_code, c.valor_remoto, c.remoto_por, c.remoto_at,
               v.valor, v.validado_por, v.decidido_at,
               COALESCE(h.project_name, '')
        FROM decision_conflictos c
        LEFT JOIN decision_validaciones v ON v.tipo = c.tipo AND v.project_code = c.project_code
        LEFT JOIN projects_historical h ON h.project_code = c.project_code
        ORDER BY c.detectado_at DESC
        """
    )
    return [
        {"tipo": tipo, "titulo": TIPO_TITULOS.get(tipo, tipo), "project_code": code, "project_name": name,
         "remoto": {"valor": vr, "validado_por": pr or [], "at": ar},
         "local": {"valor": vl, "validado_por": pl or [], "at": al}}
        for tipo, code, vr, pr, ar, vl, pl, al, name in cur.fetchall()
    ]


def contar_conflictos(cur: psycopg.Cursor) -> int:
    cur.execute("SELECT COUNT(*) FROM decision_conflictos")
    return cur.fetchone()[0]


def resolver_conflicto(cur: psycopg.Cursor, yo: str, tipo: str, code: str, accion: str) -> None:
    """accion='mia': mantengo mi valor (lo valido yo). accion='suya': acepto el
    valor del otro y lo valido yo tambien (queda confirmado)."""
    cur.execute(
        "SELECT valor_remoto, remoto_por FROM decision_conflictos WHERE tipo = %s AND project_code = %s",
        (tipo, code),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError("No hay conflicto pendiente para ese proyecto")
    valor_r, por_r = row
    now = datetime.now(timezone.utc)
    if accion == "suya":
        if not aplicar_valor(cur, tipo, code, valor_r):
            raise ValueError("El proyecto no está en tus históricos")
        _guardar_registro(cur, tipo, code, valor_r, list(por_r or []) + [yo], now)
    elif accion == "mia":
        local = _registro(cur).get((tipo, code))
        valor = local["valor"] if local else _vacio(tipo)
        _guardar_registro(cur, tipo, code, valor, [yo], now)
    else:
        raise ValueError("Accion no valida")
    cur.execute("DELETE FROM decision_conflictos WHERE tipo = %s AND project_code = %s", (tipo, code))


# ------------------------------------
# Exportar
# ------------------------------------

def _filename(cur: psycopg.Cursor, import_id: int | None) -> dict | None:
    if not import_id:
        return None
    cur.execute("SELECT filename, snapshot_year, snapshot_week FROM import_file WHERE id = %s", (import_id,))
    row = cur.fetchone()
    return {"filename": row[0], "year": row[1], "week": row[2]} if row else None


def exportar(cur: psycopg.Cursor) -> tuple[bytes, str]:
    """Fichero .json.gz con los ultimos cortes DIRECCION y las decisiones. (contenido, nombre)."""
    ensure_sync_storage(cur)
    yo = mi_nombre(cur)
    if not yo:
        raise ValueError("Configura tu nombre de PM en Configuración antes de exportar.")
    completar_detalles(cur)
    sincronizar_registro(cur, yo)

    cortes = list_cortes(cur, TIPO_DIRECCION)[-CORTES_EXPORTADOS:]
    cortes_out = []
    for corte in cortes:
        cur.execute("SELECT project_code, hito, motivo FROM informe_motivos WHERE corte_id = %s AND BTRIM(motivo) <> ''",
                    (corte["id"],))
        motivos = [{"project_code": c, "hito": h, "motivo": m} for c, h, m in cur.fetchall()]
        cortes_out.append({
            "fecha_corte": corte["fecha_corte"].isoformat(),
            "tipo": corte["tipo"],
            "origen": corte["origen"],
            "equipos": corte["equipos"],
            "tipos_proyecto": corte["tipos_proyecto"],
            "metricas": corte["metricas"],
            "all_orders": _filename(cur, corte["all_orders_import_id"]),
            "ots": _filename(cur, corte["ots_import_id"]),
            "importado_de": corte.get("importado_de"),
            "detalle": detalle_json(cur, corte["id"]),
            "motivos": motivos,
        })

    cur.execute("SELECT project_code, nombre FROM informe_nombres")
    nombres = [{"project_code": c, "nombre": n} for c, n in cur.fetchall()]
    cur.execute("SELECT key, value FROM app_settings WHERE key LIKE %s", (f"{SETTING_ENTREGAS_PREFIX}%",))
    ajustes = [{"key": k, "value": v} for k, v in cur.fetchall()]
    decisiones = [
        {"tipo": t, "project_code": c, "valor": r["valor"], "validado_por": r["validado_por"],
         "decidido_at": r["at"].isoformat() if r["at"] else None}
        for (t, c), r in _registro(cur).items()
    ]

    exported_at = datetime.now(timezone.utc)
    payload = {
        "formato": FORMATO,
        "version": VERSION,
        "exportado_por": yo,
        "exportado_at": exported_at.isoformat(),
        "cortes": cortes_out,
        "nombres": nombres,
        "ajustes": ajustes,
        "decisiones": decisiones,
    }
    blob = gzip.compress(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    ultima = cortes[-1]["fecha_corte"].isoformat() if cortes else date.today().isoformat()
    ascii_name = unicodedata.normalize("NFKD", yo).encode("ascii", "ignore").decode()
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in ascii_name).strip("_")
    return blob, f"informe_direccion_{ultima}_{safe_name}.json.gz"


# ------------------------------------
# Importar
# ------------------------------------

def leer_fichero(content: bytes) -> dict:
    try:
        data = json.loads(gzip.decompress(content) if content[:2] == b"\x1f\x8b" else content)
    except (OSError, ValueError) as exc:
        raise ValueError("El fichero no es una exportación del informe de dirección.") from exc
    if data.get("formato") != FORMATO:
        raise ValueError("El fichero no es una exportación del informe de dirección.")
    if int(data.get("version") or 0) > VERSION:
        raise ValueError("El fichero es de una versión más nueva de la app: actualízala antes de importarlo.")
    return data


def _buscar_importacion(cur: psycopg.Cursor, ref: dict | None, all_orders: bool) -> int | None:
    """Importacion local con el mismo fichero y semana (la ultima subida)."""
    if not ref or not ref.get("filename"):
        return None
    cur.execute(
        """
        SELECT f.id FROM import_file f
        WHERE f.filename = %s AND f.snapshot_year = %s AND f.snapshot_week = %s
          AND (EXISTS (SELECT 1 FROM all_orders_snapshot a WHERE a.import_file_id = f.id)) = %s
        ORDER BY f.id DESC LIMIT 1
        """,
        (ref["filename"], ref.get("year"), ref.get("week"), all_orders),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _resumen_cifras(metricas: dict) -> str:
    proyectos = (metricas.get("proyectos") or {}).get("totales")
    horas = (metricas.get("horas") or {}).get("totales")
    return f"{proyectos} proyectos / {horas} h"


def importar(cur: psycopg.Cursor, data: dict) -> dict:
    ensure_sync_storage(cur)
    yo = mi_nombre(cur)
    if not yo:
        raise ValueError("Configura tu nombre de PM en Configuración antes de importar.")
    if (data.get("exportado_por") or "").strip() == yo:
        raise ValueError(f"Este fichero lo exportaste tú ({yo}); impórtalo en la base de datos de otra persona.")
    sincronizar_registro(cur, yo)

    resumen = {"exportado_por": data.get("exportado_por"), "exportado_at": data.get("exportado_at"),
               "cortes_anadidos": [], "cortes_saltados": [], "nombres_anadidos": 0, "decisiones": []}

    existentes = {c["fecha_corte"]: c for c in list_cortes(cur, TIPO_DIRECCION)}
    for corte in data.get("cortes") or []:
        fecha = date.fromisoformat(corte["fecha_corte"])
        local = existentes.get(fecha)
        if local is not None:
            diferente = _resumen_cifras(local["metricas"]) != _resumen_cifras(corte["metricas"])
            resumen["cortes_saltados"].append({
                "fecha": fecha.isoformat(),
                "diferencias": (f"tuyo {_resumen_cifras(local['metricas'])}, "
                                f"fichero {_resumen_cifras(corte['metricas'])}") if diferente else None,
            })
            continue
        ao_id = _buscar_importacion(cur, corte.get("all_orders"), True)
        ots_id = _buscar_importacion(cur, corte.get("ots"), False)
        cur.execute(
            """
            INSERT INTO informe_cortes (fecha_corte, tipo, origen, all_orders_import_id, ots_import_id,
                                        equipos, tipos_proyecto, metricas, importado_de)
            VALUES (%s, 'DIRECCION', %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (fecha, corte.get("origen") or "APP", ao_id, ots_id, json.dumps(corte.get("equipos") or []),
             json.dumps(corte.get("tipos_proyecto") or []), json.dumps(corte["metricas"]),
             corte.get("importado_de") or data.get("exportado_por")),
        )
        corte_id = cur.fetchone()[0]
        if corte.get("detalle") is not None:
            cur.execute("INSERT INTO informe_corte_detalle (corte_id, filas) VALUES (%s, %s)",
                        (corte_id, json.dumps(corte["detalle"])))
        elif ao_id:
            completar_detalles(cur)
        for motivo in corte.get("motivos") or []:
            cur.execute(
                "INSERT INTO informe_motivos (corte_id, project_code, hito, motivo) VALUES (%s, %s, %s, %s)",
                (corte_id, motivo["project_code"], motivo["hito"], motivo["motivo"]),
            )
        resumen["cortes_anadidos"].append({"fecha": fecha.isoformat(), "enlazado": bool(ao_id)})

    for nombre in data.get("nombres") or []:
        cur.execute(
            "INSERT INTO informe_nombres (project_code, nombre) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (nombre["project_code"], nombre["nombre"]),
        )
        resumen["nombres_anadidos"] += cur.rowcount
    for ajuste in data.get("ajustes") or []:
        cur.execute("INSERT INTO app_settings (key, value) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (ajuste["key"], ajuste["value"]))

    registro = _registro(cur)
    cur.execute("SELECT project_code, project_name FROM projects_historical")
    nombres_proyecto = dict(cur.fetchall())
    for remota in data.get("decisiones") or []:
        resultado, detalle = importar_decision(cur, yo, remota, registro)
        if resultado != "igual":
            resumen["decisiones"].append({
                "tipo": TIPO_TITULOS.get(remota["tipo"], remota["tipo"]),
                "project_code": remota["project_code"],
                "project_name": nombres_proyecto.get(remota["project_code"], ""),
                "resultado": resultado,
                "detalle": detalle,
            })
    resumen["conflictos_pendientes"] = contar_conflictos(cur)
    return resumen
