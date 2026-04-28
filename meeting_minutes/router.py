import io
import os
from datetime import date

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from psycopg.types.json import Json

from .docx_service import build_meeting_minutes_docx
from .models import MeetingMinutesPayload
from .storage import ensure_meeting_minutes_storage

router = APIRouter(tags=["meeting-minutes"])
templates = Jinja2Templates(directory="templates")
DB_DSN = os.environ.get("DB_DSN", "postgresql://postgres:TU_PASSWORD@localhost:5432/mecalux")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date") from exc


@router.get("/meeting-minutes", response_class=HTMLResponse)
def meeting_minutes_page(request: Request):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, project_code, project_name
                FROM projects
                WHERE COALESCE(is_historical, FALSE) = FALSE
                ORDER BY project_name ASC, project_code ASC
                """
            )
            projects = [
                {"id": int(row[0]), "project_code": row[1], "project_name": row[2]}
                for row in cur.fetchall()
            ]
    return templates.TemplateResponse("meeting_minutes.html", {"request": request, "projects": projects})


@router.get("/meeting-minutes/list", response_class=HTMLResponse)
def list_meeting_minutes(
    request: Request,
    project_id: int | None = None,
    title: str | None = None,
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
):
    parsed_start = _parse_date(start_date)
    parsed_end = _parse_date(end_date)
    if parsed_start and parsed_end and parsed_end < parsed_start:
        raise HTTPException(status_code=400, detail="Invalid date range")

    where = ["1=1"]
    params: list[object] = []
    if project_id is not None:
        where.append("m.project_id = %s")
        params.append(project_id)
    if title:
        where.append("LOWER(m.title) LIKE %s")
        params.append(f"%{title.strip().lower()}%")
    if parsed_start:
        where.append("m.meeting_date >= %s")
        params.append(parsed_start)
    if parsed_end:
        where.append("m.meeting_date <= %s")
        params.append(parsed_end)

    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_meeting_minutes_storage(cur)
            cur.execute(
                f"""
                SELECT m.id, m.title, m.project_subject, m.albaran_number, m.language,
                       m.meeting_date, m.created_at,
                       p.id, p.project_code, p.project_name
                FROM meeting_minutes m
                LEFT JOIN projects p ON p.id = m.project_id
                WHERE {' AND '.join(where)}
                ORDER BY m.meeting_date DESC NULLS LAST, m.id DESC
                """,
                params,
            )
            rows = cur.fetchall()
            cur.execute(
                """
                SELECT id, project_code, project_name
                FROM projects
                WHERE COALESCE(is_historical, FALSE) = FALSE
                ORDER BY project_name ASC, project_code ASC
                """
            )
            projects = [
                {"id": int(row[0]), "project_code": row[1], "project_name": row[2]}
                for row in cur.fetchall()
            ]

    records = [
        {
            "id": int(row[0]),
            "title": row[1],
            "project_subject": row[2],
            "albaran_number": row[3],
            "language": row[4],
            "meeting_date": row[5].isoformat() if row[5] else None,
            "created_at": row[6].isoformat() if row[6] else None,
            "project_id": row[7],
            "project_code": row[8],
            "project_name": row[9],
        }
        for row in rows
    ]
    filters = {
        "project_id": project_id,
        "title": title or "",
        "start_date": start_date or "",
        "end_date": end_date or "",
    }
    return templates.TemplateResponse(
        "meeting_minutes_list.html",
        {"request": request, "records": records, "projects": projects, "filters": filters},
    )


@router.post("/meeting-minutes")
def create_meeting_minutes(payload: MeetingMinutesPayload):
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")

    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_meeting_minutes_storage(cur)
            if payload.project_id is not None:
                cur.execute(
                    """
                    SELECT id
                    FROM projects
                    WHERE id = %s
                      AND COALESCE(is_historical, FALSE) = FALSE
                    """,
                    (payload.project_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Project not found")
            cur.execute(
                """
                INSERT INTO meeting_minutes (
                    project_id, title, project_subject, meeting_date, start_time, end_time,
                    location, phase, language, albaran_number, participants, topics,
                    discussion, decisions_actions, planning_next_steps
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    payload.project_id,
                    title,
                    payload.project_subject,
                    _parse_date(payload.meeting_date),
                    payload.start_time,
                    payload.end_time,
                    payload.location,
                    payload.phase,
                    payload.language,
                    payload.albaran_number,
                    Json([participant.model_dump() for participant in payload.participants]),
                    payload.topics,
                    payload.discussion,
                    payload.decisions_actions,
                    payload.planning_next_steps,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return {"status": "ok", "id": int(row[0])}


@router.post("/meeting-minutes/export.docx")
def export_meeting_minutes(payload: MeetingMinutesPayload):
    docx_bytes = build_meeting_minutes_docx(payload)
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="meeting_minutes.docx"'},
    )
