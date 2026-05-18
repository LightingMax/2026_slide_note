from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.core.config import get_settings
from app.models.deck import (
    AgentRunCreate,
    AgentRunCreated,
    AgentStylePreset,
    ChatRequest,
    ChatResponse,
    Deck,
    NoteUpdate,
)
from app.models.memory import DeckMemory
from app.services.agent_runner import cancel_run, create_run, list_style_presets, stream_run
from app.services.ark_client import generate_note
from app.services.memory_store import (
    build_memory_context,
    clear_memory,
    load_memory,
    record_manual_note_update,
    record_note_reset,
)
from app.services.ppt_exporter import export_deck_with_notes, find_uploaded_pptx
from app.services.ppt_parser import parse_pptx
from app.services.ppt_renderer import render_deck_snapshots
from app.services.storage import list_decks, load_deck, save_deck

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/agent/styles", response_model=list[AgentStylePreset])
def get_agent_styles() -> list[AgentStylePreset]:
    return list_style_presets()


@router.post("/agent/runs", response_model=AgentRunCreated)
def create_agent_run(payload: AgentRunCreate) -> AgentRunCreated:
    return AgentRunCreated(run_id=create_run(payload))


@router.get("/agent/runs/{run_id}/events")
def get_agent_run_events(run_id: str) -> StreamingResponse:
    return StreamingResponse(stream_run(run_id), media_type="text/event-stream")


@router.delete("/agent/runs/{run_id}")
def cancel_agent_run(run_id: str) -> dict[str, bool]:
    return {"cancelled": cancel_run(run_id)}


@router.get("/decks", response_model=list[Deck])
def get_decks() -> list[Deck]:
    return list_decks()


@router.get("/decks/{deck_id}", response_model=Deck)
def get_deck(deck_id: str) -> Deck:
    try:
        return load_deck(deck_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc


@router.get("/decks/{deck_id}/memory", response_model=DeckMemory)
def get_deck_memory(deck_id: str) -> DeckMemory:
    try:
        load_deck(deck_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc
    return load_memory(deck_id)


@router.delete("/decks/{deck_id}/memory", response_model=DeckMemory)
def clear_deck_memory(deck_id: str) -> DeckMemory:
    try:
        load_deck(deck_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc
    return clear_memory(deck_id)


@router.post("/decks/upload", response_model=Deck)
async def upload_deck(file: UploadFile = File(...)) -> Deck:
    if not file.filename or Path(file.filename).suffix.lower() not in {".pptx"}:
        raise HTTPException(status_code=400, detail="Only .pptx files are supported")

    with NamedTemporaryFile(delete=False, suffix=".pptx") as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        deck = parse_pptx(tmp_path, file.filename)
        save_deck(deck)
        return deck
    finally:
        tmp_path.unlink(missing_ok=True)


@router.patch("/decks/{deck_id}/slides/{slide_id}/notes", response_model=Deck)
def update_notes(deck_id: str, slide_id: str, payload: NoteUpdate) -> Deck:
    try:
        deck = load_deck(deck_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    for slide in deck.slides:
        if slide.id == slide_id:
            slide.notes = payload.notes
            save_deck(deck)
            record_manual_note_update(deck_id, slide, payload.notes)
            return deck
    raise HTTPException(status_code=404, detail="Slide not found")


@router.post("/decks/{deck_id}/slides/{slide_id}/notes/reset", response_model=Deck)
def reset_notes(deck_id: str, slide_id: str) -> Deck:
    try:
        deck = load_deck(deck_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    for slide in deck.slides:
        if slide.id == slide_id:
            slide.notes = slide.original_notes or ""
            save_deck(deck)
            record_note_reset(deck_id, slide)
            return deck
    raise HTTPException(status_code=404, detail="Slide not found")


@router.get("/decks/{deck_id}/export")
def export_deck(deck_id: str) -> FileResponse:
    try:
        deck = load_deck(deck_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    pptx_path = find_uploaded_pptx(deck_id)
    if pptx_path is None:
        raise HTTPException(status_code=404, detail="Original PPTX file not found")

    exported = export_deck_with_notes(deck, pptx_path)
    filename = f"{Path(deck.filename).stem}_slide-note.pptx"
    return FileResponse(
        exported,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )


@router.post("/decks/{deck_id}/render", response_model=Deck)
def render_deck(deck_id: str) -> Deck:
    try:
        deck = load_deck(deck_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    pptx_path = find_uploaded_pptx(deck_id)
    if pptx_path is None:
        raise HTTPException(status_code=404, detail="Original PPTX file not found")

    deck = render_deck_snapshots(deck, pptx_path)
    save_deck(deck)
    return deck


@router.post("/decks/{deck_id}/chat", response_model=ChatResponse)
def chat(deck_id: str, payload: ChatRequest) -> ChatResponse:
    try:
        deck = load_deck(deck_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    slide = next((item for item in deck.slides if item.id == payload.slide_id), None)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found")

    try:
        response = generate_note(
            slide,
            payload.instruction,
            [item.model_dump() for item in payload.messages],
            deck_context=build_memory_context(deck_id, slide.id),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return response
