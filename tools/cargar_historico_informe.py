"""Carga el historico del informe de direccion desde el Excel generador (.xlsm).

Uso:
    python tools/cargar_historico_informe.py "<ruta>\\20261005_Generador_Informe.xlsm"

- Crea un corte DIRECCION por cada fecha de la hoja `Tablas` (graficos 1-7),
  con origen EXCEL (o MANUAL si en el Excel venia del historico manual).
  Las fechas que ya existan en `informe_cortes` no se tocan.
- Asocia cada corte a la importacion AllOrders/OTS cuyo nombre lleva la fecha
  (AAMMDD), para poder calcular entradas/salidas contra el.
- Guarda las entregas acumuladas del ano anterior (hoja HistoricoManual) y
  las del ano del ultimo corte (hoja Tablas) en app_settings.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import openpyxl
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reports.informe_direccion import (  # noqa: E402
    DB_DSN,
    DEFAULT_PROJECT_TYPES,
    DEFAULT_TEAMS,
    ensure_informe_storage,
    set_entregas_anio,
)

FIRST_DATA_ROW = 5


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _num(value) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _billing(values: list) -> dict:
    keys = ("total", "s", "m", "l")
    return {
        key: {"base": _num(values[i * 4]), "facturado": _num(values[i * 4 + 1]),
              "rojo": _num(values[i * 4 + 2]), "verde": _num(values[i * 4 + 3])}
        for i, key in enumerate(keys)
    }


def leer_tablas(wb) -> dict[date, dict]:
    """Columnas (1-based) de la hoja Tablas segun modGraficos."""
    rows = list(wb["Tablas"].iter_rows(min_row=FIRST_DATA_ROW, values_only=True))
    cortes: dict[date, dict] = {}

    def block(row, start, width):
        return list(row[start - 1:start - 1 + width])

    for row in rows:
        # Grafico 1 (A-F) y 2 (H-M)
        fecha = _as_date(row[0])
        if fecha:
            corte = cortes.setdefault(fecha, {"origen": row[5], "metricas": {}})
            corte["metricas"]["proyectos"] = {"totales": int(_num(row[2])), "activos": int(_num(row[3])),
                                              "parados": int(_num(row[4]))}
        fecha2 = _as_date(row[7])
        if fecha2:
            corte = cortes.setdefault(fecha2, {"origen": row[12], "metricas": {}})
            corte["metricas"]["horas"] = {"totales": int(_num(row[9])), "pendientes": int(_num(row[10])),
                                          "ejecutables": int(_num(row[11]))}
        # Grafico 5 (AC-AP): tramos total/pendiente/ejecutable (incluye los graficos 3 y 4)
        fecha5 = _as_date(row[28])
        if fecha5:
            v = block(row, 31, 9)
            cortes.setdefault(fecha5, {"origen": row[42], "metricas": {}})["metricas"]["tramos"] = {
                group: {"total": int(_num(v[i * 3])), "pendiente": int(_num(v[i * 3 + 1])),
                        "ejecutable": int(_num(v[i * 3 + 2]))}
                for i, group in enumerate(("s", "m", "l"))
            }
        # Grafico 6 (AR-BJ) y 7 (BL-CD); antes de tener datos de facturacion son 0
        fecha6 = _as_date(row[43])
        if fecha6:
            values = block(row, 46, 16)
            if any(_num(v) for v in values):
                cortes.setdefault(fecha6, {"origen": row[61], "metricas": {}})["metricas"]["horas_vs_facturacion"] = _billing(values)
        fecha7 = _as_date(row[63])
        if fecha7:
            values = block(row, 66, 16)
            if any(_num(v) for v in values):
                cortes.setdefault(fecha7, {"origen": row[81], "metricas": {}})["metricas"]["avance_vs_facturacion"] = _billing(values)
    return cortes


def leer_entregas(wb) -> dict[int, dict]:
    """Filas de las tablas de entregas acumuladas (Tablas CP:DB, filas 5-6 y 11-12)."""
    ws = wb["Tablas"]
    result: dict[int, dict] = {}
    for horas_row, proyectos_row in ((5, 11), (6, 12)):
        horas = [c for c in next(ws.iter_rows(min_row=horas_row, max_row=horas_row, min_col=94, max_col=106, values_only=True))]
        proyectos = [c for c in next(ws.iter_rows(min_row=proyectos_row, max_row=proyectos_row, min_col=94, max_col=106, values_only=True))]
        year = int(_num(horas[0]))
        if year:
            to_value = lambda v: None if v in (None, "") else _num(v)  # noqa: E731
            result[year] = {"horas": [to_value(v) for v in horas[1:]], "proyectos": [to_value(v) for v in proyectos[1:]]}
    return result


def buscar_importacion(cur, fecha: date, all_orders: bool) -> int | None:
    token = fecha.strftime("%y%m%d")
    cur.execute(
        """
        SELECT f.id
        FROM import_file f
        WHERE f.filename LIKE %s
          AND (EXISTS (SELECT 1 FROM all_orders_snapshot a WHERE a.import_file_id = f.id)) = %s
        ORDER BY f.id DESC
        LIMIT 1
        """,
        (f"%{token}%", all_orders),
    )
    row = cur.fetchone()
    return row[0] if row else None


def main(path: str) -> None:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    cortes = leer_tablas(wb)
    entregas = leer_entregas(wb)
    ultima = max(cortes)

    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_informe_storage(cur)
            cur.execute("SELECT fecha_corte FROM informe_cortes")
            existentes = {row[0] for row in cur.fetchall()}
            creados = 0
            for fecha in sorted(cortes):
                if fecha in existentes:
                    continue
                corte = cortes[fecha]
                metricas = corte["metricas"]
                if fecha == ultima and fecha.year in entregas:
                    metricas["entregas"] = entregas[fecha.year]
                origen = "MANUAL" if str(corte["origen"] or "").strip().lower() == "manual" else "EXCEL"
                cur.execute(
                    """
                    INSERT INTO informe_cortes (fecha_corte, tipo, origen, all_orders_import_id, ots_import_id,
                                                equipos, tipos_proyecto, metricas)
                    VALUES (%s, 'DIRECCION', %s, %s, %s, %s, %s, %s)
                    """,
                    (fecha, origen, buscar_importacion(cur, fecha, True), buscar_importacion(cur, fecha, False),
                     json.dumps(DEFAULT_TEAMS), json.dumps(DEFAULT_PROJECT_TYPES), json.dumps(metricas)),
                )
                creados += 1
            for year, data in entregas.items():
                if year < ultima.year:
                    set_entregas_anio(cur, year, data["horas"], data["proyectos"])
        conn.commit()
    print(f"Cortes creados: {creados} (ya existian {len(existentes)}). Ultimo corte: {ultima}.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
