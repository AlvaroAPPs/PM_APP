import unittest

import app


class StoppedUnplannedHelpersTests(unittest.TestCase):
    def test_row_class_stopped_takes_precedence(self):
        self.assertEqual(app.stopped_unplanned_row_class(True, True), "row-stopped")

    def test_row_class_unplanned_when_not_stopped(self):
        self.assertEqual(app.stopped_unplanned_row_class(False, True), "row-unplanned")


class IncreasedHoursWithoutProgressTests(unittest.TestCase):
    def test_qualifies_when_hours_increase_and_progress_stays_same(self):
        self.assertTrue(app.qualifies_increased_hours_without_progress(12, 10, 50, 50))

    def test_qualifies_when_hours_increase_and_progress_decreases(self):
        self.assertTrue(app.qualifies_increased_hours_without_progress(12, 10, 45, 50))

    def test_excludes_when_progress_increases(self):
        self.assertFalse(app.qualifies_increased_hours_without_progress(12, 10, 55, 50))

    def test_excludes_when_hours_do_not_increase(self):
        self.assertFalse(app.qualifies_increased_hours_without_progress(10, 10, 50, 50))


if __name__ == "__main__":
    unittest.main()
