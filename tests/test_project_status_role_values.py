import unittest

import app


class ProjectStatusRoleValuesTests(unittest.TestCase):
    def test_ots_distribution_and_deviation_drive_role_values(self):
        assigned, consumed, deviation = app.project_status_role_values(
            {
                "ordered_total": 400,
                "real_hours": 200,
                "dist_pm": 20,
                "dist_c": 0.5,
                "dist_e": 30,
                "deviation_pmd": 10,
                "deviation_cd": -0.2,
                "deviation_ed": 0,
            }
        )

        self.assertEqual(assigned, {"pm": 80.0, "consultant": 200.0, "technician": 120.0})
        self.assertEqual(deviation, {"pm": 10.0, "consultant": -20.0, "technician": 0.0})
        self.assertEqual(consumed, {"pm": 36.0, "consultant": 120.0, "technician": 60.0})

    def test_missing_ots_role_values_are_safe(self):
        assigned, consumed, deviation = app.project_status_role_values({"real_hours": 200})

        expected = {"pm": 0.0, "consultant": 0.0, "technician": 0.0}
        self.assertEqual(assigned, expected)
        self.assertEqual(consumed, expected)
        self.assertEqual(deviation, expected)


if __name__ == "__main__":
    unittest.main()
