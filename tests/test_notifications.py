import unittest
from datetime import date

from notifications.service import build_notification_payload


def _item(day: date, title: str, code: str = "P1") -> dict:
    return {
        "kind": "tarea",
        "project_code": code,
        "project_name": "Proyecto",
        "title": title,
        "date": day,
        "owner_role": "PM",
        "url": "/tasks?project_id=1&type=TASK",
    }


class NotificationPayloadTests(unittest.TestCase):
    def test_splits_overdue_today_and_upcoming(self):
        today = date(2026, 10, 21)
        items = [_item(date(2026, 10, 15), "Vieja"), _item(today, "Hoy"), _item(date(2026, 10, 25), "Futura")]
        payload = build_notification_payload("PM", items, today, 7)
        self.assertEqual(payload["total"], 3)
        self.assertEqual([i["title"] for i in payload["overdue"]], ["Vieja"])
        self.assertEqual([i["title"] for i in payload["today_items"]], ["Hoy"])
        self.assertEqual([i["title"] for i in payload["upcoming"]], ["Futura"])
        self.assertEqual(payload["summary"], "1 vencido · 1 para hoy · 1 en los próximos 7 días")
        self.assertEqual(payload["upcoming"][0]["date"], "2026-10-25")

    def test_highlights_show_most_urgent_first_and_max_three(self):
        today = date(2026, 10, 21)
        items = [_item(date(2026, 10, d), f"T{d}") for d in (18, 19, 20, 22, 23)]
        payload = build_notification_payload("PM", items, today, 7)
        self.assertEqual(payload["highlights"], ["18/10 · P1 · T18", "19/10 · P1 · T19", "20/10 · P1 · T20"])

    def test_empty_summary(self):
        payload = build_notification_payload("PM", [], date(2026, 10, 21), 7)
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["summary"], "Nada pendiente en tu planning")


if __name__ == "__main__":
    unittest.main()
