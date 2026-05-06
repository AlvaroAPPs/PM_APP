import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from meeting_minutes.docx_service import build_meeting_minutes_docx
from meeting_minutes.models import MeetingMinutesPayload


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


if __name__ == "__main__":
    unittest.main()
