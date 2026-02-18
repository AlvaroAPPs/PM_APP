import unittest

from fastapi.testclient import TestClient

import app


class _SingleRowFrame:
    def __init__(self, row):
        self.row = row

    def iterrows(self):
        yield 0, self.row


class FakeCursor:
    def __init__(self, state):
        self.state = state
        self._result = []
        self._idx = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        q = " ".join(query.split())
        if "INSERT INTO import_file" in q:
            self._result = [(999,)]
        elif "SELECT COALESCE(is_historical, FALSE) FROM projects WHERE project_code = %s" in q:
            code = params[0]
            project = self.state["projects"].get(code)
            self._result = [(bool(project["is_historical"]),)] if project else []
        elif "SELECT 1 FROM projects_historical WHERE project_code = %s" in q:
            code = params[0]
            self._result = [(1,)] if code in self.state["historicals"] else []
        else:
            raise AssertionError(f"Unexpected query: {q}")
        self._idx = 0

    def fetchone(self):
        if self._idx >= len(self._result):
            return None
        row = self._result[self._idx]
        self._idx += 1
        return row


class FakeConn:
    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self.state)

    def commit(self):
        return None


class ImportAllBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.original_connect = app.psycopg.connect
        self.original_ensure = app.ensure_historical_storage
        self.original_read = app.read_and_normalize_excel
        self.original_map = app.map_row
        self.original_upsert_project = app.upsert_project
        self.original_compute_deltas = app.compute_deltas
        self.original_upsert_snapshot = app.upsert_snapshot
        self.original_move = app.move_project_to_historical
        self.original_restore = app.restore_project_from_historical

        self.state = {
            "projects": {},
            "historicals": set(),
            "upsert_calls": 0,
            "move_calls": 0,
            "restore_calls": 0,
            "snapshot_calls": 0,
        }

        app.psycopg.connect = lambda *args, **kwargs: FakeConn(self.state)
        app.ensure_historical_storage = lambda cur: None
        app.read_and_normalize_excel = lambda path, sheet: _SingleRowFrame({"row": 1})
        app.compute_deltas = lambda cur, pid, year, week, fields: fields
        app.upsert_snapshot = self._fake_upsert_snapshot
        app.move_project_to_historical = self._fake_move_to_historical
        app.restore_project_from_historical = self._fake_restore_from_historical

    def tearDown(self):
        app.psycopg.connect = self.original_connect
        app.ensure_historical_storage = self.original_ensure
        app.read_and_normalize_excel = self.original_read
        app.map_row = self.original_map
        app.upsert_project = self.original_upsert_project
        app.compute_deltas = self.original_compute_deltas
        app.upsert_snapshot = self.original_upsert_snapshot
        app.move_project_to_historical = self.original_move
        app.restore_project_from_historical = self.original_restore

    def _fake_upsert_project(self, cur, project_fields):
        self.state["upsert_calls"] += 1
        code = project_fields["project_code"]
        existing = self.state["projects"].get(code)
        if existing:
            return existing["id"]
        pid = len(self.state["projects"]) + 1
        self.state["projects"][code] = {"id": pid, "is_historical": False}
        return pid

    def _fake_move_to_historical(self, cur, project_id, project_fields, moved_to_historical_week, filename):
        self.state["move_calls"] += 1

    def _fake_restore_from_historical(self, cur, project_code):
        self.state["restore_calls"] += 1

    def _fake_upsert_snapshot(self, cur, pid, import_file_id, snapshot_year, snapshot_week, snapshot_fields):
        self.state["snapshot_calls"] += 1

    def _post_all_import(self):
        client = TestClient(app.app)
        return client.post(
            "/imports",
            data={"snapshot_year": "2026", "snapshot_week": "6", "import_type": "ALL", "sheet": ""},
            files={"file": ("all.xlsx", b"dummy", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    def test_historical_to_historical_is_frozen(self):
        self.state["projects"]["P-1"] = {"id": 1, "is_historical": True}
        self.state["historicals"].add("P-1")
        app.upsert_project = self._fake_upsert_project
        app.map_row = lambda row: (
            {"project_code": "P-1", "project_name": "Original"},
            {"internal_status": "Closed"},
        )

        res = self._post_all_import()

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["skipped_rows"], 1)
        self.assertEqual(res.json()["archived_rows"], 0)
        self.assertEqual(self.state["upsert_calls"], 0)
        self.assertEqual(self.state["move_calls"], 0)

    def test_active_to_historical_sets_historical_transition(self):
        self.state["projects"]["P-2"] = {"id": 2, "is_historical": False}
        app.upsert_project = self._fake_upsert_project
        app.map_row = lambda row: (
            {"project_code": "P-2", "project_name": "Active Project"},
            {"internal_status": "Hided"},
        )

        res = self._post_all_import()

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["archived_rows"], 1)
        self.assertEqual(self.state["upsert_calls"], 1)
        self.assertEqual(self.state["move_calls"], 1)

    def test_historical_to_active_reactivation_still_works(self):
        self.state["projects"]["P-3"] = {"id": 3, "is_historical": True}
        self.state["historicals"].add("P-3")
        app.upsert_project = self._fake_upsert_project
        app.map_row = lambda row: (
            {"project_code": "P-3", "project_name": "Back Again"},
            {"internal_status": "Normal"},
        )

        res = self._post_all_import()

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["restored_rows"], 1)
        self.assertEqual(res.json()["imported_rows"], 1)
        self.assertEqual(self.state["upsert_calls"], 1)
        self.assertEqual(self.state["restore_calls"], 1)
        self.assertEqual(self.state["snapshot_calls"], 1)


if __name__ == "__main__":
    unittest.main()
