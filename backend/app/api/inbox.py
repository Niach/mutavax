from fastapi import APIRouter
from pydantic import BaseModel

from app.runtime import get_inbox_root
from app.services.inbox import list_inbox


router = APIRouter(prefix="/api/inbox", tags=["inbox"])


class InboxEntryResponse(BaseModel):
    name: str
    path: str
    size_bytes: int
    modified_at: str
    kind: str


class InboxListResponse(BaseModel):
    root: str
    entries: list[InboxEntryResponse]


@router.get("", response_model=InboxListResponse)
async def get_inbox():
    entries = list_inbox()
    return InboxListResponse(
        root=str(get_inbox_root()),
        entries=[InboxEntryResponse(**entry.__dict__) for entry in entries],
    )
