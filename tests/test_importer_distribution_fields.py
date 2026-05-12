import math
import sys
import types
import unittest


if "pandas" not in sys.modules:
    pandas_stub = types.ModuleType("pandas")

    def isna(value):
        try:
            return math.isnan(value)
        except TypeError:
            return False

    pandas_stub.isna = isna
    pandas_stub.read_excel = None
    pandas_stub.ExcelFile = None
    pandas_stub.to_datetime = None
    sys.modules["pandas"] = pandas_stub

if "psycopg" not in sys.modules:
    psycopg_stub = types.ModuleType("psycopg")
    psycopg_stub.Cursor = object
    sys.modules["psycopg"] = psycopg_stub

import importer


class FakeCursor:
    def __init__(self):
        self.query = None
        self.payload = None

    def execute(self, query, payload):
        self.query = query
        self.payload = payload

    def fetchone(self):
        return (123,)


class ImporterDistributionFieldTests(unittest.TestCase):
    def test_distribution_headers_are_normalized_to_internal_fields(self):
        self.assertEqual(importer.RENAME_MAP[importer._snake("Distribution C")], "dist_c")
        self.assertEqual(importer.RENAME_MAP[importer._snake("Distribution PM")], "dist_pm")
        self.assertEqual(importer.RENAME_MAP[importer._snake("Distribution E")], "dist_e")

    def test_map_row_includes_distribution_values(self):
        _, snap = importer.map_row(
            {
                "project_code": "1001",
                "dist_c": "10.5",
                "dist_pm": 20,
                "dist_e": "30",
            }
        )

        self.assertEqual(snap["dist_c"], 10.5)
        self.assertEqual(snap["dist_pm"], 20.0)
        self.assertEqual(snap["dist_e"], 30.0)

    def test_upsert_snapshot_persists_distribution_fields(self):
        _, fields = importer.map_row(
            {
                "project_code": "1001",
                "dist_c": 10,
                "dist_pm": 20,
                "dist_e": 30,
            }
        )
        cur = FakeCursor()

        snapshot_id = importer.upsert_snapshot(cur, 1, 2, 2026, 6, fields)

        self.assertEqual(snapshot_id, 123)
        self.assertIn("dist_c, dist_pm, dist_e", cur.query)
        self.assertIn("dist_c = COALESCE(EXCLUDED.dist_c, project_snapshot.dist_c)", cur.query)
        self.assertEqual(cur.payload["dist_c"], 10.0)
        self.assertEqual(cur.payload["dist_pm"], 20.0)
        self.assertEqual(cur.payload["dist_e"], 30.0)


if __name__ == "__main__":
    unittest.main()
