import unittest
from datetime import date

import app


TODAY = date(2026, 11, 3)


class KanbanColumnTests(unittest.TestCase):
    def test_open_due_today_goes_to_today(self):
        self.assertEqual(app.kanban_column("OPEN", TODAY, TODAY), "TODAY")

    def test_open_overdue_stays_in_today(self):
        self.assertEqual(app.kanban_column("OPEN", date(2026, 10, 30), TODAY), "TODAY")

    def test_open_future_or_undated_goes_to_todo(self):
        self.assertEqual(app.kanban_column("OPEN", date(2026, 11, 4), TODAY), "TODO")
        self.assertEqual(app.kanban_column("OPEN", None, TODAY), "TODO")

    def test_status_columns_ignore_date(self):
        self.assertEqual(app.kanban_column("IN_PROGRESS", date(2026, 10, 1), TODAY), "IN_PROGRESS")
        self.assertEqual(app.kanban_column("PAUSED", TODAY, TODAY), "WAITING")
        self.assertEqual(app.kanban_column("CLOSED", TODAY, TODAY), "DONE")


class KanbanDaysOverdueTests(unittest.TestCase):
    def test_counts_days_for_past_open_tasks(self):
        self.assertEqual(app.kanban_days_overdue("OPEN", date(2026, 10, 31), TODAY), 3)

    def test_zero_for_today_future_undated_or_closed(self):
        self.assertEqual(app.kanban_days_overdue("OPEN", TODAY, TODAY), 0)
        self.assertEqual(app.kanban_days_overdue("OPEN", None, TODAY), 0)
        self.assertEqual(app.kanban_days_overdue("CLOSED", date(2026, 10, 1), TODAY), 0)


class ProjectColorTests(unittest.TestCase):
    def test_normalize_accepts_hex_and_lowercases(self):
        self.assertEqual(app.normalize_project_color(" #AABBCC "), "#aabbcc")

    def test_normalize_rejects_invalid(self):
        self.assertIsNone(app.normalize_project_color("red"))
        self.assertIsNone(app.normalize_project_color("#abc"))
        self.assertIsNone(app.normalize_project_color(None))

    def test_resolve_uses_stored_color_or_palette(self):
        self.assertEqual(app.resolve_project_color(5, "#123456"), "#123456")
        palette = app.PROJECT_COLOR_PALETTE
        self.assertEqual(app.resolve_project_color(5, None), palette[5 % len(palette)])
        self.assertEqual(app.resolve_project_color(5, "bad"), palette[5 % len(palette)])


if __name__ == "__main__":
    unittest.main()
