from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
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
        "topics": "Objetivos de la reunión y temas tratados",
        "discussion": "Resumen de lo tratado",
        "decisions": "Decisiones / Acciones",
        "planning": "Planificación / Próximos pasos",
        "approval_notice": "Si no hay ningún comentario o anotación, el acta se dará por aprobada a los 2 días laborables de su envío.",
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
        "topics": "Meeting objectives and topics discussed",
        "discussion": "Discussion summary",
        "decisions": "Decisions / Actions",
        "planning": "Planning / Next steps",
        "approval_notice": "If there are no comments or annotations, the minutes will be considered approved 2 business days after being sent.",
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
  <Default Extension=\"jpg\" ContentType=\"image/jpeg\"/>
  <Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>
  <Override PartName=\"/word/header1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml\"/>
</Types>
"""

RELS_XML = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>
</Relationships>
"""

DOCUMENT_RELS_XML = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rIdHeader\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/header\" Target=\"header1.xml\"/>
</Relationships>
"""

HEADER_RELS_XML = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rIdLogo\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/image\" Target=\"media/mecalux_logo.jpg\"/>
</Relationships>
"""

LOGO_IMAGE_PATH = Path(__file__).with_name("assets") / "mecalux_logo.jpg"
LOGO_IMAGE_DOCX_PATH = "word/media/mecalux_logo.jpg"
LOGO_IMAGE_WIDTH_EMU = 2133600
LOGO_IMAGE_HEIGHT_EMU = 391160


def _filename_part(value: str | None, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or fallback))
    ascii_value = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    safe_value = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_value).strip("_")
    return safe_value or fallback


def _filename_date(value: str | None) -> str:
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        return datetime.now().strftime("%Y%m%d")


def build_meeting_minutes_filename(payload: MeetingMinutesPayload) -> str:
    prefix = _filename_part(payload.albaran_number, "Meeting_Minutes")
    date_value = _filename_date(payload.meeting_date)
    project_name = _filename_part(payload.project_subject or payload.title, "Project")
    language = _filename_part(payload.language.upper(), "ES")
    return f"{prefix}_{date_value}_{project_name}_Meeting_Minutes_{language}.docx"


def _has_text(text: str | None) -> bool:
    return bool(str(text or "").strip())


def _text_run(text: str, bold: bool = False, italic: bool = False, underline: bool = False) -> str:
    content = escape(str(text or ""))
    style_xml = ""
    if bold or italic or underline:
        style_parts = []
        if bold:
            style_parts.append("<w:b/>")
        if italic:
            style_parts.append("<w:i/>")
        if underline:
            style_parts.append('<w:u w:val="single"/>')
        style_xml = f"<w:rPr>{''.join(style_parts)}</w:rPr>"
    return f'<w:r>{style_xml}<w:t xml:space="preserve">{content}</w:t></w:r>'


def _p(text: str, bold: bool = False, italic: bool = False, underline: bool = False) -> str:
    if text is None:
        text = ""
    return f"<w:p>{_text_run(str(text), bold, italic, underline)}</w:p>"


def _empty_p() -> str:
    return "<w:p/>"


def _bullet_p(text: str) -> str:
    return (
        '<w:p><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr>'
        f"{_text_run('•')}"
        f"{_text_run('  ' + str(text or '').strip())}"
        "</w:p>"
    )


def _numbered_topic_p(index: int, text: str) -> str:
    return (
        '<w:p><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr>'
        f"{_text_run(f'{index}) ')}"
        f"{_text_run(str(text or '').strip())}"
        "</w:p>"
    )


def _horizontal_rule_p() -> str:
    return (
        '<w:p><w:pPr><w:pBdr>'
        '<w:bottom w:val="single" w:sz="8" w:space="1" w:color="808080"/>'
        '</w:pBdr></w:pPr></w:p>'
    )


