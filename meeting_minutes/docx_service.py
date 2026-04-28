from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from .models import MeetingMinutesPayload


TRANSLATIONS = {
    "es": {
        "document_title": "Acta de Reunión",
        "project": "Proyecto / Asunto",
        "minutes_title_label": "Título del acta",
        "albaran": "Albarán",
        "date": "Fecha",
        "time": "Hora",
        "location": "Ubicación",
        "phase": "Fase",
        "participants": "Participantes",
        "name": "Nombre",
        "department": "Departamento",
        "absent": "Ausente",
        "notes": "Notas",
        "topics": "Temas tratados",
        "discussion": "Detalle de la discusión",
        "decisions": "Decisiones / Acciones",
        "planning": "Planificación / Próximos pasos",
        "yes": "Sí",
        "no": "No",
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
    },
}

CONTENT_TYPES_XML = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">
  <Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>
  <Default Extension=\"xml\" ContentType=\"application/xml\"/>
  <Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>
</Types>
"""

RELS_XML = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">
  <Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>
</Relationships>
"""


def _p(text: str, bold: bool = False) -> str:
    if text is None:
        text = ""
    content = escape(str(text))
    if bold:
        return f"<w:p><w:r><w:rPr><w:b/></w:rPr><w:t xml:space=\"preserve\">{content}</w:t></w:r></w:p>"
    return f"<w:p><w:r><w:t xml:space=\"preserve\">{content}</w:t></w:r></w:p>"


def _participants_table(payload: MeetingMinutesPayload, t: dict[str, str]) -> str:
    rows = [
        """
        <w:tr>
          <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{}</w:t></w:r></w:p></w:tc>
          <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{}</w:t></w:r></w:p></w:tc>
          <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{}</w:t></w:r></w:p></w:tc>
          <w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{}</w:t></w:r></w:p></w:tc>
        </w:tr>
        """.format(escape(t["name"]), escape(t["department"]), escape(t["absent"]), escape(t["notes"]))
    ]
    participants = payload.participants or []
    if not participants:
        rows.append(
            "<w:tr><w:tc><w:p><w:r><w:t>-</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>-</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>-</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>-</w:t></w:r></w:p></w:tc></w:tr>"
        )
    for participant in participants:
        rows.append(
            "<w:tr>"
            f"<w:tc><w:p><w:r><w:t xml:space=\"preserve\">{escape(participant.name or '')}</w:t></w:r></w:p></w:tc>"
            f"<w:tc><w:p><w:r><w:t xml:space=\"preserve\">{escape(participant.department or '')}</w:t></w:r></w:p></w:tc>"
            f"<w:tc><w:p><w:r><w:t>{escape(t['yes'] if participant.absent else t['no'])}</w:t></w:r></w:p></w:tc>"
            f"<w:tc><w:p><w:r><w:t xml:space=\"preserve\">{escape(participant.notes or '')}</w:t></w:r></w:p></w:tc>"
            "</w:tr>"
        )
    return "<w:tbl>" + "".join(rows) + "</w:tbl>"


def build_meeting_minutes_docx(payload: MeetingMinutesPayload) -> bytes:
    t = TRANSLATIONS[payload.language]
    body_parts = [
        _p(t["document_title"], bold=True),
        _p(f"{t['minutes_title_label']}: {payload.title}"),
        _p(f"{t['project']}: {payload.project_subject}"),
        _p(f"{t['albaran']}: {payload.albaran_number}"),
        _p(f"{t['date']}: {payload.meeting_date}"),
        _p(f"{t['time']}: {payload.start_time} - {payload.end_time}"),
        _p(f"{t['location']}: {payload.location}"),
        _p(f"{t['phase']}: {payload.phase}"),
        _p(""),
        _p(t["participants"], bold=True),
        _participants_table(payload, t),
        _p(""),
        _p(t["topics"], bold=True),
        _p(payload.topics),
        _p(""),
        _p(t["discussion"], bold=True),
        _p(payload.discussion),
        _p(""),
        _p(t["decisions"], bold=True),
        _p(payload.decisions_actions),
        _p(""),
        _p(t["planning"], bold=True),
        _p(payload.planning_next_steps),
        "<w:sectPr/>",
    ]

    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        f"<w:body>{''.join(body_parts)}</w:body></w:document>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("_rels/.rels", RELS_XML)
        zf.writestr("word/document.xml", document_xml)
    return buffer.getvalue()
