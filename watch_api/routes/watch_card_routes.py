from fastapi import APIRouter, Query

from watch_api.schemas.watch_card_schema import WatchCardSchema, WatchSearchItemSchema
from watch_api.services.watch_card_service import (
    get_card_by_model_id,
    get_card_by_name,
    search_cards,
)


router = APIRouter(prefix="/api/watch-card", tags=["watch-card"])


# Short search payload for autocomplete, QA checks, and not-found suggestions.
@router.get("/search", response_model=list[WatchSearchItemSchema])
def search_watch_cards(
    q: str | None = Query(default=None, description="Search text"),
    brand: str | None = Query(default=None, description="Optional brand filter"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    return search_cards(q=q, brand=brand, limit=limit)


# Human-friendly lookup used by the demo UI after it detects brand and model name.
@router.get("/by-name", response_model=WatchCardSchema)
def get_watch_card_by_name(brand: str, normalized_name: str) -> dict:
    return get_card_by_name(brand=brand, normalized_name=normalized_name)


# Direct lookup is useful for internal tools where the model id is already known.
@router.get("/{model_id}", response_model=WatchCardSchema)
def get_watch_card(model_id: int) -> dict:
    return get_card_by_model_id(model_id)
