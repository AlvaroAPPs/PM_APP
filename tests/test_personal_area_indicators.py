import unittest

import app


class PersonalAreaIndicatorRulesTests(unittest.TestCase):
    def test_productivity_red_when_theoretical_gradient_is_lower(self):
        weekly = [
            {"real_hours": 10, "horas_teoricas": 12},
            {"real_hours": 16, "horas_teoricas": 15},
        ]
        self.assertEqual(app.compute_productivity_indicator(weekly), "red")

    def test_productivity_green_when_theoretical_gradient_equal_or_higher(self):
        weekly_equal = [
            {"real_hours": 10, "horas_teoricas": 12},
            {"real_hours": 15, "horas_teoricas": 17},
        ]
        weekly_higher = [
            {"real_hours": 10, "horas_teoricas": 12},
            {"real_hours": 13, "horas_teoricas": 18},
        ]
        self.assertEqual(app.compute_productivity_indicator(weekly_equal), "green")
        self.assertEqual(app.compute_productivity_indicator(weekly_higher), "green")

    def test_deviation_boundary(self):
        self.assertEqual(app.compute_deviation_indicator([{"desviacion_pct": 0.5}]), "red")
        self.assertEqual(app.compute_deviation_indicator([{"desviacion_pct": 0}]), "green")
        self.assertEqual(app.compute_deviation_indicator([{"desviacion_pct": -0.1}]), "green")

    def test_phase_indicator_red_when_latest_week_changes(self):
        phases = [
            {"date_kickoff": "2026-01-01", "date_design": "2026-01-08", "date_validation": None, "date_golive": None, "date_reception": None, "date_end": None},
            {"date_kickoff": "2026-01-01", "date_design": "2026-01-10", "date_validation": None, "date_golive": None, "date_reception": None, "date_end": None},
        ]
        self.assertEqual(app.compute_phase_indicator(phases), "red")

    def test_phase_indicator_green_when_latest_week_has_no_changes(self):
        phases = [
            {"date_kickoff": "2026-01-01", "date_design": "2026-01-08", "date_validation": None, "date_golive": None, "date_reception": None, "date_end": None},
            {"date_kickoff": "2026-01-01", "date_design": "2026-01-08", "date_validation": None, "date_golive": None, "date_reception": None, "date_end": None},
        ]
        self.assertEqual(app.compute_phase_indicator(phases), "green")

    def test_aggregate_indicator_rule(self):
        self.assertEqual(app.compute_area_personal_indicator_status("green", "green", "green"), "green")
        self.assertEqual(app.compute_area_personal_indicator_status("red", "green", "green"), "orange")
        self.assertEqual(app.compute_area_personal_indicator_status("red", "red", "green"), "red")
        self.assertEqual(app.compute_area_personal_indicator_status("red", "red", "red"), "red")


if __name__ == "__main__":
    unittest.main()
