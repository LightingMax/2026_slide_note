from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.deck import ChatRequest, ChatResponse, Deck, NoteUpdate
from app.services.ark_client import generate_note
from app.services.ppt_parser import parse_pptx
from app.services.storage import list_decks, load_deck, save_deck

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/decks", response_model=list[Deck])
def get_decks() -> list[Deck]:
    return list_decks()


@router.get("/decks/{deck_id}", response_model=Deck)
def get_deck(deck_id: str) -> Deck:
    try:
        return load_deck(deck_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc


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
            return deck
    raise HTTPException(status_code=404, detail="Slide not found")


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
        text = generate_note(slide, payload.instruction, [item.model_dump() for item in payload.messages])
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChatResponse(text=text)