def _approval_notice_p(text: str) -> str:
    return f"<w:p>{_text_run(text, bold=True)}</w:p>"


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
        f'<wp:extent cx="{LOGO_IMAGE_WIDTH_EMU}" cy="{LOGO_IMAGE_HEIGHT_EMU}"/>'
        '<wp:docPr id="1" name="Mecalux logo"/>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="mecalux_logo.jpg"/>'
        '<pic:cNvPicPr/></pic:nvPicPr><pic:blipFill>'
        '<a:blip r:embed="rIdLogo"/>'
        '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{LOGO_IMAGE_WIDTH_EMU}" cy="{LOGO_IMAGE_HEIGHT_EMU}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        '</a:graphicData></a:graphic>'
        "</wp:inline>"
        "</w:drawing></w:r></w:p>"
    )


def _tc_pr_xml(*, width: int, grid_span: int | None = None) -> str:
    span_xml = f"<w:gridSpan w:val=\"{grid_span}\"/>" if grid_span else ""
    return (
        f"<w:tcW w:w=\"{width}\" w:type=\"dxa\"/>{span_xml}"
        "<w:tcMar>"
        '<w:top w:w="80" w:type="dxa"/>'
        '<w:left w:w="100" w:type="dxa"/>'
        '<w:bottom w:w="80" w:type="dxa"/>'
        '<w:right w:w="100" w:type="dxa"/>'
        "</w:tcMar>"
    )


def _tc_xml(
    content_xml: str,
    *,
    width: int,
    grid_span: int | None = None,
    v_merge: str | None = None,
    v_align: str | None = None,
) -> str:
    merge_xml = f"<w:vMerge w:val=\"{v_merge}\"/>" if v_merge else ""
    align_xml = f"<w:vAlign w:val=\"{v_align}\"/>" if v_align else ""
    return (
        "<w:tc>"
        f"<w:tcPr>{_tc_pr_xml(width=width, grid_span=grid_span)}{merge_xml}{align_xml}</w:tcPr>"
        f"{content_xml}"
        "</w:tc>"
    )


def _header_table(t: dict[str, str]) -> str:
    modified_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    rows = [
        "<w:tr>"
        + _tc_xml(_logo_p(), width=2820, v_merge="restart", v_align="center")
        + _tc_xml(_empty_p(), width=6540, grid_span=2)
        + "</w:tr>",
        "<w:tr>"
        + _tc_xml(_empty_p(), width=2820, v_merge="continue", v_align="center")
        + _tc_xml(_p(f"{t['version']}:") + _p("1.0"), width=1560)
        + _tc(f"{t['modified']}: {modified_at}", width=4980)
        + "</w:tr>",
    ]
    return _table(rows)


def _tc(content: str, *, width: int, bold: bool = False, shaded: bool = False, grid_span: int | None = None) -> str:
    shade_xml = '<w:shd w:fill="D9D9D9"/>' if shaded else ""
    return (
        "<w:tc>"
        f"<w:tcPr>{_tc_pr_xml(width=width, grid_span=grid_span)}{shade_xml}</w:tcPr>"
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



def _header_xml(t: dict[str, str]) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'{_header_table(t)}'
        '</w:hdr>'
    )


def _metadata_table(payload: MeetingMinutesPayload, t: dict[str, str]) -> str:
    time_value = " - ".join(value for value in (payload.start_time, payload.end_time) if _has_text(value))
    rows = [
        "<w:tr>"
        + _tc(t["project"], width=1860, bold=True, shaded=True)
        + _tc(payload.project_subject, width=7500, grid_span=3)
        + "</w:tr>",
        "<w:tr>"
        + _tc(t["date"], width=1860, bold=True, shaded=True)
        + _tc(payload.meeting_date, width=2820)
        + _tc(t["time"], width=1860, bold=True, shaded=True)
        + _tc(time_value, width=2820)
        + "</w:tr>",
        "<w:tr>"
        + _tc(t["phase"], width=1860, bold=True, shaded=True)
        + _tc(payload.phase, width=7500, grid_span=3)
        + "</w:tr>",
    ]

    optional_rows: list[str] = []
    if _has_text(payload.albaran_number):
        optional_rows.append(
            "<w:tr>"
            + _tc(t["albaran"], width=1860, bold=True, shaded=True)
            + _tc(payload.albaran_number, width=7500, grid_span=3)
            + "</w:tr>"
        )
    if _has_text(payload.location):
        optional_rows.append(
            "<w:tr>"
            + _tc(t["location"], width=1860, bold=True, shaded=True)
            + _tc(payload.location, width=7500, grid_span=3)
            + "</w:tr>"
        )
    return _table(rows + optional_rows)


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


