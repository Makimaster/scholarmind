from __future__ import annotations

import json
from datetime import datetime
from typing import Any, List

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.schemas.chat import (
    ChatQueryRequest,
    CitationResponse,
    ConversationCreate,
    ConversationResponse,
    FeedbackRequest,
    FeedbackResponse,
    MessageResponse,
)
from common.db.mysql import AsyncSessionLocal as MySQLSessionLocal
from common.db.pg import AsyncSessionLocal as PGSessionLocal
from app.deps import CurrentUserId
from services.chat_agent.agent import stream_chat_query
from services.chat_agent.memory import get_or_create_conversation

router = APIRouter(prefix="/chat", tags=["chat"])


def _citation_response(item: dict[str, Any]) -> CitationResponse:
    page = int(item.get("page") or item.get("page_num") or 0)
    return CitationResponse(
        paper_id=int(item.get("paper_id") or 0),
        paper_title=str(item.get("paper_title") or ""),
        page=page,
        page_num=page,
        chunk_id=str(item.get("chunk_id") or ""),
        bbox=str(item.get("bbox") or ""),
        chunk_type=str(item.get("chunk_type") or "text"),
        content=str(item.get("content") or ""),
        image_key=item.get("image_key"),
    )


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新建对话",
    description="创建一个新的对话会话，可绑定文件夹或指定论文范围（当前 PG schema 暂不持久化 scope）。",
)
async def create_conversation(data: ConversationCreate, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    conversation_id = await get_or_create_conversation(
        user_id,
        data.title or "新会话",
        data.folder_id,
        data.paper_ids,
    )
    async with PGSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                WHERE id = :id AND user_id = :user_id
                """
            ),
            {"id": conversation_id, "user_id": user_id},
        )
        row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationResponse(
        id=int(row["id"]),
        title=str(row["title"] or "新会话"),
        folder_id=data.folder_id,
        paper_ids=data.paper_ids or [],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get(
    "/conversations",
    response_model=List[ConversationResponse],
    summary="对话列表",
    description="获取当前用户的所有对话会话，按更新时间倒序排列。",
)
async def list_conversations(user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with PGSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                WHERE user_id = :user_id
                ORDER BY updated_at DESC, id DESC
                """
            ),
            {"user_id": user_id},
        )
        rows = result.mappings().all()
    return [
        ConversationResponse(
            id=int(row["id"]),
            title=str(row["title"] or "新会话"),
            folder_id=None,
            paper_ids=[],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


@router.get(
    "/conversations/{id}/messages",
    response_model=List[MessageResponse],
    summary="对话历史消息",
    description="获取指定会话的完整消息历史，每条 assistant 消息包含引用溯源信息。",
)
async def list_messages(id: int, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with PGSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT m.id, m.conversation_id, m.role, m.content, m.citations, m.created_at
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.conversation_id = :conversation_id AND c.user_id = :user_id
                ORDER BY m.created_at ASC, m.id ASC
                """
            ),
            {"conversation_id": id, "user_id": user_id},
        )
        rows = result.mappings().all()
    messages: list[MessageResponse] = []
    for row in rows:
        raw_citations = row["citations"] or []
        if isinstance(raw_citations, str):
            raw_citations = json.loads(raw_citations)
        messages.append(
            MessageResponse(
                id=int(row["id"]),
                conversation_id=int(row["conversation_id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                citations=[_citation_response(item) for item in raw_citations],
                created_at=row["created_at"],
            )
        )
    return messages


@router.post(
    "/query",
    summary="论文问答（SSE 流式）",
    description="意图路由 → RAG/Agent → cite/token/done SSE 输出，并在生成完成后落盘。",
)
async def chat_query(request: ChatQueryRequest, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    return StreamingResponse(
        stream_chat_query(
            question=request.question,
            user_id=user_id,
            conversation_id=request.conversation_id,
            scope_type=request.scope_type,
            folder_id=request.folder_id,
            paper_ids=request.paper_ids,
        ),
        media_type="text/event-stream",
    )


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    summary="答案反馈（点赞/踩）",
    description="对 assistant 回答进行正负反馈，后续用于更新 query_logs。",
)
async def message_feedback(data: FeedbackRequest, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with PGSessionLocal() as session:
        exists = await session.execute(
            text(
                """
                SELECT m.id, m.conversation_id
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.id = :id AND c.user_id = :user_id
                """
            ),
            {"id": data.message_id, "user_id": user_id},
        )
        message = exists.mappings().first()
        if message is None:
            raise HTTPException(status_code=404, detail="Message not found")

    feedback = 1 if data.is_positive else -1
    async with MySQLSessionLocal() as session:
        if data.query_log_id is not None:
            # Precise binding: update the exact query_log row the client knows about.
            result = await session.execute(
                text(
                    "UPDATE query_logs SET feedback = :feedback "
                    "WHERE id = :id AND user_id = :user_id"
                ),
                {"feedback": feedback, "id": data.query_log_id, "user_id": user_id},
            )
        else:
            # Fallback: update the most recent query_log in this conversation.
            result = await session.execute(
                text(
                    """
                    UPDATE query_logs
                    SET feedback = :feedback
                    WHERE user_id = :user_id
                      AND conversation_id = :conversation_id
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {"feedback": feedback, "user_id": user_id, "conversation_id": int(message["conversation_id"])},
            )
        await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Query log not found")
    return FeedbackResponse(status="success", message="Feedback received.")
