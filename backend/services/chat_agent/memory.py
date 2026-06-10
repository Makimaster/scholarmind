from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from common.db.pg import AsyncSessionLocal


async def get_history(user_id: int, conversation_id: int, limit: int = 10) -> list[dict[str, str]]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT m.role, m.content
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.conversation_id = :conversation_id AND c.user_id = :user_id
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT :limit
                """
            ),
            {"user_id": user_id, "conversation_id": conversation_id, "limit": limit},
        )
        rows = list(result.mappings())
    rows.reverse()
    return [{"role": str(row["role"]), "content": str(row["content"])} for row in rows]


async def save_message(
    user_id: int,
    conversation_id: int,
    role: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
) -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                INSERT INTO messages (conversation_id, role, content, citations)
                SELECT :conversation_id, :role, :content, CAST(:citations AS jsonb)
                WHERE EXISTS (
                    SELECT 1 FROM conversations
                    WHERE id = :conversation_id AND user_id = :user_id
                )
                RETURNING id
                """
            ),
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "citations": json.dumps(citations if citations is not None else [], ensure_ascii=False),
            },
        )
        message_id = result.scalar_one_or_none()
        if message_id is None:
            await session.rollback()
            raise RuntimeError(f"conversation not found: conversation_id={conversation_id} user_id={user_id}")
        await session.execute(
            text("UPDATE conversations SET updated_at = now() WHERE id = :conversation_id AND user_id = :user_id"),
            {"conversation_id": conversation_id, "user_id": user_id},
        )
        await session.commit()
        return int(message_id)


async def get_or_create_conversation(
    user_id: int,
    title: str | None,
    folder_id: int | None = None,
    paper_ids: list[int] | None = None,
) -> int:
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
