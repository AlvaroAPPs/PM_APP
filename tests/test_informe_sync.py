import gzip
import json
import unittest
from datetime import date, datetime, timezone

from reports import informe_direccion as inf
from reports import informe_sync as sync


class FakeCursor:
    """Cursor minimo para importar_decision: registra las sentencias y simula
    que el proyecto existe en historicos."""

    def __init__(self):
        self.sql = []
        self._result = None

    def execute(self, query, params=None):
        self.sql.append((" ".join(query.split()), params))
        self._result = (1,) if "RETURNING id" in query else None

    def fetchone(self):
        return self._result


def remota(valor, por, at="2026-10-20T10:00:00+00:00", tipo=sync.TIPO_OVERRIDE, code="P1"):
    return {"tipo": tipo, "project_code": code, "valor": valor, "validado_por": por, "decidido_at": at}


def local(valor, por, at=datetime(2026, 10, 10, tzinfo=timezone.utc)):
    return {(sync.TIPO_OVERRIDE, "P1"): {"valor": valor, "validado_por": por, "at": at}}


class DobleValidacionTests(unittest.TestCase):
    def test_new_decision_is_added(self):
        cur = FakeCursor()
        resultado, _ = sync.importar_decision(cur, "B", remota({"horas": 138}, ["A"]), {})
        self.assertEqual(resultado, "anadida")
        self.assertTrue(any("UPDATE projects_historical" in q for q, _ in cur.sql))

    def test_same_value_adds_validation_and_confirms(self):
        cur = FakeCursor()
        resultado, detalle = sync.importar_decision(cur, "B", remota({"horas": 138}, ["A"]), local({"horas": 138}, ["B"]))
        self.assertEqual(resultado, "confirmada")
        self.assertEqual(detalle, "A, B")

    def test_different_unconfirmed_values_create_conflict(self):
        cur = FakeCursor()
        resultado, _ = sync.importar_decision(cur, "B", remota({"horas": 138}, ["A"]), local({"horas": 81}, ["B"]))
        self.assertEqual(resultado, "conflicto")
        self.assertFalse(any("UPDATE projects_historical" in q for q, _ in cur.sql))

    def test_confirmed_remote_overrides_unconfirmed_local(self):
        cur = FakeCursor()
        resultado, _ = sync.importar_decision(cur, "B", remota({"horas": 138}, ["A", "C"]), local({"horas": 81}, ["B"]))
        self.assertEqual(resultado, "sustituida")

    def test_confirmed_local_is_kept_against_unconfirmed_remote(self):
        cur = FakeCursor()
        resultado, _ = sync.importar_decision(cur, "B", remota({"horas": 138}, ["A"]), local({"horas": 81}, ["A", "B"]))
        self.assertEqual(resultado, "mantenida")

    def test_between_confirmed_the_latest_wins(self):
        older = remota({"horas": 138}, ["A", "C"], at="2026-10-01T10:00:00+00:00")
        newer = remota({"horas": 138}, ["A", "C"], at="2026-10-20T10:00:00+00:00")
        mine = local({"horas": 81}, ["A", "B"], at=datetime(2026, 10, 10, tzinfo=timezone.utc))
        self.assertEqual(sync.importar_decision(FakeCursor(), "B", older, mine)[0], "mantenida")
        self.assertEqual(sync.importar_decision(FakeCursor(), "B", newer, mine)[0], "sustituida")


class FicheroTests(unittest.TestCase):
    def test_reads_gzip_and_rejects_other_files(self):
        payload = {"formato": sync.FORMATO, "version": sync.VERSION, "cortes": []}
        self.assertEqual(sync.leer_fichero(gzip.compress(json.dumps(payload).encode()))["cortes"], [])
        with self.assertRaises(ValueError):
            sync.leer_fichero(b"no es un fichero")
        with self.assertRaises(ValueError):
            sync.leer_fichero(json.dumps({"formato": "otro"}).encode())

    def test_detail_rows_roundtrip_dates(self):
        row = {"project_code": "1", "date_end": date(2026, 8, 13), "ordered_n": 10, "kickoff_ok": True}
        back = inf._fila_desde_json(json.loads(json.dumps(inf._fila_json(row))))
        self.assertEqual(back["date_end"], date(2026, 8, 13))
        self.assertTrue(back["kickoff_ok"])


if __name__ == "__main__":
    unittest.main()