def _append_section(
    body_parts: list[str],
    title: str,
    content: str | None,
    *,
    title_bold: bool = True,
    title_italic: bool = False,
    title_underline: bool = False,
) -> None:
    if not _has_text(content):
        return
    body_parts.append(_p(title, bold=title_bold, italic=title_italic, underline=title_underline))
    body_parts.extend(_content_paragraphs(content))
    body_parts.append(_empty_p())


def _topic_titles(payload: MeetingMinutesPayload) -> list[str]:
    if payload.topic_blocks:
        return [str(block.topic).strip() for block in payload.topic_blocks if _has_text(block.topic)]
    return [line.strip().lstrip('*').strip() for line in str(payload.topics or '').splitlines() if _has_text(line)]


def _append_topics_overview(body_parts: list[str], payload: MeetingMinutesPayload, title: str) -> None:
    topics = _topic_titles(payload)
    if not topics:
        return
    body_parts.append(_p(title, bold=True, underline=True))
    for index, topic in enumerate(topics, start=1):
        body_parts.append(_numbered_topic_p(index, topic))


def _append_approval_notice(body_parts: list[str], text: str) -> None:
    body_parts.append(_horizontal_rule_p())
    body_parts.append(_approval_notice_p(text))
    body_parts.append(_horizontal_rule_p())


def _topic_block_has_content(block) -> bool:
    return any(
        _has_text(value)
        for value in (block.topic, block.discussion, block.decisions_actions, block.planning_next_steps)
    )


def build_meeting_minutes_docx(payload: MeetingMinutesPayload) -> bytes:
    t = TRANSLATIONS[payload.language]
    header_xml = _header_xml(t)
    body_parts = [_empty_p(), _metadata_table(payload, t), _empty_p()]

    participants_table = _participants_table(payload, t)
    if participants_table:
        body_parts.extend([_p(t["participants"], bold=True, underline=True), participants_table, _empty_p()])

    _append_topics_overview(body_parts, payload, t["topics"])

    if payload.topic_blocks:
        has_previous_topic_block = False
        for block in payload.topic_blocks:
            if not _topic_block_has_content(block):
                continue
            if has_previous_topic_block:
                body_parts.append(_horizontal_rule_p())
            has_previous_topic_block = True
            if _has_text(block.topic):
                body_parts.append(_p(block.topic, bold=True, underline=True))
            body_parts.extend(_content_paragraphs(block.discussion))
            if _has_text(block.discussion):
                body_parts.append(_empty_p())
            _append_section(body_parts, t["decisions"], block.decisions_actions, title_italic=True)
            _append_section(body_parts, t["planning"], block.planning_next_steps, title_italic=True)
    else:
        fallback_topics = _topic_titles(payload)
        discussion_title = fallback_topics[0] if fallback_topics else t["discussion"]
        _append_section(body_parts, discussion_title, payload.discussion, title_underline=True)
        _append_section(body_parts, t["decisions"], payload.decisions_actions, title_italic=True)
        _append_section(body_parts, t["planning"], payload.planning_next_steps, title_italic=True)

    _append_approval_notice(body_parts, t["approval_notice"])
    body_parts.append('<w:sectPr><w:headerReference w:type="default" r:id="rIdHeader"/></w:sectPr>')

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
        zf.writestr("word/_rels/header1.xml.rels", HEADER_RELS_XML)
        zf.write(LOGO_IMAGE_PATH, LOGO_IMAGE_DOCX_PATH)
        zf.writestr("word/header1.xml", header_xml)
        zf.writestr("word/document.xml", document_xml)
    return buffer.getvalue()
