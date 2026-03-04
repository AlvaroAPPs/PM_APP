import unittest

import app


class StoppedUnplannedHelpersTests(unittest.TestCase):
    def test_row_class_stopped_takes_precedence(self):
        self.assertEqual(app.stopped_unplanned_row_class(True, True), "row-stopped")

    def test_row_class_unplanned_when_not_stopped(self):
        self.assertEqual(app.stopped_unplanned_row_class(False, True), "row-unplanned")


if __name__ == "__main__":
    unittest.main()
