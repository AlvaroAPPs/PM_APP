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
            document_xml = docx.read("word/document.xml").decode("utf-8")
            embedded_logo = docx.read("word/media/mecalux_logo.jpg")

        self.assertIn("word/media/mecalux_logo.jpg", names)
        self.assertNotIn("word/media/mecalux_logo.svg", names)
        self.assertEqual(embedded_logo, logo_asset)
        self.assertIn('Extension="jpg" ContentType="image/jpeg"', content_types)
        self.assertIn('Target="media/mecalux_logo.jpg"', document_rels)
        self.assertIn('name="mecalux_logo.jpg"', document_xml)


if __name__ == "__main__":
    unittest.main()
