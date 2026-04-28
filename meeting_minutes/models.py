from pydantic import BaseModel, Field


class MeetingParticipant(BaseModel):
    name: str = ""
    department: str = ""
    absent: bool = False
    notes: str = ""


class MeetingMinutesPayload(BaseModel):
    language: str = Field(default="es", pattern="^(es|en)$")
    project_id: int | None = None
    title: str = ""
    project_subject: str = ""
    albaran_number: str = ""
    meeting_date: str = ""
    start_time: str = ""
    end_time: str = ""
    location: str = ""
    phase: str = ""
    participants: list[MeetingParticipant] = Field(default_factory=list)
    topics: str = ""
    discussion: str = ""
    decisions_actions: str = ""
    planning_next_steps: str = ""
