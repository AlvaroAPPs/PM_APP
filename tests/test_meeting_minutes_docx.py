import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from meeting_minutes.docx_service import build_meeting_minutes_docx
from meeting_minutes.models import MeetingMinutesPayload, MeetingParticipant, MeetingTopicBlock


class MeetingMinutesDocxTests(unittest.TestCase):
    def test_header_uses_jpg_logo_asset(self):
        docx_bytes = build_meeting_minutes_docx(MeetingMinutesPayload(title="Demo"))
        logo_asset = Path("meeting_minutes/assets/mecalux_logo.jpg").read_bytes()

        with zipfile.ZipFile(BytesIO(docx_bytes)) as docx:
            names = docx.namelist()
            content_types = docx.read("[Content_Types].xml").decode("utf-8")
            document_rels = docx.read("word/_rels/document.xml.rels").decode("utf-8")
            header_rels = docx.read("word/_rels/header1.xml.rels").decode("utf-8")
            document_xml = docx.read("word/document.xml").decode("utf-8")
            header_xml = docx.read("word/header1.xml").decode("utf-8")
            embedded_logo = docx.read("word/media/mecalux_logo.jpg")

        self.assertIn("word/header1.xml", names)
        self.assertIn("word/_rels/header1.xml.rels", names)
        self.assertIn("word/media/mecalux_logo.jpg", names)
        self.assertNotIn("word/media/mecalux_logo.svg", names)
        self.assertEqual(embedded_logo, logo_asset)
        self.assertIn('Extension="jpg" ContentType="image/jpeg"', content_types)
        self.assertIn('PartName="/word/header1.xml"', content_types)
        self.assertIn('Target="header1.xml"', document_rels)
        self.assertIn('Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header"', document_rels)
        self.assertIn('Target="media/mecalux_logo.jpg"', header_rels)
        self.assertIn('<w:headerReference w:type="default" r:id="rIdHeader"/>', document_xml)
        self.assertNotIn('name="mecalux_logo.jpg"', document_xml)
        self.assertIn('name="mecalux_logo.jpg"', header_xml)
        self.assertIn('<w:vAlign w:val="center"/>', header_xml)

    def test_document_body_formats_topics_and_approval_notice(self):
        payload = MeetingMinutesPayload(
            title="Acta demo",
            participants=[MeetingParticipant(name="Ana")],
            topic_blocks=[
                MeetingTopicBlock(
                    topic="Tema A",
                    discussion="Resumen A",
                    decisions_actions="Acción A",
                    planning_next_steps="Plan A",
                ),
                MeetingTopicBlock(topic="Tema B", discussion="Resumen B"),
            ],
        )
        docx_bytes = build_meeting_minutes_docx(payload)

        with zipfile.ZipFile(BytesIO(docx_bytes)) as docx:
            document_xml = docx.read("word/document.xml").decode("utf-8")

        self.assertIn("<w:body><w:p/><w:tbl", document_xml)
        self.assertIn("Objetivos de la reunión y temas tratados", document_xml)
        self.assertIn("1) ", document_xml)
        self.assertIn("Tema A", document_xml)
        self.assertIn("2) ", document_xml)
        self.assertIn("Tema B", document_xml)
        self.assertNotIn("Detalle de la discusión", document_xml)
        self.assertIn('<w:rPr><w:b/><w:u w:val="single"/></w:rPr><w:t xml:space="preserve">Tema A</w:t>', document_xml)
        self.assertIn('<w:rPr><w:b/><w:i/></w:rPr><w:t xml:space="preserve">Decisiones / Acciones</w:t>', document_xml)
        self.assertIn('<w:rPr><w:b/><w:i/></w:rPr><w:t xml:space="preserve">Planificación / Próximos pasos</w:t>', document_xml)
        self.assertIn("Si no hay ningún comentario o anotación", document_xml)
        self.assertGreaterEqual(document_xml.count('<w:bottom w:val="single" w:sz="8"'), 2)


if __name__ == "__main__":
    unittest.main()
