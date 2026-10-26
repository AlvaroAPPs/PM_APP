"""Genera la presentacion "Estado Ampliaciones" a partir de un corte.

Parte de la ultima presentacion real (assets/informe_direccion_plantilla.pptx)
y solo sustituye los datos: valores cacheados de los graficos, textos de
entradas/salidas y la fecha de portada. Asi se conservan intactos formato,
colores y maquetacion. Los graficos de la plantilla estaban vinculados al
Excel generador; ese vinculo se elimina y los datos quedan dentro del PPT.

Diapositivas que se rellenan (indice 1-based de la plantilla):
  1  portada (fecha)
  4  proyectos en curso + horas (ultimos 12 cortes DIRECCION)
  5  entradas / salidas respecto al corte DIRECCION anterior
  6  tartas por tamano de proyecto
  7  barras agrupacion de horas
  8  facturacion vs avance
  9  facturacion vs horas invertidas
  10 proyectos entregados (acumulado ano anterior vs actual)
  11 horas entregadas (acumulado ano anterior vs actual)
El resto (objetivos, hitos retrasados, otros temas) queda como en la plantilla.
"""

from __future__ import annotations

import copy
import io
import re
from datetime import date
from pathlib import Path

from lxml import etree
from pptx import Presentation

TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "informe_direccion_plantilla.pptx"

C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"c": C_NS}

HISTORY_POINTS = 12
SIZE_KEYS = ("s", "m", "l")
BILLING_KEYS = ("total", "s", "m", "l")
BILLING_SERIES = ("base", "facturado", "rojo", "verde")
MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


# ------------------------------------
# Graficos: sustitucion de valores cacheados
# ------------------------------------

def _excel_serial(value: date) -> int:
    return (value - date(1899, 12, 30)).days


def _c(tag: str) -> str:
    return f"{{{C_NS}}}{tag}"


def _fill_cache(container: etree._Element, values: list) -> None:
    """Rellena numRef/strRef (su cache) o numLit/strLit con `values`.
    Los None se omiten (punto vacio), igual que una celda en blanco."""
    data = None
    for child in container:
        tag = etree.QName(child).localname
        if tag in ("numRef", "strRef"):
            cache_tag = "numCache" if tag == "numRef" else "strCache"
            data = child.find(f"c:{cache_tag}", NS)
            if data is None:
                data = etree.SubElement(child, _c(cache_tag))
            break
        if tag in ("numLit", "strLit"):
            data = child
            break
    if data is None:
        raise ValueError("Serie de grafico sin datos cacheados")

    for pt in data.findall("c:pt", NS):
        data.remove(pt)
    count = data.find("c:ptCount", NS)
    if count is None:
        count = etree.Element(_c("ptCount"))
        format_code = data.find("c:formatCode", NS)
        if format_code is not None:
            format_code.addnext(count)
        else:
            data.insert(0, count)
    count.set("val", str(len(values)))

    anchor = count
    for index, value in enumerate(values):
        if value is None:
            continue
        pt = etree.Element(_c("pt"))
        pt.set("idx", str(index))
        etree.SubElement(pt, _c("v")).text = str(value)
        anchor.addnext(pt)
        anchor = pt


def _set_series_name(ser: etree._Element, name: str) -> None:
    tx = ser.find("c:tx", NS)
    if tx is None:
        return
    v = tx.find("c:v", NS)
    if v is not None:
        v.text = name
    else:
        _fill_cache(tx, [name])


def _unlink_chart(chart) -> None:
    """Quita el vinculo al Excel externo para que PowerPoint no pida actualizarlo."""
    chart_space = chart._chartSpace
    external = chart_space.find("c:externalData", NS)
    if external is None:
        return
    rel_id = external.get(f"{{{R_NS}}}id")
    chart_space.remove(external)
    if rel_id and rel_id in chart.part.rels:
        chart.part.drop_rel(rel_id)


def _update_chart(chart, categories: list, series: list[list], names: list[str] | None = None) -> None:
    sers = chart._chartSpace.findall(".//c:ser", NS)
    if len(sers) != len(series):
        raise ValueError(f"El grafico tiene {len(sers)} series y se esperaban {len(series)}")
    for index, (ser, values) in enumerate(zip(sers, series)):
        cat = ser.find("c:cat", NS)
        if cat is not None:
            _fill_cache(cat, categories)
        _fill_cache(ser.find("c:val", NS), values)
        if names:
            _set_series_name(ser, names[index])
    _unlink_chart(chart)


def _chart_by_name(slide, name: str):
    """La plantilla tiene copias vacias (sin series) con el mismo nombre; se usa la que tiene datos."""
    for shape in slide.shapes:
        if shape.name == name and getattr(shape, "has_chart", False) and shape.has_chart:
            if shape.chart._chartSpace.find(".//c:ser", NS) is not None:
                return shape.chart
    raise ValueError(f"No se encuentra el grafico '{name}' en la diapositiva")


