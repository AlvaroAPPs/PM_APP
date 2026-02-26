import unittest

import app


class NotesAndChecklistHelpersTests(unittest.TestCase):
    def test_note_payload_defaults_to_general_and_null_project(self):
        payload = app.NoteCreateIn(title="Note", date="2026-01-01")
        project_id, title, comment, note_type, parsed_date, checklist = app._normalize_note_payload(payload)
        self.assertIsNone(project_id)
        self.assertEqual(title, "Note")
        self.assertIsNone(comment)
        self.assertEqual(note_type, "GENERAL")
        self.assertEqual(parsed_date.isoformat(), "2026-01-01")
        self.assertEqual(checklist, [])

    def test_note_payload_accepts_reunion_type_and_project(self):
        payload = app.NoteCreateIn(title="Reunión", date="2026-01-01", projectId=7, type="Reunion")
        project_id, _, _, note_type, _, _ = app._normalize_note_payload(payload)
        self.assertEqual(project_id, 7)
        self.assertEqual(note_type, "REUNION")

    def test_compose_and_split_subtasks_roundtrip(self):
        text = app._compose_description_subtasks(
            "Descripción",
            [{"text": "A", "done": False}, {"text": "B", "done": True}],
        )
        description, subtasks = app._split_description_subtasks(text)
        self.assertEqual(description, "Descripción")
        self.assertEqual(subtasks, [{"text": "A", "done": False}, {"text": "B", "done": True}])


if __name__ == "__main__":
    unittest.main()
