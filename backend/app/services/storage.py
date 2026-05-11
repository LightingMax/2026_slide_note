import json
from pathlib import Path

from app.core.config import get_settings
from app.models.deck import Deck


def _deck_path(deck_id: str) -> Path:
    return get_settings().data_dir / f"{deck_id}.json"


def save_deck(deck: Deck) -> None:
    _deck_path(deck.id).write_text(deck.model_dump_json(indent=2), encoding="utf-8")


def load_deck(deck_id: str) -> Deck:
    path = _deck_path(deck_id)
    if not path.exists():
        raise FileNotFoundError(deck_id)
    return Deck.model_validate(json.loads(path.read_text(encoding="utf-8")))


def list_decks() -> list[Deck]:
    decks: list[Deck] = []
    for path in sorted(get_settings().data_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        decks.append(Deck.model_validate(json.loads(path.read_text(encoding="utf-8"))))
    return decks

