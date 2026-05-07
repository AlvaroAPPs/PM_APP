import io
import os
from datetime import date

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from psycopg.types.json import Json

from .docx_service import build_meeting_minutes_docx, build_meeting_minutes_filename
from .models import MeetingMinutesPayload
from .storage import ensure_meeting_minutes_storage

router = APIRouter(tags=["meeting-minutes"])
templates = Jinja2Templates(directory="templates")
DB_DSN = os.environ.get("DB_DSN", "postgresql://postgres:TU_PASSWORD@localhost:5432/mecalux")


def _project_name_for_filename(payload: MeetingMinutesPayload) -> str | None:
    if payload.project_id is None:
        return None
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT project_name
                FROM projects
                WHERE id = %s
                """,
                (payload.project_id,),
            )
            row = cur.fetchone()
    return str(row[0]).strip() if row and row[0] else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date") from exc


@router.get("/meeting-minutes", response_class=HTMLResponse)
def meeting_minutes_page(request: Request, minutes_id: int | None = None):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_meeting_minutes_storage(cur)
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
            existing_minutes = None
            if minutes_id is not None:
                cur.execute(
                    """
                    SELECT id, project_id, title, project_subject, albaran_number, language,
                           meeting_date, start_time, end_time, location, phase, participants,
                           topic_blocks, topics, discussion, decisions_actions, planning_next_steps
                    FROM meeting_minutes
                    WHERE id = %s
                    """,
                    (minutes_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Minutes not found")
                existing_minutes = {
                    "id": int(row[0]),
                    "project_id": row[1],
                    "title": row[2] or "",
                    "project_subject": row[3] or "",
                    "albaran_number": row[4] or "",
                    "language": row[5] or "es",
                    "meeting_date": row[6].isoformat() if row[6] else "",
                    "start_time": row[7] or "",
                    "end_time": row[8] or "",
                    "location": row[9] or "",
                    "phase": row[10] or "",
                    "participants": row[11] or [],
                    "topic_blocks": row[12] or [],
                    "topics": row[13] or "",
                    "discussion": row[14] or "",
                    "decisions_actions": row[15] or "",
                    "planning_next_steps": row[16] or "",
                }
    return templates.TemplateResponse(
        "meeting_minutes.html",
        {"request": request, "projects": projects, "existing_minutes": existing_minutes},
    )


@router.get("/meeting-minutes/albaranes/search")
def meeting_minutes_albaranes_search(q: str = ""):
    query = (q or "").strip()
    like = f"%{query}%"
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_meeting_minutes_storage(cur)
            cur.execute(
                """
                SELECT DISTINCT m.albaran_number
                FROM meeting_minutes m
                WHERE m.albaran_number IS NOT NULL
                  AND m.albaran_number <> ''
                  AND (%s = '' OR m.albaran_number ILIKE %s)
                ORDER BY m.albaran_number ASC
                LIMIT 12
                """,
                (query, like),
            )
            albaranes = [row[0] for row in cur.fetchall()]
    return {"items": albaranes}


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
                  AND EXISTS (
                    SELECT 1
                    FROM meeting_minutes m
                    WHERE m.project_id = projects.id
                  )
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
@router.post("/meeting-minutes/")
def create_meeting_minutes(payload: MeetingMinutesPayload):
    title = (payload.title or "").strip() or (payload.project_subject or "").strip()
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
                    location, phase, language, albaran_number, participants, topic_blocks, topics,
                    discussion, decisions_actions, planning_next_steps
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
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
                    Json([block.model_dump() for block in payload.topic_blocks]),
                    payload.topics,
                    payload.discussion,
                    payload.decisions_actions,
                    payload.planning_next_steps,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return {"status": "ok", "id": int(row[0])}


@router.put("/meeting-minutes/{minutes_id}")
def update_meeting_minutes(minutes_id: int, payload: MeetingMinutesPayload):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_meeting_minutes_storage(cur)
            cur.execute(
                """
                SELECT project_id, title, project_subject, meeting_date, start_time, end_time,
                       location, phase, language, albaran_number, participants, topic_blocks, topics,
                       discussion, decisions_actions, planning_next_steps
                FROM meeting_minutes
                WHERE id = %s
                """,
                (minutes_id,),
            )
            current = cur.fetchone()
            if not current:
                raise HTTPException(status_code=404, detail="Minutes not found")

            merged_title = (payload.title or "").strip() or (current[1] or "")
            merged_project_subject = (payload.project_subject or "").strip() or (current[2] or "")
            if not merged_title:
                merged_title = merged_project_subject
            if not merged_title:
                raise HTTPException(status_code=400, detail="Title is required")

            merged_meeting_date = _parse_date(payload.meeting_date) if payload.meeting_date else current[3]
            merged_start_time = payload.start_time if payload.start_time else (current[4] or "")
            merged_end_time = payload.end_time if payload.end_time else (current[5] or "")
            merged_location = payload.location if payload.location else (current[6] or "")
            merged_phase = payload.phase if payload.phase else (current[7] or "")
            merged_language = payload.language if payload.language else (current[8] or "es")
            merged_albaran = payload.albaran_number if payload.albaran_number else (current[9] or "")
            incoming_participants = [participant.model_dump() for participant in payload.participants]
            merged_participants = incoming_participants if incoming_participants else (current[10] or [])
            incoming_topic_blocks = [block.model_dump() for block in payload.topic_blocks]
            merged_topic_blocks = incoming_topic_blocks if incoming_topic_blocks else (current[11] or [])
            merged_topics = payload.topics if payload.topics else (current[12] or "")
            merged_discussion = payload.discussion if payload.discussion else (current[13] or "")
            merged_decisions = payload.decisions_actions if payload.decisions_actions else (current[14] or "")
            merged_planning = payload.planning_next_steps if payload.planning_next_steps else (current[15] or "")
            cur.execute(
                """
                UPDATE meeting_minutes
                SET project_id = %s,
                    title = %s,
                    project_subject = %s,
                    meeting_date = %s,
                    start_time = %s,
                    end_time = %s,
                    location = %s,
                    phase = %s,
                    language = %s,
                    albaran_number = %s,
                    participants = %s::jsonb,
                    topic_blocks = %s::jsonb,
                    topics = %s,
                    discussion = %s,
                    decisions_actions = %s,
                    planning_next_steps = %s,
                    updated_at = now()
                WHERE id = %s
                RETURNING id
                """,
                (
                    payload.project_id if payload.project_id is not None else current[0],
                    merged_title,
                    merged_project_subject,
                    merged_meeting_date,
                    merged_start_time,
                    merged_end_time,
                    merged_location,
                    merged_phase,
                    merged_language,
                    merged_albaran,
                    Json(merged_participants),
                    Json(merged_topic_blocks),
                    merged_topics,
                    merged_discussion,
                    merged_decisions,
                    merged_planning,
                    minutes_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return {"status": "ok", "id": int(row[0])}


@router.post("/meeting-minutes/export.docx")
@router.post("/meeting-minutes/export.docx/")
def export_meeting_minutes(payload: MeetingMinutesPayload):
    docx_bytes = build_meeting_minutes_docx(payload)
    filename = build_meeting_minutes_filename(payload, _project_name_for_filename(payload))
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
