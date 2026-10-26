import unittest
from datetime import date

from reports import informe_direccion as inf
from reports import project_closures as pc

CORTE = date(2026, 10, 5)


def row(code, hours, status="Normal", phase="Development", pct=0, **extra):
    return {
        "project_code": code, "client": f"CLIENTE {code}", "ordered_n": hours, "ordered_e": 0,
        "internal_status": status, "order_phase": phase, "status_pct": pct, **extra,
    }


class MetricasTests(unittest.TestCase):
    def test_counts_only_normal_and_first_row_per_code(self):
        rows = [row("1", 10), row("1", 50), row("2", 20, phase="Stopped"), row("3", 30, status="Closed")]
        metricas = inf.calcular_metricas(rows, {}, CORTE)
        self.assertEqual(metricas["proyectos"], {"totales": 2, "activos": 1, "parados": 1})
        self.assertEqual(metricas["horas"]["totales"], 30)

    def test_pending_and_executable_hours(self):
        rows = [
            row("1", 200, pct=25),
            row("2", 100, phase="Stopped", pct=50),
            row("3", 40, phase="Design", date_design=date(2026, 11, 30)),
            row("4", 40, phase="Design", date_design=date(2026, 10, 15)),
        ]
        horas = inf.calcular_metricas(rows, {}, CORTE)["horas"]
        self.assertEqual(horas["pendientes"], 150 + 50 + 40 + 40)
        # Parado y diseno a mas de 15 dias no son ejecutables
        self.assertEqual(horas["ejecutables"], 150 + 40)

    def test_size_groups_use_macro_limits(self):
        rows = [row("1", 100), row("2", 101), row("3", 399), row("4", 400)]
        tramos = inf.calcular_metricas(rows, {}, CORTE)["tramos"]
        self.assertEqual(tramos["s"]["total"], 100)
        self.assertEqual(tramos["m"]["total"], 500)
        self.assertEqual(tramos["l"]["total"], 400)

    def test_billing_vs_invested_hours(self):
        rows = [row("1", 10, pct=50, payment_total=1000, payment_inv=30)]
        metricas = inf.calcular_metricas(rows, {"1": 4}, CORTE)
        horas = metricas["horas_vs_facturacion"]["total"]
        self.assertAlmostEqual(horas["base"], 400)  # 4 h reales * 100 EUR/h
        self.assertAlmostEqual(horas["facturado"], 300)
        self.assertAlmostEqual(horas["rojo"], -100)
        avance = metricas["avance_vs_facturacion"]["total"]
        self.assertAlmostEqual(avance["base"], 500)
        self.assertAlmostEqual(avance["rojo"], -200)

    def test_round_like_excel(self):
        self.assertEqual(inf._round_excel(2.5), 3)
        self.assertEqual(inf._round_excel(-2.5), -3)


class EntregasTests(unittest.TestCase):
    def test_cumulative_closed_until_cut_month(self):
        rows = [
            row("1", 10, status="Closed", date_end=date(2026, 1, 20)),
            row("2", 5, status="Closed", date_end=date(2026, 3, 2)),
            row("3", 7, status="Closed", date_end=date(2025, 12, 2)),
            row("4", 9, date_end=date(2026, 2, 2)),
        ]
        entregas = inf.calcular_entregas(rows, date(2026, 3, 15))
        self.assertEqual(entregas["horas"][:4], [10, 10, 15, None])
        self.assertEqual(entregas["proyectos"][:3], [1, 1, 2])

    def test_closed_hours_follow_closure_report_priority(self):
        def closed(code, total, **extra):
            return {"project_code": code, "internal_status": "Closed", "date_end": date(2026, 1, 10),
                    "ordered_total": total, **extra}

        rows = [
            closed("1", 81, frozen_hours=138),                              # congeladas al cierre
            closed("2", 50, frozen_hours=40, closed_hours_override=45),     # correccion manual
            closed("3", 20),                                                 # sin congelar: actuales
        ]
        entregas = inf.calcular_entregas(rows, date(2026, 1, 31))
        self.assertEqual(entregas["horas"][0], 138 + 45 + 20)


class LatestBatchCodesTests(unittest.TestCase):
    def test_project_with_non_ots_type_is_not_present(self):
        class FakeCursor:
            def __init__(self):
                self.result = []

            def execute(self, query, params=None):
                if "SELECT id, snapshot_year" in query:
                    self.result = [(255,)]
                else:
                    self.result = [
                        ("A", "closed", "otssoftware"),
                        ("MONDELEZ", "normal", "software"),
                        ("B", "normal", "otsrobotic"),
                    ]

            def fetchall(self):
                return self.result

        _batch, present, closed = pc._latest_batch_codes(FakeCursor())
        self.assertEqual(present, {"A", "B"})
        self.assertEqual(closed, {"A"})


class CompararCortesTests(unittest.TestCase):
    def test_entradas_y_salidas(self):
        old = [row("1", 100), row("2", 20), row("3", 30, status="Closed", ordered_e=0)]
        new = [
            row("1", 120),                 # cambio de horas +20
            row("2", 20, status="Closed"),  # salida
            row("3", 25, status="Closed"),  # cerrado->cerrado: no cuenta
            row("4", 150),                 # nuevo entre 100 y 400
            row("5", 450, status="Closed"),  # nuevo ya cerrado: no cuenta
        ]
        delta = inf.comparar_cortes(old, new)
        self.assertEqual(delta["entradas"]["cambios_horas"], 20)
        self.assertEqual([i["code"] for i in delta["entradas"]["tramos"]["m"]], ["4"])
        self.assertEqual(delta["entradas"]["total_horas"], 170)
        self.assertEqual([i["code"] for i in delta["salidas"]["tramos"]["s"]], ["2"])
        self.assertEqual(delta["salidas"]["total_horas"], 20)

    def test_net_matches_total_hours_change(self):
        old = [row("1", 50), row("2", 40), row("3", 30, status="Hided"), row("4", 80, status="Normal")]
        new = [
            row("1", 50),
            # "2" desaparece del AllOrders -> salida con sus horas anteriores
            row("3", 35),                   # vuelve a Normal -> entrada
            row("4", 90, status="Closed"),  # cierra con horas cambiadas -> sale con las 80 que tenia
        ]
        delta = inf.comparar_cortes(old, new)
        salidas = delta["salidas"]["tramos"]["s"]
        self.assertEqual({i["code"]: i["hours"] for i in salidas}, {"2": 40, "4": 80})
        self.assertEqual(next(i for i in salidas if i["code"] == "2")["motivo"], "Ya no aparece en el AllOrders")
        self.assertEqual([i["code"] for i in delta["entradas"]["tramos"]["s"]], ["3"])
        total_old = sum(inf._ordered(r) for r in old if inf._is_normal(r))
        total_new = sum(inf._ordered(r) for r in new if inf._is_normal(r))
        neto = delta["entradas"]["total_horas"] - delta["salidas"]["total_horas"]
        self.assertEqual(neto, total_new - total_old)


if __name__ == "__main__":
    unittest.main()
