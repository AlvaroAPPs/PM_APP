import unittest
from unittest.mock import patch

import app


class FakeStatusRoleCursor:
    def __init__(self):
        self.description = [(name,) for name in (
            "id", "ordered_total", "real_hours", "dist_pm", "dist_c", "dist_e",
            "progress_pm", "progress_c", "progress_e", "deviation_pmd", "deviation_cd",
            "deviation_ed", "design_ok", "validation_ok", "progress_w", "horas_teoricas",
            "desviacion_pct", "real_hours_delta",
        )]
        self.saved = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, payload):
        if "UPDATE project_snapshot" in query:
            self.saved = payload

    def fetchall(self):
        return [
            (10, 100, 40, 20, 50, 30, 50, 40, 100, 0, 0, 0, True, True, 55, 55, -27.27, 10),
            (9, 100, 30, 20, 50, 30, 40, 30, 90, 0, 0, 0, True, True, 45, 45, -33.33, 8),
        ]


class FakeStatusRoleConnection:
    def __init__(self):
        self.cursor_instance = FakeStatusRoleCursor()
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True


class ProjectStatusRoleValuesTests(unittest.TestCase):
    def test_ots_inverse_deviation_drives_normalized_role_hours(self):
        assigned, consumed, deviation, percentages = app.project_status_role_values(
            {
                "ordered_total": 100,
                "real_hours": 50,
                "dist_pm": 20,
                "dist_c": 50,
                "dist_e": 30,
                "progress_pm": 10,
                "progress_c": 50,
                "progress_e": 80,
                "deviation_pmd": 10,
                "deviation_cd": -20,
                "deviation_ed": 0,
                "design_ok": True,
                "validation_ok": True,
            }
        )

        self.assertEqual(assigned, {"pm": 20.0, "consultant": 50.0, "technician": 30.0})
        self.assertEqual(percentages, {"pm": 20.0, "consultant": 50.0, "technician": 30.0})
        self.assertEqual(deviation, {"total": 0.0, "pm": 10.0, "consultant": -20.0, "technician": 0.0})
        self.assertEqual(consumed, {"pm": 1.0, "consultant": 28.0, "technician": 21.0})
        self.assertEqual(sum(consumed.values()), 50.0)
        self.assertTrue(all((hours * 4).is_integer() for hours in consumed.values()))

    def test_inverse_deviation_uses_design_and_validation_stages(self):
        self.assertEqual(app._deviation_projection_stage(80, False, True), 20.0)
        self.assertEqual(app._deviation_projection_stage(10, True, True), 20.0)
        self.assertEqual(app._deviation_projection_stage(80, True, False), 70.0)
        self.assertEqual(app._deviation_projection_stage(50, True, True), 70.0)
        self.assertEqual(app._deviation_projection_stage(80, True, True), 100.0)

    def test_assigned_rounding_prioritizes_technician_and_keeps_pm_rounded_down(self):
        assigned, _, _, _ = app.project_status_role_values(
            {"ordered_total": 10, "dist_pm": 34, "dist_c": 33, "dist_e": 33}
        )

        self.assertEqual(assigned, {"pm": 3.0, "consultant": 3.0, "technician": 4.0})

    def test_missing_progress_falls_back_to_distribution_and_matches_real_hours(self):
        assigned, consumed, _, _ = app.project_status_role_values(
            {"ordered_total": 100, "real_hours": 20, "dist_pm": 20, "dist_c": 50, "dist_e": 30}
        )

        self.assertEqual(assigned, {"pm": 20.0, "consultant": 50.0, "technician": 30.0})
        self.assertEqual(consumed, {"pm": 4.0, "consultant": 10.0, "technician": 6.0})

    def test_missing_ots_role_values_are_safe(self):
        assigned, consumed, deviation, percentages = app.project_status_role_values({"real_hours": 200})

        expected = {"pm": 0.0, "consultant": 0.0, "technician": 0.0}
        self.assertEqual(assigned, expected)
        self.assertEqual(consumed, expected)
        self.assertEqual(deviation, {"total": 0.0, **expected})
        self.assertEqual(percentages, expected)


    def test_consumed_role_increment_compares_with_previous_snapshot(self):
        increment = app.project_status_consumed_role_increment(
            {"pm": 12.25, "consultant": 30.5, "technician": 20.0},
            {"pm": 10.0, "consultant": 31.0, "technician": 15.25},
        )

        self.assertEqual(increment, {"pm": 2.25, "consultant": -0.5, "technician": 4.75})

    def test_consumed_role_increment_is_zero_without_previous_snapshot(self):
        increment = app.project_status_consumed_role_increment(
            {"pm": 12.25, "consultant": 30.5, "technician": 20.0}, None
        )

        self.assertEqual(increment, {"pm": 0.0, "consultant": 0.0, "technician": 0.0})

    def test_role_edits_recalculate_weighted_progress_and_dependent_values(self):
        latest = {
            "ordered_total": 100,
            "real_hours": 40,
            "dist_pm": 20,
            "dist_c": 50,
            "dist_e": 30,
            "progress_pm": 50,
            "progress_c": 40,
            "progress_e": 100,
            "deviation_pmd": 0,
            "deviation_cd": 0,
            "deviation_ed": 0,
            "design_ok": True,
            "validation_ok": True,
        }
        payload = app.ProjectStatusRoleEditIn(
            progress_pm=60,
            progress_consultant=50,
            progress_technician=80,
            percentage_pm=25,
            percentage_consultant=45,
            percentage_technician=30,
        )

        values = app.project_status_role_edit_values(latest, payload)

        self.assertEqual(values["progress_w"], 61.5)
        self.assertEqual(values["horas_teoricas"], 61.5)
        self.assertAlmostEqual(values["desviacion_h"], -21.5)
        self.assertAlmostEqual(values["desviacion_pct"], -34.959349593495936)
        expected_total_deviation = (
            0.25 * values["deviation_pmd"]
            + 0.45 * values["deviation_cd"]
            + 0.30 * values["deviation_ed"]
        )
        self.assertAlmostEqual(values["deviation_td"], expected_total_deviation)
        self.assertAlmostEqual(values["deviation_td"], 27.575)
        self.assertEqual(values["dist_pm"], 0.25)
        self.assertEqual(values["progress_c"], 50)

    def test_role_edits_are_persisted_to_latest_snapshot(self):
        connection = FakeStatusRoleConnection()
        payload = app.ProjectStatusRoleEditIn(
            progress_pm=60,
            progress_consultant=50,
            progress_technician=80,
            percentage_pm=25,
            percentage_consultant=45,
            percentage_technician=30,
        )

        with patch.object(app.psycopg, "connect", return_value=connection):
            response = app.update_project_status_role_values(1, payload)

        self.assertEqual(response, {"status": "ok"})
        self.assertTrue(connection.committed)
        self.assertEqual(connection.cursor_instance.saved["snapshot_id"], 10)
        self.assertEqual(connection.cursor_instance.saved["progress_w"], 61.5)
        self.assertEqual(connection.cursor_instance.saved["dist_pm"], 0.25)

    def test_role_edits_require_percentages_to_total_100(self):
        payload = app.ProjectStatusRoleEditIn(
            progress_pm=50,
            progress_consultant=50,
            progress_technician=50,
            percentage_pm=20,
            percentage_consultant=20,
            percentage_technician=20,
        )

        with self.assertRaisesRegex(ValueError, "must total 100"):
            app.project_status_role_edit_values({}, payload)

    def test_pm_deviation_uses_role_progress_weight_and_consumed_hours(self):
        deviation = app.project_status_pm_deviation(
            {
                "ordered_total": 100,
                "dist_pm": 20,
                "dist_c": 50,
                "dist_e": 30,
                "progress_pm": 50,
                "progress_c": 40,
                "progress_e": 100,
            },
            {"pm": 8.0, "consultant": 25.0, "technician": 24.0},
        )

        self.assertEqual(deviation, {"pm": 20.0, "consultant": -25.0, "technician": 20.0, "total": 5.0})

    def test_pm_deviation_is_safe_when_theoretical_hours_are_missing(self):
        deviation = app.project_status_pm_deviation({}, {"pm": 2.0, "consultant": 3.0, "technician": 4.0})

        self.assertEqual(deviation, {"pm": 0.0, "consultant": 0.0, "technician": 0.0, "total": 0.0})

    def test_progress_and_total_deviation_use_excel_percentage_values(self):
        progress = app.project_status_progress_values(
            {"progress_w": 75.123, "progress_pm": 1, "progress_c": 25, "progress_e": 33.333}
        )
        _, _, deviation, _ = app.project_status_role_values({"deviation_td": -1.2555})

        self.assertEqual(progress, {"total": 75.12, "pm": 1.0, "consultant": 25.0, "technician": 33.33})
        self.assertEqual(deviation["total"], -1.26)


if __name__ == "__main__":
    unittest.main()
