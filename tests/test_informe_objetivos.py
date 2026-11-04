import unittest
from datetime import date

from reports import informe_objetivos as ob

CORTE = date(2026, 10, 5)
SEP, OCT, NOV = (2026, 9), (2026, 10), (2026, 11)


def row(code, hours, design=None, design_ok=False, phase="Development", status="Normal"):
    return {
        "project_code": code, "project_name": f"PROYECTO {code}", "ordered_n": hours, "ordered_e": 0,
        "internal_status": status, "order_phase": phase, "comments": "ultimo comentario",
        "date_design": design, "design_ok": design_ok,
    }


def celda(result, ym, tramo):
    return {e["code"]: e["estado"] for e in result["D"]["celdas"][(ym, tramo)]}


class ObjetivosTests(unittest.TestCase):
    def test_months_are_previous_current_next(self):
        result = ob.calcular_objetivos(CORTE, {}, None, {})
        self.assertEqual(result["D"]["meses"], [SEP, OCT, NOV])

    def test_months_shift_after_15th_when_month_already_reported(self):
        anteriores = [date(2026, 9, 14), date(2026, 10, 5)]
        self.assertEqual(ob.meses_tabla(date(2026, 10, 26), anteriores), [OCT, NOV, (2026, 12)])
        # Primer informe del mes: sigue mostrando el mes anterior completo
        self.assertEqual(ob.meses_tabla(date(2026, 10, 5), [date(2026, 9, 14)]), [SEP, OCT, NOV])
        # Ya hubo informe en el mes, pero aun no ha pasado el 15
        self.assertEqual(ob.meses_tabla(date(2026, 10, 12), anteriores), [SEP, OCT, NOV])
        # Pasado el 15 pero sin informe previo en el mes
        self.assertEqual(ob.meses_tabla(date(2026, 10, 26), [date(2026, 9, 28)]), [SEP, OCT, NOV])
        # Cambio de ano
        self.assertEqual(ob.meses_tabla(date(2026, 12, 20), [date(2026, 12, 2)]), [(2026, 12), (2027, 1), (2027, 2)])

    def test_states_without_replanning(self):
        actual = {
            "ok": row("ok", 150, date(2026, 9, 10), design_ok=True),
            "late": row("late", 150, date(2026, 9, 20)),            # mes pasado sin conseguir
            "now": row("now", 150, date(2026, 10, 20)),             # mes actual pendiente
            "small": row("small", 20, date(2026, 10, 1)),
        }
        result = ob.calcular_objetivos(CORTE, actual, actual, {})
        self.assertEqual(celda(result, SEP, "m"), {"ok": ob.ESTADO_OK, "late": ob.ESTADO_ROJO})
        self.assertEqual(celda(result, OCT, "m"), {"now": ob.ESTADO_PENDIENTE})
        self.assertEqual(list(celda(result, OCT, "s")), ["small"])

    def test_replanned_first_time_stays_in_old_column(self):
        anterior = {
            "a": row("a", 150, date(2026, 9, 10)),
            "b": row("b", 150, date(2026, 9, 10)),
            "c": row("c", 150, date(2026, 10, 10)),
        }
        actual = {
            "a": row("a", 150, date(2026, 10, 15)),                 # +1 mes -> naranja
            "b": row("b", 150, date(2026, 12, 1)),                  # +3 meses -> rojo
            "c": row("c", 150, date(2026, 10, 10), phase="Stopped"),  # parado -> rojo
        }
        result = ob.calcular_objetivos(CORTE, actual, anterior, {})
        self.assertEqual(celda(result, SEP, "m"), {"a": ob.ESTADO_NARANJA, "b": ob.ESTADO_ROJO})
        self.assertEqual(celda(result, OCT, "m"), {"a": ob.ESTADO_PENDIENTE, "c": ob.ESTADO_ROJO})

    def test_replanning_marked_again_in_a_later_report(self):
        # Ya se replanifico antes: si vuelve a moverse desde un mes visible, se marca
        anterior = {"a": row("a", 150, date(2026, 9, 10))}
        actual = {"a": row("a", 150, date(2026, 10, 15))}
        result = ob.calcular_objetivos(CORTE, actual, anterior, {})
        self.assertEqual(celda(result, SEP, "m"), {"a": ob.ESTADO_NARANJA})

    def test_replanning_from_hidden_month_is_not_marked(self):
        # Pasa de enero a febrero con columnas sep-nov: no se ve, no se marca
        anterior = {"a": row("a", 150, date(2027, 1, 10))}
        actual = {"a": row("a", 150, date(2027, 2, 10))}
        result = ob.calcular_objetivos(CORTE, actual, anterior, {})
        self.assertTrue(all(not e for e in result["D"]["celdas"].values()))

    def test_short_name_and_delayed_list(self):
        anterior = {"a": row("a", 150, date(2026, 9, 10)), "s": row("s", 50, date(2026, 9, 10))}
        actual = {"a": row("a", 150, date(2026, 10, 15)), "s": row("s", 50, date(2026, 10, 15))}
        result = ob.calcular_objetivos(CORTE, actual, anterior, {"a": "CLIENTE A - Fase 2"})
        delayed = ob.retrasados(result, {("a", "D"): {"motivo": "Falta firma", "heredado": True}})
        self.assertEqual([(e["code"], e["nombre"], e["motivo"]) for e in delayed["D"]],
                         [("a", "CLIENTE A - Fase 2", "Falta firma")])


if __name__ == "__main__":
    unittest.main()
