from __future__ import annotations

import io
import os
from datetime import date

import psycopg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from planning.pdf import build_gantt_pdf
from planning.storage import fetch_project_progress, seed_phase_items, sync_checklist_milestone

router = APIRouter(tags=["planning"])
templates = Jinja2Templates(directory="templates")

DB_DSN = os.environ.get("DB_DSN", "postgresql://postgres:TU_PASSWORD@localhost:5432/mecalux")


class GanttItemIn(BaseModel):
    title: str
    start_date: str
    end_date: str
    is_milestone: bool = False
    parent_id: int | None = None
    progress: int = 0


class GanttItemUpdateIn(BaseModel):
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_milestone: bool | None = None
    parent_id: int | None = None
    position: int | None = None
    progress: int | None = None


def fetch_project_by_code(cur: psycopg.Cursor, project_code: str) -> tuple[int, str | None]:
    cur.execute(
        "SELECT id, project_name FROM projects WHERE project_code = %s AND COALESCE(is_historical, FALSE) = FALSE",
        (project_code,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return row[0], row[1]


def _row_to_item(row: tuple) -> dict:
    return {
        "id": row[0],
        "parent_id": row[1],
        "title": row[2],
        "start_date": row[3].isoformat(),
        "end_date": row[4].isoformat(),
        "is_milestone": row[5],
        "position": row[6],
        "source": row[7],
        "checklist_item_id": row[8],
        "touched": row[9],
        "progress": row[10],
    }


def _fetch_or_seed_items(cur: psycopg.Cursor, project_id: int) -> list[tuple]:
    cur.execute("SELECT id FROM project_gantt_items WHERE project_id = %s LIMIT 1", (project_id,))
    if not cur.fetchone():
        seed_phase_items(cur, project_id)
    cur.execute(
        """
        SELECT id, parent_id, title, start_date, end_date, is_milestone, position, source, checklist_item_id, touched, progress
        FROM project_gantt_items
        WHERE project_id = %s
        ORDER BY position, id
        """,
        (project_id,),
    )
    return cur.fetchall()


def _clamp_progress(value: int) -> int:
    return max(0, min(100, value))


@router.get("/projects/{project_code}/planning", response_class=HTMLResponse)
def project_planning_page(request: Request, project_code: str):
    return templates.TemplateResponse("project_planning.html", {"request": request, "project_code": project_code})


@router.get("/api/projects/{project_code}/gantt")
def get_project_gantt(project_code: str):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            project_id, project_name = fetch_project_by_code(cur, project_code)
            rows = _fetch_or_seed_items(cur, project_id)
            progress_w = fetch_project_progress(cur, project_id)
        conn.commit()
    return {
        "project": {"id": project_id, "project_code": project_code, "project_name": project_name, "progress_w": progress_w},
        "items": [_row_to_item(r) for r in rows],
    }


@router.post("/api/projects/{project_code}/gantt")
def create_gantt_item(project_code: str, payload: GanttItemIn):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="El titulo es obligatorio")
    try:
        start = date.fromisoformat(payload.start_date)
        end = date.fromisoformat(payload.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Fecha invalida")
    if end < start:
        raise HTTPException(status_code=400, detail="La fecha de fin no puede ser anterior a la de inicio")
    if payload.is_milestone:
        end = start

    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            project_id, _ = fetch_project_by_code(cur, project_code)
            if payload.parent_id is not None:
                cur.execute(
                    "SELECT 1 FROM project_gantt_items WHERE id = %s AND project_id = %s",
                    (payload.parent_id, project_id),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=400, detail="Tarea padre no encontrada")
            cur.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM project_gantt_items WHERE project_id = %s",
                (project_id,),
            )
            position = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO project_gantt_items
                    (project_id, parent_id, title, start_date, end_date, is_milestone, position, source, touched, progress)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'manual', TRUE, %s)
                RETURNING id
                """,
                (project_id, payload.parent_id, title, start, end, payload.is_milestone, position, _clamp_progress(payload.progress)),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    return {"id": item_id}


@router.patch("/api/gantt-items/{item_id}")
def update_gantt_item(item_id: int, payload: GanttItemUpdateIn):
    fields: list[str] = []
    values: list[object] = []
    touched = False

    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="El titulo es obligatorio")
        fields.append("title = %s")
        values.append(title)
        touched = True

    new_start: date | None = None
    if payload.start_date is not None:
        try:
            new_start = date.fromisoformat(payload.start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Fecha invalida")
        fields.append("start_date = %s")
        values.append(new_start)
        touched = True
    if payload.end_date is not None:
        try:
            date.fromisoformat(payload.end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Fecha invalida")
        touched = True
    if payload.is_milestone is not None:
        fields.append("is_milestone = %s")
        values.append(payload.is_milestone)
    if payload.parent_id is not None:
        fields.append("parent_id = %s")
        values.append(payload.parent_id)
    if payload.position is not None:
        fields.append("position = %s")
        values.append(payload.position)
    if payload.progress is not None:
        fields.append("progress = %s")
        values.append(_clamp_progress(payload.progress))

    if not fields and payload.end_date is None:
        return {"ok": True}

    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_milestone, start_date FROM project_gantt_items WHERE id = %s",
                (item_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tarea no encontrada")
            current_is_milestone, current_start = row
            effective_is_milestone = payload.is_milestone if payload.is_milestone is not None else current_is_milestone
            effective_start = new_start if new_start is not None else current_start

            end_date_value = date.fromisoformat(payload.end_date) if payload.end_date is not None else None
            if effective_is_milestone:
                end_date_value = effective_start
            if end_date_value is not None:
                fields.append("end_date = %s")
                values.append(end_date_value)

            if not fields:
                return {"ok": True}
            if touched:
                fields.append("touched = TRUE")
            fields.append("updated_at = now()")
            values.append(item_id)
            cur.execute(
                f"UPDATE project_gantt_items SET {', '.join(fields)} WHERE id = %s",
                values,
            )
        conn.commit()
    return {"ok": True}


@router.delete("/api/gantt-items/{item_id}")
def delete_gantt_item(item_id: int):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM project_gantt_items WHERE id = %s", (item_id,))
        conn.commit()
    return {"ok": True}


@router.get("/projects/{project_code}/planning/report.pdf")
def project_planning_pdf(project_code: str):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            project_id, project_name = fetch_project_by_code(cur, project_code)
            rows = _fetch_or_seed_items(cur, project_id)
            progress_w = fetch_project_progress(cur, project_id)
        conn.commit()

    items = [_row_to_item(r) for r in rows]
    pdf_bytes = build_gantt_pdf(project_name or project_code, project_code, items, progress_w=progress_w)
    filename = f"gantt_{project_code}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
