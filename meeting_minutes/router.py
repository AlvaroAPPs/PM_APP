import io

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from .docx_service import build_meeting_minutes_docx
from .models import MeetingMinutesPayload

router = APIRouter(tags=["meeting-minutes"])
templates = Jinja2Templates(directory="templates")


@router.get("/meeting-minutes", response_class=HTMLResponse)
def meeting_minutes_page(request: Request):
    return templates.TemplateResponse("meeting_minutes.html", {"request": request})


@router.post("/meeting-minutes/export.docx")
def export_meeting_minutes(payload: MeetingMinutesPayload):
    docx_bytes = build_meeting_minutes_docx(payload)
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="meeting_minutes.docx"'},
    )
