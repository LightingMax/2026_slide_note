from pydantic import BaseModel, Field


class SlideAsset(BaseModel):
    name: str
    kind: str
    url: str
    content_type: str | None = None


class Slide(BaseModel):
    id: str
    index: int
    title: str
    text: str
    notes: str
    snapshot_url: str | None = None
    render_status: str = "pending"
    render_error: str | None = None
    assets: list[SlideAsset] = Field(default_factory=list)


class Deck(BaseModel):
    id: str
    filename: str
    created_at: str
    slides: list[Slide]


class NoteUpdate(BaseModel):
    notes: str


class ChatMessage(BaseModel):
    role: str
    content: str


class AgentAction(BaseModel):
    type: str
    slide_id: str
    label: str
    content: str


class ChatRequest(BaseModel):
    slide_id: str
    instruction: str
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    text: str
    message: str
    actions: list[AgentAction] = Field(default_factory=list)
