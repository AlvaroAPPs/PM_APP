import unittest

import app


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

    def test_progress_and_total_deviation_support_percentages_and_ratios(self):
        progress = app.project_status_progress_values(
            {"progress_w": 75.123, "progress_pm": 0.5, "progress_c": 25, "progress_e": 0.33333}
        )
        _, _, deviation, _ = app.project_status_role_values({"deviation_td": -0.12555})

        self.assertEqual(progress, {"total": 75.12, "pm": 50.0, "consultant": 25.0, "technician": 33.33})
        self.assertEqual(deviation["total"], -12.55)


if __name__ == "__main__":
    unittest.main()
