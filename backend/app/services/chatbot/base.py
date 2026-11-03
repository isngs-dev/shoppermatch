"""Shared building blocks for the chatbot tool modules (kept separate so
tools.py and shopper_tools.py don't import each other)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ChatConversation, Invitation, User

MAX_ROWS = 15


@dataclass
class ChatScope:
    audience: str  # staff | shopper | visitor
    conversation: ChatConversation
    user: User | None = None
    invitation: Invitation | None = None
    # Collected by tools that want the UI to offer a button (e.g. navigate).
    ui_actions: list[dict] = field(default_factory=list)
    # Per-turn counters for the generic API tool (see api_tools.py).
    # The app page the user is looking at (staff chat only; sanitised in the router).
    page: str | None = None
    api_calls: int = 0
    api_writes: int = 0

    @property
    def is_admin(self) -> bool:
        return self.audience == "staff" and self.user is not None and self.user.role == "admin"

    @property
    def client_id(self) -> uuid.UUID | None:
        if self.audience == "staff" and self.user is not None and self.user.role == "client":
            return self.user.client_id
        return None


ToolHandler = Callable[[AsyncSession, ChatScope, dict], Awaitable[dict]]


def spec(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
        },
    }