# ------------------------------------
# Textos
# ------------------------------------

LEGAL_SUFFIX_RE = re.compile(
    r"[\s,.-]+(S\.?\s?A\.?\s?U\.?|S\.?\s?L\.?\s?U\.?|S\.?\s?A\.?|S\.?\s?L\.?|B\.?\s?V\.?|S\.?\s?P\.?\s?A\.?|SAS|LTDA?\.?|GMBH)\s*$",
    re.IGNORECASE,
)


def _short_name(item: dict) -> str:
    name = item.get("client") or item.get("project_name") or item.get("code") or ""
    previous = None
    while previous != name:
        previous = name
        name = LEGAL_SUFFIX_RE.sub("", name).strip(" ,.-")
    return name


def _fmt_hours(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return f"{round(value):.0f}"
    return f"{value:.1f}".replace(".", ",")


def _set_runs(paragraph, texts: list[str]) -> None:
    runs = paragraph.runs
    for run, text in zip(runs, texts):
        run.text = text
    for run in runs[len(texts):]:
        run.text = ""


def _clone_paragraph(prototype, texts: list[str]):
    element = copy.deepcopy(prototype._p)
    from pptx.text.text import _Paragraph

    paragraph = _Paragraph(element, prototype._parent)
    _set_runs(paragraph, texts)
    return element


def _rebuild_text(text_frame, blocks: list[tuple[object, list[str]]]) -> None:
    """Sustituye los parrafos por clones de los prototipos indicados."""
    elements = [_clone_paragraph(proto, texts) for proto, texts in blocks]
    tx_body = text_frame._txBody
    for p in list(tx_body.p_lst):
        tx_body.remove(p)
    for element in elements:
        tx_body.append(element)


def _shape_by_text(slide, startswith: str):
    for shape in slide.shapes:
        if shape.has_text_frame and shape.text_frame.text.strip().upper().startswith(startswith):
            return shape
    raise ValueError(f"No se encuentra el cuadro de texto '{startswith}'")


def _tables(slide) -> list:
    return sorted((s for s in slide.shapes if s.has_table), key=lambda s: s.left)


def _set_cell(cell, text: str) -> None:
    paragraph = cell.text_frame.paragraphs[0]
    if paragraph.runs:
        _set_runs(paragraph, [text])
    else:
        paragraph.text = text


def _fill_entradas_salidas(slide, delta: dict | None) -> None:
    entradas_box = _shape_by_text(slide, "ENTRADAS")
    salidas_box = _shape_by_text(slide, "SALIDAS")
    tabla_entradas, tabla_salidas = _tables(slide)

    if delta is None:
        return

    # Prototipos de formato tomados de la plantilla
    ep = entradas_box.text_frame.paragraphs
    e_header, e_cambios, e_cambio_item = ep[0], ep[1], ep[2]
    e_section = next(p for p in ep if p.text.strip().startswith("Proyectos >400"))
    e_none = next(p for p in ep if p.text.strip() == "Ninguno")
    e_item = next(p for p in ep if p.level == 1 and p.runs and p.runs[0].font.size and p.runs[0].font.size.pt == 11)
    e_small = next(p for p in ep if p.text.strip().startswith("Proyectos <100"))

    sp = salidas_box.text_frame.paragraphs
    s_header = sp[0]
    s_section = next(p for p in sp if p.text.strip().startswith("Proyectos >400"))
    s_none = next(p for p in sp if p.text.strip() == "Ninguno")
    s_item = next(p for p in sp if p.level == 1 and p.text.strip() != "Ninguno")
    s_small = next(p for p in sp if p.text.strip().startswith("Proyectos <100"))

    entradas = delta["entradas"]
    salidas = delta["salidas"]

    def _items(tramo: list[dict], item_proto, none_proto) -> list:
        if not tramo:
            return [(none_proto, ["Ninguno"])]
        return [(item_proto, [f"{_short_name(i)} ({_fmt_hours(i['hours'])} h)"]) for i in tramo]

    blocks = [
        (e_header, ["ENTRADAS", ": ( ", f"{_fmt_hours(entradas['total_horas'])} ", "h)"]),
        (e_cambios, ["Cambio horas proyectos existentes: ", f"{_fmt_hours(entradas['cambios_horas'])} h "]),
    ]
    blocks += [(e_cambio_item, [f"{_short_name(i)} ({_fmt_hours(i['hours'])} h)"]) for i in entradas["cambios"]]
    blocks.append((e_section, ["Proyectos >400 h:"]))
    blocks += _items(entradas["tramos"]["l"], e_item, e_none)
    blocks.append((e_section, ["Proyectos entre 100 y 400 h: "]))
    blocks += _items(entradas["tramos"]["m"], e_item, e_none)
    blocks.append((e_small, ["Proyectos <100 horas"]))
    _rebuild_text(entradas_box.text_frame, blocks)

    blocks = [(s_header, ["SALIDAS", ": ", f"({_fmt_hours(salidas['total_horas'])} h)"])]
    blocks.append((s_section, ["Proyectos >400 h"]))
    blocks += _items(salidas["tramos"]["l"], s_item, s_none)
    blocks.append((s_section, ["Proyectos entre 100 y 400 h:"]))
    blocks += _items(salidas["tramos"]["m"], s_item, s_none)
    blocks.append((s_small, ["Proyectos <100 horas"]))
    _rebuild_text(salidas_box.text_frame, blocks)

    for table_shape, tramo in ((tabla_entradas, entradas["tramos"]["s"]), (tabla_salidas, salidas["tramos"]["s"])):
        table = table_shape.table
        _set_cell(table.cell(0, 1), str(len(tramo)))
        _set_cell(table.cell(1, 1), _fmt_hours(sum(i["hours"] for i in tramo)))


# ------------------------------------
# Presentacion completa
# ------------------------------------

def generar_presentacion(corte: dict, historico: list[dict], delta: dict | None, entregas_anterior: dict | None) -> bytes:
    """`historico`: cortes DIRECCION hasta el corte (incluido), ordenados por fecha.
    `delta`: resultado de comparar_cortes contra el corte DIRECCION anterior (o None).
    `entregas_anterior`: entregas acumuladas del ano anterior {"horas", "proyectos"}."""
    prs = Presentation(str(TEMPLATE_PATH))
    slides = prs.slides
    metricas = corte["metricas"]
    fecha: date = corte["fecha_corte"]

    # 1. Portada
    portada = _shape_by_text(slides[0], "20")
    _set_runs(portada.text_frame.paragraphs[0], [fecha.isoformat()])

    # 4. Historico de proyectos y horas
    puntos = [c for c in historico if c["metricas"].get("proyectos") and c["metricas"].get("horas")][-HISTORY_POINTS:]
    fechas = [_excel_serial(c["fecha_corte"]) for c in puntos]
    _update_chart(
        _chart_by_name(slides[3], "Chart 1"), fechas,
        [[c["metricas"]["proyectos"]["totales"] for c in puntos],
         [c["metricas"]["proyectos"]["activos"] for c in puntos]],
    )
    _update_chart(
        _chart_by_name(slides[3], "cht_Graf_02_Horas"), fechas,
        [[c["metricas"]["horas"][key] for c in puntos] for key in ("totales", "pendientes", "ejecutables")],
    )

    # 5. Entradas / salidas
    _fill_entradas_salidas(slides[4], delta)

    # 6-7. Tramos por tamano de proyecto
    tramos = metricas["tramos"]
    _update_chart(
        _chart_by_name(slides[5], "cht_Graf_03_TrabajoHoras"),
        ["Horas proyectos <= 100", "Horas proyectos > 100 y < 400", "Horas proyectos >= 400"],
        [[tramos[k]["total"] for k in SIZE_KEYS]],
    )
    _update_chart(
        _chart_by_name(slides[5], "cht_Graf_04_TrabajoPendiente"),
        ["Horas pendientes proyectos <= 100", "Horas pendientes proyectos > 100 y < 400",
         "Horas pendientes proyectos >= 400"],
        [[tramos[k]["pendiente"] for k in SIZE_KEYS]],
    )
    horas = metricas["horas"]
    general = {"total": horas["totales"], "pendiente": horas["pendientes"], "ejecutable": horas["ejecutables"]}
    _update_chart(
        _chart_by_name(slides[6], "cht_Graf_05_BarrasAgrupacion"),
        ["<=100", "100-400", ">=400", "General"],
        [[tramos[k][serie] for k in SIZE_KEYS] + [general[serie]] for serie in ("total", "pendiente", "ejecutable")],
    )

    # 8-9. Facturacion
    for slide_index, chart_name, key in (
        (7, "cht_Graf_07_AvanceVsFacturacion", "avance_vs_facturacion"),
        (8, "cht_Graf_06_HorasVsFacturacion", "horas_vs_facturacion"),
    ):
        data = metricas.get(key)
        if data:
            _update_chart(
                _chart_by_name(slides[slide_index], chart_name),
                ["Total", "<=100", "100-400", ">=400"],
                [[data[group][serie] for group in BILLING_KEYS] for serie in BILLING_SERIES],
            )

    # 10-11. Entregas acumuladas
    entregas = metricas.get("entregas")
    if entregas:
        anterior = entregas_anterior or {"horas": [None] * 12, "proyectos": [None] * 12}
        names = [str(fecha.year - 1), str(fecha.year)]
        _update_chart(
            _chart_by_name(slides[9], "cht_Graf_09_EntregasProyectos"), MONTH_LABELS,
            [anterior["proyectos"], entregas["proyectos"]], names,
        )
        _update_chart(
            _chart_by_name(slides[10], "cht_Graf_08_EntregasHoras"), MONTH_LABELS,
            [anterior["horas"], entregas["horas"]], names,
        )

    output = io.BytesIO()
    prs.save(output)
    return output.getvalue()
