import unittest

import app


def reference(progress, excel=None, manual=False, review=None):
    return {
        "progress_pm": progress,
        "excel_progress_pm": excel,
        "manual_progress_pm": manual,
        "review_progress_pm": review,
    }


class ResolveRoleProgressTests(unittest.TestCase):
    def test_without_previous_snapshot_uses_excel(self):
        result = app.resolve_role_progress({"pm": 40}, None)["pm"]
        self.assertEqual(result, {"excel": 40.0, "effective": 40.0, "manual": False, "review": None})

    def test_unchanged_excel_keeps_manual_value(self):
        result = app.resolve_role_progress({"pm": 40}, reference(55, excel=40, manual=True))["pm"]
        self.assertEqual(result["effective"], 55.0)
        self.assertTrue(result["manual"])
        self.assertIsNone(result["review"])

    def test_increased_excel_replaces_manual_value(self):
        result = app.resolve_role_progress({"pm": 45}, reference(55, excel=40, manual=True))["pm"]
        self.assertEqual(result["effective"], 45.0)
        self.assertFalse(result["manual"])
        self.assertIsNone(result["review"])

    def test_decreased_excel_keeps_previous_value_and_flags_review(self):
        result = app.resolve_role_progress({"pm": 30}, reference(55, excel=40, manual=True))["pm"]
        self.assertEqual(result["effective"], 55.0)
        self.assertTrue(result["manual"])
        self.assertEqual(result["review"], 30.0)

    def test_pending_review_persists_while_excel_unchanged(self):
        result = app.resolve_role_progress({"pm": 30}, reference(55, excel=30, manual=True, review=30))["pm"]
        self.assertEqual(result["effective"], 55.0)
        self.assertEqual(result["review"], 30.0)

    def test_legacy_snapshot_without_excel_value_compares_with_stored_progress(self):
        result = app.resolve_role_progress({"pm": 35}, reference(40))["pm"]
        self.assertEqual(result["effective"], 40.0)
        self.assertEqual(result["review"], 35.0)

    def test_missing_excel_value_is_skipped(self):
        self.assertEqual(app.resolve_role_progress({"pm": None}, reference(40)), {})


class RecomputeSnapshotProgressTests(unittest.TestCase):
    def test_recomputes_weighted_progress_and_deviation(self):
        fields = {
            "dist_pm": 20, "dist_c": 50, "dist_e": 30,
            "progress_pm": 50, "progress_c": 40, "progress_e": 100,
            "ordered_total": 100, "real_hours": 60,
        }
        app._recompute_snapshot_progress(fields)
        self.assertAlmostEqual(fields["progress_w"], 60.0)
        self.assertAlmostEqual(fields["horas_teoricas"], 60.0)
        self.assertAlmostEqual(fields["desviacion_h"], 0.0)


if __name__ == "__main__":
    unittest.main()
