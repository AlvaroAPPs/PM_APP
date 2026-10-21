"""Avisos para el PM configurado en el equipo: tareas y planning vencidos o
proximos. Lo consume el script de aviso emergente de Windows
(tools/aviso_pm.ps1) al iniciar sesion y a la hora programada."""
from __future__ import annotations

from datetime import date, timedelta

import psycopg

# Barras del Gantt vencidas hace mas de esto se ignoran: suelen ser fases
# antiguas que nadie marco al 100% y solo meterian ruido en el aviso.
GANTT_OVERDUE_LOOKBACK_DAYS = 30


def fetch_pm_notifications(cur: psycopg.Cursor, pm_name: str, today: date, days: int) -> list[dict]:
    horizon = today + timedelta(days=days)
    items: list[dict] = []

    cur.execute(
        """
        SELECT p.id, p.project_code, p.project_name, t.title, t.description, t.planned_date, t.owner_role, t.type
        FROM project_tasks t
        JOIN projects p ON p.id = t.project_id
        WHERE p.project_manager = %s
          AND COALESCE(p.is_historical, FALSE) = FALSE
          AND t.status <> 'CLOSED'
          AND t.planned_date IS NOT NULL
          AND t.planned_date <= %s
        """,
        (pm_name, horizon),
    )
    for project_id, code, name, title, description, planned_date, owner_role, task_type in cur.fetchall():
        items.append(
            {
                "kind": "pp" if task_type == "PP" else "tarea",
                "project_code": code,
                "project_name": name,
                "title": (title or description or "").strip(),
                "date": planned_date,
                "owner_role": owner_role,
                "url": f"/tasks?project_id={project_id}&type={task_type}",
            }
        )

    cur.execute(
        """
        SELECT p.project_code, p.project_name, g.title, g.end_date, g.is_milestone
        FROM project_gantt_items g
        JOIN projects p ON p.id = g.project_id
        WHERE p.project_manager = %s
          AND COALESCE(p.is_historical, FALSE) = FALSE
          AND g.progress < 100
          AND g.end_date BETWEEN %s AND %s
        """,
        (pm_name, today - timedelta(days=GANTT_OVERDUE_LOOKBACK_DAYS), horizon),
    )
    for code, name, title, end_date, is_milestone in cur.fetchall():
        items.append(
            {
                "kind": "hito" if is_milestone else "planning",
                "project_code": code,
                "project_name": name,
                "title": title,
                "date": end_date,
                "owner_role": None,
                "url": f"/projects/{code}/planning",
            }
        )

    items.sort(key=lambda item: (item["date"], item["project_code"] or "", item["title"]))
    return items


def build_notification_payload(pm_name: str, items: list[dict], today: date, days: int) -> dict:
    overdue = [item for item in items if item["date"] < today]
    due_today = [item for item in items if item["date"] == today]
    upcoming = [item for item in items if item["date"] > today]

    parts = []
    if overdue:
        parts.append(f"{len(overdue)} vencido{'s' if len(overdue) != 1 else ''}")
    if due_today:
        parts.append(f"{len(due_today)} para hoy")
    if upcoming:
        parts.append(f"{len(upcoming)} en los próximos {days} días")
    summary = " · ".join(parts) if parts else "Nada pendiente en tu planning"

    def serialize(item: dict) -> dict:
        return {**item, "date": item["date"].isoformat()}

    # Para el aviso: primero lo mas urgente (vencido y hoy), despues lo proximo.
    highlights = [
        f"{item['date']:%d/%m} · {item['project_code']} · {item['title']}"
        for item in (overdue + due_today + upcoming)[:3]
    ]

    return {
        "pm_name": pm_name,
        "today": today.isoformat(),
        "days": days,
        "total": len(items),
        "summary": summary,
        "highlights": highlights,
        "overdue": [serialize(item) for item in overdue],
        "today_items": [serialize(item) for item in due_today],
        "upcoming": [serialize(item) for item in upcoming],
    }
