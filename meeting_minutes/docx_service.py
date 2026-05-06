from __future__ import annotations

import io
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

from .models import MeetingMinutesPayload


TRANSLATIONS = {
    "es": {
        "document_title": "Acta de Reunión",
        "project": "Asunto/Proyecto",
        "minutes_title_label": "Título del acta",
        "albaran": "Albarán",
        "date": "Fecha Reunión",
        "time": "Hora inicio - fin",
        "location": "Lugar",
        "phase": "Fase",
        "participants": "Participantes",
        "name": "Nombre",
        "department": "Departamento",
        "absent": "Ausente",
        "notes": "Notas",
        "topics": "Proyectos tratados",
        "discussion": "Detalle de la discusión",
        "decisions": "Decisiones / Acciones",
        "planning": "Planificación / Próximos pasos",
        "yes": "Sí",
        "no": "No",
        "version": "Versión",
        "modified": "Fecha modificación",
    },
    "en": {
        "document_title": "Meeting Minutes",
        "project": "Project / Subject",
        "minutes_title_label": "Minutes title",
        "albaran": "Delivery note",
        "date": "Meeting date",
        "time": "Start - End",
        "location": "Location",
        "phase": "Phase",
        "participants": "Participants",
        "name": "Name",
        "department": "Department",
        "absent": "Absent",
        "notes": "Notes",
        "topics": "Topics discussed",
        "discussion": "Detailed content",
        "decisions": "Decisions / Actions",
        "planning": "Planning / Next steps",
        "yes": "Yes",
        "no": "No",
        "version": "Version",
        "modified": "Modified",
    },
}

CONTENT_TYPES_XML = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">
  <Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>
  <Default Extension=\"xml\" ContentType=\"application/xml\"/>
  <Default Extension=\"svg\" ContentType=\"image/svg+xml\"/>
  <Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>
</Types>
"""

RELS_XML = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>
</Relationships>
"""

DOCUMENT_RELS_XML = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rIdLogo\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/image\" Target=\"media/mecalux_logo.svg\"/>
</Relationships>
"""

MECALUX_LOGO_SVG = """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 960 160\">
  <rect width=\"960\" height=\"160\" fill=\"white\"/>
  <g fill=\"#0061A8\">
    <circle cx=\"78\" cy=\"80\" r=\"72\"/>
    <path d=\"M45 132 74 28h26L71 132H45Zm58 0 24-88 25 44-13 44h-36ZM24 80c0-20 10-37 25-48L30 103a55 55 0 0 1-6-23Zm128 0c0 21-12 40-29 50l19-73c6 7 10 15 10 23Z\" fill=\"white\"/>
    <text x=\"175\" y=\"105\" font-family=\"Arial, Helvetica, sans-serif\" font-size=\"78\" font-weight=\"700\" letter-spacing=\"-3\">MECALUX</text>
  </g>
