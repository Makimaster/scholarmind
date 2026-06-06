from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from common.db.pg import AsyncSessionLocal


async def get_history(conversation_id: int, limit: int = 10) -> list[dict[str, str]]:
    """Load the latest conversation messages from PostgreSQL memory."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT role, content
                FROM messages
                WHERE conversation_id = :conversation_id
                ORDER BY created_at DESC, id DESC
                LIMIT :limit
                """
            ),
            {"conversation_id": conversation_id, "limit": limit},
        )
        rows = list(result.mappings())
    rows.reverse()
    return [{"role": str(row["role"]), "content": str(row["content"])} for row in rows]


async def save_message(
    conversation_id: int,
    role: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
) -> int:
    """Persist one conversation message and optional citation metadata."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                INSERT INTO messages (conversation_id, role, content, citations)
                VALUES (:conversation_id, :role, :content, CAST(:citations AS jsonb))
                RETURNING id
                """
            ),
            {
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "citations": json.dumps(citations if citations is not None else [], ensure_ascii=False),
            },
        )
        message_id = int(result.scalar_one())
        await session.commit()
        return message_id


async def get_or_create_conversation(
    user_id: int,
    title: str | None,
    folder_id: int | None = None,
    paper_ids: list[int] | None = None,
) -> int:
    """Get or create a conversation for a user.

    The current PostgreSQL schema does not store folder_id/paper_ids, so those
    parameters are accepted for API compatibility and future schema expansion.
    """
    del folder_id, paper_ids
    normalized_title = title or "新会话"
    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            text(
                """
                SELECT id
                FROM conversations
                WHERE user_id = :user_id AND title = :title
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id, "title": normalized_title},
        )
        conversation_id = existing.scalar_one_or_none()
        if conversation_id is not None:
            return int(conversation_id)

        created = await session.execute(
            text(
                """
                INSERT INTO conversations (user_id, title)
                VALUES (:user_id, :title)
                RETURNING id
                """
            ),
            {"user_id": user_id, "title": normalized_title},
        )
        new_id = int(created.scalar_one())
        await session.commit()
        return new_id
