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
        result = ob.calcular_objetivos(CORTE, {}, None, set(), {})
        self.assertEqual(result["D"]["meses"], [SEP, OCT, NOV])

    def test_states_without_replanning(self):
        actual = {
            "ok": row("ok", 150, date(2026, 9, 10), design_ok=True),
            "late": row("late", 150, date(2026, 9, 20)),            # mes pasado sin conseguir
            "now": row("now", 150, date(2026, 10, 20)),             # mes actual pendiente
            "small": row("small", 20, date(2026, 10, 1)),
        }
        result = ob.calcular_objetivos(CORTE, actual, actual, set(), {})
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
        result = ob.calcular_objetivos(CORTE, actual, anterior, set(), {})
        self.assertEqual(celda(result, SEP, "m"), {"a": ob.ESTADO_NARANJA, "b": ob.ESTADO_ROJO})
        self.assertEqual(celda(result, OCT, "m"), {"a": ob.ESTADO_PENDIENTE, "c": ob.ESTADO_ROJO})

    def test_second_replanning_is_not_marked(self):
        anterior = {"a": row("a", 150, date(2026, 9, 10))}
        actual = {"a": row("a", 150, date(2026, 10, 15))}
        result = ob.calcular_objetivos(CORTE, actual, anterior, {("a", "D")}, {})
        self.assertEqual(celda(result, SEP, "m"), {})
        self.assertEqual(celda(result, OCT, "m"), {"a": ob.ESTADO_PENDIENTE})

    def test_previous_replannings_from_history(self):
        history = [
            {"a": row("a", 150, date(2026, 8, 10)), "b": row("b", 150, date(2026, 8, 10))},
            {"a": row("a", 150, date(2026, 9, 10)), "b": row("b", 150, date(2026, 7, 10))},
        ]
        self.assertEqual(ob.replanificados_previos(history), {("a", "D")})

    def test_short_name_and_delayed_list(self):
        anterior = {"a": row("a", 150, date(2026, 9, 10)), "s": row("s", 50, date(2026, 9, 10))}
        actual = {"a": row("a", 150, date(2026, 10, 15)), "s": row("s", 50, date(2026, 10, 15))}
        result = ob.calcular_objetivos(CORTE, actual, anterior, set(), {"a": "CLIENTE A - Fase 2"})
        delayed = ob.retrasados(result, {("a", "D"): {"motivo": "Falta firma", "heredado": True}})
        self.assertEqual([(e["code"], e["nombre"], e["motivo"]) for e in delayed["D"]],
                         [("a", "CLIENTE A - Fase 2", "Falta firma")])


if __name__ == "__main__":
    unittest.main()
