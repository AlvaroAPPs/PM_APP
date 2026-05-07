import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from meeting_minutes.docx_service import build_meeting_minutes_docx, build_meeting_minutes_filename
from meeting_minutes.models import MeetingMinutesPayload, MeetingParticipant, MeetingTopicBlock
from meeting_minutes import router as meeting_minutes_router


class MeetingMinutesDocxTests(unittest.TestCase):
    def test_header_uses_jpg_logo_asset(self):
        docx_bytes = build_meeting_minutes_docx(MeetingMinutesPayload(title="Demo"), "FR-SW-0406 Proyecto BBDD")
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
        self.assertIn("FR-SW-0406 Proyecto BBDD", header_xml)
        self.assertIn("Fecha modificación", header_xml)
        self.assertNotIn("Versión", header_xml)
        self.assertNotIn(">1.0<", header_xml)

    def test_document_body_formats_topics_and_approval_notice(self):
        payload = MeetingMinutesPayload(
            title="Acta demo",
            albaran_number="OTRO-ALBARAN",
            meeting_date="2026-03-31",
            start_time="11:30",
            end_time="12:30",
            project_subject="JIM",
            phase="Desarrollo",
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
        self.assertNotIn("Título del acta", document_xml)
        self.assertIn("Asunto/Proyecto", document_xml)
        self.assertIn("JIM", document_xml)
        self.assertIn("2026-03-31", document_xml)
        self.assertIn("11:30 - 12:30", document_xml)
        self.assertIn('<w:tcMar><w:top w:w="80" w:type="dxa"/><w:left w:w="100" w:type="dxa"/>', document_xml)
        self.assertIn("Objetivos de la reunión y temas tratados", document_xml)
        self.assertIn('<w:ind w:left="720" w:hanging="360"/>', document_xml)
        self.assertIn('<w:t xml:space="preserve">1) </w:t>', document_xml)
        self.assertIn("Tema A", document_xml)
        self.assertIn('<w:t xml:space="preserve">2) </w:t>', document_xml)
        self.assertIn("Tema B", document_xml)
        self.assertNotIn('<w:rPr><w:b/></w:rPr><w:t xml:space="preserve">1) </w:t>', document_xml)
        self.assertNotIn('<w:t xml:space="preserve">Tema A</w:t></w:r></w:p><w:p/><w:p><w:pPr><w:ind w:left="720"', document_xml)
        self.assertNotIn("Detalle de la discusión", document_xml)
        self.assertIn('<w:rPr><w:b/><w:u w:val="single"/></w:rPr><w:t xml:space="preserve">Tema A</w:t>', document_xml)
        self.assertIn(
            '<w:t xml:space="preserve">Tema A</w:t></w:r></w:p><w:p><w:r><w:t xml:space="preserve">Resumen A</w:t>',
            document_xml,
        )
        self.assertNotIn(
            '<w:t xml:space="preserve">Tema A</w:t></w:r></w:p><w:p/><w:p><w:r><w:t xml:space="preserve">Resumen A</w:t>',
            document_xml,
        )
        self.assertIn('<w:rPr><w:b/><w:i/></w:rPr><w:t xml:space="preserve">Decisiones / Acciones</w:t>', document_xml)
        self.assertIn('<w:rPr><w:b/><w:i/></w:rPr><w:t xml:space="preserve">Planificación / Próximos pasos</w:t>', document_xml)
        self.assertIn('w:color="808080"/></w:pBdr></w:pPr></w:p><w:p><w:r><w:rPr><w:b/><w:u w:val="single"/></w:rPr><w:t xml:space="preserve">Tema B</w:t>', document_xml)
        self.assertIn("Si no hay ningún comentario o anotación", document_xml)
        self.assertGreaterEqual(document_xml.count('<w:bottom w:val="single" w:sz="8"'), 3)

    def test_filename_uses_fixed_prefix_date_project_and_language(self):
        payload = MeetingMinutesPayload(
            language="es",
            albaran_number="OTRO-ALBARAN",
            meeting_date="2026-03-31",
            project_subject="JIM",
        )

        filename = build_meeting_minutes_filename(payload)

        self.assertEqual(filename, "FR-SW-0406_20260331_JIM_Meeting_Minutes_ES.docx")

    def test_export_details_feed_header_and_filename_project_name(self):
        payload = MeetingMinutesPayload(
            language="es",
            project_id=7,
            albaran_number="FR-SW-0406",
            meeting_date="2026-03-31",
            project_subject="Formulario Local",
        )

        class FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, query, params=None):
                self.query = " ".join(query.split())
                self.params = params

            def fetchone(self):
                return ("FR-SW-0406", "Proyecto BBDD")

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return FakeCursor()

        original_connect = meeting_minutes_router.psycopg.connect
        meeting_minutes_router.psycopg.connect = lambda *args, **kwargs: FakeConn()
        try:
            project_code, project_name = meeting_minutes_router._project_export_details(payload)
        finally:
            meeting_minutes_router.psycopg.connect = original_connect

        filename = build_meeting_minutes_filename(payload, project_name)
        header_label = meeting_minutes_router._project_header_label(project_code, project_name)

        self.assertEqual(project_code, "FR-SW-0406")
        self.assertEqual(project_name, "Proyecto BBDD")
        self.assertEqual(header_label, "FR-SW-0406 Proyecto BBDD")
        self.assertEqual(filename, "FR-SW-0406_20260331_Proyecto_BBDD_Meeting_Minutes_ES.docx")


if __name__ == "__main__":
    unittest.main()
