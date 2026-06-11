import unittest

import app


class ProjectStatusRoleValuesTests(unittest.TestCase):
    def test_ots_values_drive_rounded_role_hours(self):
        assigned, consumed, deviation, percentages = app.project_status_role_values(
            {
                "ordered_total": 101,
                "real_hours": 200,
                "dist_pm": 20,
                "dist_c": 0.5,
                "dist_e": 30,
                "deviation_pmd": 10,
                "deviation_cd": -0.2,
                "deviation_ed": 0,
            }
        )

        self.assertEqual(assigned, {"pm": 20.0, "consultant": 50.0, "technician": 31.0})
        self.assertEqual(sum(assigned.values()), 101.0)
        self.assertEqual(percentages, {"pm": 20.0, "consultant": 50.0, "technician": 30.0})
        self.assertEqual(deviation, {"total": 0.0, "pm": 10.0, "consultant": -20.0, "technician": 0.0})
        self.assertEqual(consumed, {"pm": 33.25, "consultant": 111.25, "technician": 55.5})
        self.assertEqual(sum(consumed.values()), 200.0)
        self.assertTrue(all((hours * 4).is_integer() for hours in consumed.values()))

    def test_assigned_rounding_prioritizes_technician_and_keeps_pm_rounded_down(self):
        assigned, _, _, _ = app.project_status_role_values(
            {"ordered_total": 10, "dist_pm": 34, "dist_c": 33, "dist_e": 33}
        )

        self.assertEqual(assigned, {"pm": 3.0, "consultant": 3.0, "technician": 4.0})

    def test_missing_ots_role_values_are_safe(self):
        assigned, consumed, deviation, percentages = app.project_status_role_values({"real_hours": 200})

        expected = {"pm": 0.0, "consultant": 0.0, "technician": 0.0}
        self.assertEqual(assigned, expected)
        self.assertEqual(consumed, expected)
        self.assertEqual(deviation, {"total": 0.0, **expected})
        self.assertEqual(percentages, expected)

    def test_progress_and_total_deviation_support_percentages_and_ratios(self):
        progress = app.project_status_progress_values(
            {"progress_w": 75.123, "progress_pm": 0.5, "progress_c": 25, "progress_e": 0.33333}
        )
        _, _, deviation, _ = app.project_status_role_values({"deviation_td": -0.12555})

        self.assertEqual(progress, {"total": 75.12, "pm": 50.0, "consultant": 25.0, "technician": 33.33})
        self.assertEqual(deviation["total"], -12.55)


if __name__ == "__main__":
    unittest.main()