</svg>
"""


def _has_text(text: str | None) -> bool:
    return bool(str(text or "").strip())


def _text_run(text: str, bold: bool = False) -> str:
    content = escape(str(text or ""))
    bold_xml = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f"<w:r>{bold_xml}<w:t xml:space=\"preserve\">{content}</w:t></w:r>"


def _p(text: str, bold: bool = False) -> str:
    if text is None:
        text = ""
    return f"<w:p>{_text_run(str(text), bold)}</w:p>"


def _empty_p() -> str:
    return "<w:p/>"


def _bullet_p(text: str) -> str:
    return (
        "<w:p><w:pPr><w:ind w:left=\"720\" w:hanging=\"360\"/></w:pPr>"
        f"{_text_run('•')}"
        f"{_text_run('  ' + str(text or '').strip())}"
        "</w:p>"
    )


def _content_paragraphs(text: str | None) -> list[str]:
    paragraphs: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            paragraphs.append(_empty_p())
        elif stripped.startswith("*"):
            paragraphs.append(_bullet_p(stripped[1:]))
        else:
            paragraphs.append(_p(line))
    return paragraphs


def _logo_p() -> str:
    return (
        "<w:p><w:r><w:drawing>"
        '<wp:inline distT="0" distB="0" distL="0" distR="0">'
        '<wp:extent cx="2133600" cy="355600"/>'
        '<wp:docPr id="1" name="Mecalux logo"/>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="mecalux_logo.svg"/>'
        '<pic:cNvPicPr/></pic:nvPicPr><pic:blipFill>'
        '<a:blip r:embed="rIdLogo"/>'
        '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="2133600" cy="355600"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        '</a:graphicData></a:graphic>'
        "</wp:inline>"
        "</w:drawing></w:r></w:p>"
    )


def _tc_xml(
    content_xml: str,
    *,
    width: int,
    grid_span: int | None = None,
    v_merge: str | None = None,
) -> str:
    span_xml = f"<w:gridSpan w:val=\"{grid_span}\"/>" if grid_span else ""
    merge_xml = f"<w:vMerge w:val=\"{v_merge}\"/>" if v_merge else ""
    return (
        "<w:tc>"
        f"<w:tcPr><w:tcW w:w=\"{width}\" w:type=\"dxa\"/>{span_xml}{merge_xml}</w:tcPr>"
        f"{content_xml}"
        "</w:tc>"
    )


def _header_table(t: dict[str, str]) -> str:
    modified_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    rows = [
        "<w:tr>"
        + _tc_xml(_logo_p(), width=2820, v_merge="restart")
        + _tc_xml(_empty_p(), width=6540, grid_span=2)
        + "</w:tr>",
        "<w:tr>"
        + _tc_xml(_empty_p(), width=2820, v_merge="continue")
        + _tc_xml(_p(f"{t['version']}:") + _p("1.0"), width=1560)
        + _tc(f"{t['modified']}: {modified_at}", width=4980)
        + "</w:tr>",
    ]
    return _table(rows)


def _tc(content: str, *, width: int, bold: bool = False, shaded: bool = False, grid_span: int | None = None) -> str:
    span_xml = f"<w:gridSpan w:val=\"{grid_span}\"/>" if grid_span else ""
    shade_xml = '<w:shd w:fill="D9D9D9"/>' if shaded else ""
    return (
        "<w:tc>"
        f"<w:tcPr><w:tcW w:w=\"{width}\" w:type=\"dxa\"/>{span_xml}{shade_xml}</w:tcPr>"
        f"{_p(content, bold=bold)}"
        "</w:tc>"
    )


def _table(rows: list[str], width: int = 9360) -> str:
    if not rows:
        return ""
    return (
        "<w:tbl>"
        "<w:tblPr>"
        f"<w:tblW w:w=\"{width}\" w:type=\"dxa\"/>"
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
        "</w:tblBorders>"
        "</w:tblPr>"
        f"{''.join(rows)}"
        "</w:tbl>"
    )


def _metadata_table(payload: MeetingMinutesPayload, t: dict[str, str]) -> str:
    time_value = " - ".join(value for value in (payload.start_time, payload.end_time) if _has_text(value))
    fields = [
        (t["minutes_title_label"], payload.title),
        (t["project"], payload.project_subject),
        (t["albaran"], payload.albaran_number),
        (t["date"], payload.meeting_date),
        (t["time"], time_value),
        (t["location"], payload.location),
        (t["phase"], payload.phase),
    ]
    fields = [(label, str(value).strip()) for label, value in fields if _has_text(value)]
    rows: list[str] = []
    for idx in range(0, len(fields), 2):
        first = fields[idx]
        second = fields[idx + 1] if idx + 1 < len(fields) else None
        cells = [
            _tc(first[0], width=1860, bold=True, shaded=True),
            _tc(first[1], width=2820),
        ]
        if second:
            cells.extend([
                _tc(second[0], width=1860, bold=True, shaded=True),
                _tc(second[1], width=2820),
            ])
        else:
            cells.append(_tc("", width=4680, grid_span=2))
        rows.append(f"<w:tr>{''.join(cells)}</w:tr>")
    return _table(rows)


def _participant_has_content(participant) -> bool:
    return any(
        _has_text(value)
        for value in (participant.name, participant.department, participant.notes)
    ) or participant.absent


def _participants_table(payload: MeetingMinutesPayload, t: dict[str, str]) -> str:
    participants = [participant for participant in (payload.participants or []) if _participant_has_content(participant)]
    if not participants:
        return ""
    rows = [
        "<w:tr>"
        + _tc(t["name"], width=1860, bold=True)
        + _tc(t["department"], width=1740, bold=True)
        + _tc(t["absent"], width=1620, bold=True)
        + _tc(t["notes"], width=4140, bold=True)
        + "</w:tr>"
    ]
    for participant in participants:
        rows.append(
            "<w:tr>"
            + _tc(participant.name or "", width=1860)
            + _tc(participant.department or "", width=1740)
            + _tc(t["yes"] if participant.absent else t["no"], width=1620)
            + _tc(participant.notes or "", width=4140)
            + "</w:tr>"
        )
    return _table(rows)


def _append_section(body_parts: list[str], title: str, content: str | None) -> None:
    if not _has_text(content):
        return
    body_parts.append(_p(title, bold=True))
    body_parts.extend(_content_paragraphs(content))
    body_parts.append(_empty_p())


def _topic_block_has_content(block) -> bool:
    return any(
        _has_text(value)
        for value in (block.topic, block.discussion, block.decisions_actions, block.planning_next_steps)
    )


def build_meeting_minutes_docx(payload: MeetingMinutesPayload) -> bytes:
    t = TRANSLATIONS[payload.language]
    body_parts = [_header_table(t), _empty_p(), _metadata_table(payload, t), _empty_p()]

    participants_table = _participants_table(payload, t)
    if participants_table:
        body_parts.extend([_p(t["participants"], bold=True), participants_table, _empty_p()])

    if payload.topic_blocks:
        for block in payload.topic_blocks:
            if not _topic_block_has_content(block):
                continue
            if _has_text(block.topic):
                body_parts.extend(_content_paragraphs(block.topic))
                body_parts.append(_empty_p())
            _append_section(body_parts, t["discussion"], block.discussion)
            _append_section(body_parts, t["decisions"], block.decisions_actions)
            _append_section(body_parts, t["planning"], block.planning_next_steps)
    else:
        _append_section(body_parts, t["topics"], payload.topics)
        _append_section(body_parts, t["discussion"], payload.discussion)
        _append_section(body_parts, t["decisions"], payload.decisions_actions)
        _append_section(body_parts, t["planning"], payload.planning_next_steps)
    body_parts.append("<w:sectPr/>")

    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" "
        "xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\" "
        "xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" "
        "xmlns:pic=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
        f"<w:body>{''.join(body_parts)}</w:body></w:document>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("_rels/.rels", RELS_XML)
        zf.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS_XML)
        zf.writestr("word/media/mecalux_logo.svg", MECALUX_LOGO_SVG)
        zf.writestr("word/document.xml", document_xml)
    return buffer.getvalue()
