import unittest
from fastapi.testclient import TestClient

import app


class FakeCursor:
    def __init__(self):
        self._result = []
        self._idx = 0
        self.description = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        q = " ".join(query.split())
        if "SELECT id, project_code, project_name, client, team, project_manager, consultant FROM projects" in q:
            self._result = [(1, "P-001", "Proyecto Demo", "Cliente Demo", "Equipo A", "PM Demo", "NaN")]
            self.description = [("id",), ("project_code",), ("project_name",), ("client",), ("team",), ("project_manager",), ("consultant",)]
        elif "SELECT * FROM project_snapshot" in q and "LIMIT 1" in q:
            self._result = [(
                1,
                1,
                2026,
                6,
                None,
                45.0,
                100.0,
                None,
                40.0,
                10.0,
                "Comentario principal",
            )]
            self.description = [
                ("id",),
                ("project_id",),
                ("snapshot_year",),
                ("snapshot_week",),
                ("snapshot_at",),
                ("progress_w",),
                ("ordered_total",),
                ("horas_teoricas",),
                ("real_hours",),
                ("desviacion_pct",),
                ("comments",),
            ]
        elif "SELECT snapshot_year, snapshot_week, progress_w, desviacion_pct, real_hours, horas_teoricas FROM project_snapshot" in q:
            self._result = [
                (2026, 5, 30.0, 5.0, 20.0, 18.0),
                (2026, 6, 45.0, 10.0, 40.0, 35.0),
            ]
        elif "SELECT snapshot_year, snapshot_week, date_kickoff, date_design, date_validation, date_golive, date_reception, date_end FROM project_snapshot" in q:
            self._result = [
                (2026, 6, "2026-01-10", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01", "2026-06-01")
            ]
        elif "SELECT comments FROM project_snapshot" in q:
            self._result = [("Comentario principal",)]
        elif "ADD COLUMN IF NOT EXISTS comments TEXT" in q:
            self._result = []
        else:
            raise AssertionError(f"Unexpected query: {q}")
        self._idx = 0

    def fetchone(self):
        if self._idx >= len(self._result):
            return None
        row = self._result[self._idx]
        self._idx += 1
        return row

    def fetchall(self):
        return list(self._result)


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor()

    def commit(self):
        return None


class PdfExportTests(unittest.TestCase):
    def test_build_snapshot_report_pdf_contains_markers(self):
        payload = {
            "project": {
                "project_name": "Proyecto Demo",
                "project_code": "P-001",
                "client": "Cliente Demo",
                "team": "Equipo A",
                "project_manager": "PM Demo",
                "consultant": "NaN",
            },
            "latest": {
                "snapshot_year": 2026,
                "snapshot_week": 6,
                "progress_w": 45.0,
                "ordered_total": 100.0,
                "horas_teoricas": 35.0,
                "real_hours": 40.0,
                "desviacion_pct": 10.0,
            },
            "weekly": [
                {"progress_w": 30.0, "desviacion_pct": 5.0, "real_hours": 20.0, "horas_teoricas": 18.0},
                {"progress_w": 45.0, "desviacion_pct": 10.0, "real_hours": 40.0, "horas_teoricas": 35.0},
            ],
            "phases": [{
                "date_kickoff": "2026-01-10",
                "date_design": "2026-02-01",
                "date_validation": "2026-03-01",
                "date_golive": "2026-04-01",
                "date_reception": "2026-05-01",
                "date_end": "2026-06-01",
            }],
            "comment": "Comentario principal",
            "indicators": {"productivity": "green", "deviation": "amber", "phase": "orange"},
        }

        pdf = app.build_snapshot_report_pdf(payload)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"Proyecto Demo", pdf)
        self.assertIn(b"2026-W06", pdf)
        self.assertIn(b"Horas proyecto", pdf)

    def test_pdf_endpoint_returns_pdf_mime(self):
        original_connect = app.psycopg.connect
        app.psycopg.connect = lambda *args, **kwargs: FakeConn()
        try:
            client = TestClient(app.app)
            res = client.get("/projects/P-001/report.pdf")
        finally:
            app.psycopg.connect = original_connect

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("content-type"), "application/pdf")
        self.assertIn(b"Proyecto Demo", res.content)
        self.assertIn(b"2026-W06", res.content)
        self.assertIn(b"Avance", res.content)


if __name__ == "__main__":
    unittest.main()
