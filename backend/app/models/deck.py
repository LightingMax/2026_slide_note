from pydantic import BaseModel, Field, model_validator


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
    original_notes: str | None = None
    snapshot_url: str | None = None
    render_status: str = "pending"
    render_error: str | None = None
    assets: list[SlideAsset] = Field(default_factory=list)

    @model_validator(mode="after")
    def hydrate_original_notes(self) -> "Slide":
        if self.original_notes is None:
            self.original_notes = self.notes
        return self


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


class AgentUiOption(BaseModel):
    label: str
    value: str
    description: str = ""


class AgentUi(BaseModel):
    type: str
    id: str
    title: str
    mode: str = "buttons"
    options: list[AgentUiOption] = Field(default_factory=list)


class ChatRequest(BaseModel):
    slide_id: str
    instruction: str
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    text: str
    message: str
    actions: list[AgentAction] = Field(default_factory=list)
    ui: AgentUi | None = None


class AgentRunCreate(BaseModel):
    deck_id: str
    slide_id: str
    instruction: str
    style_preset: str = "auto"
    messages: list[ChatMessage] = Field(default_factory=list)


class AgentRunCreated(BaseModel):
    run_id: str


class AgentStylePreset(BaseModel):
    id: str
    name: str
    description: str
