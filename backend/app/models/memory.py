from pydantic import BaseModel, Field


class MemoryEvent(BaseModel):
    id: str
    created_at: str
    type: str
    summary: str
    slide_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class SlideMemory(BaseModel):
    slide_id: str
    role: str = ""
    last_change: str = ""
    notes_status: str = ""
    user_feedback: list[str] = Field(default_factory=list)


class DeckMemory(BaseModel):
    deck_id: str
    deck_goal: str = ""
    audience: str = ""
    style: str = ""
    latest_user_intent: str = ""
    global_constraints: list[str] = Field(default_factory=list)
    slides: dict[str, SlideMemory] = Field(default_factory=dict)
    events: list[MemoryEvent] = Field(default_factory=list)
