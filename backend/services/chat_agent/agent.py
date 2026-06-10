from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import text

from common.clients.llm import chat_complete, chat_complete_json
from common.config import rag_flag, settings
from common.db.mysql import AsyncSessionLocal as MySQLSessionLocal
from common.logging import logger
from common.prompts import load_prompt, render_prompt
from services.chat_agent import memory
from services.retrieval import Chunk, RetrievalScope, retrieve
from services.retrieval.query_optimizer import optimize_query



def sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def history_to_text(history: list[dict[str, str]]) -> str:
    return "\n".join(f"{item.get('role', 'message')}: {item.get('content', '')}" for item in history)


def build_scope(user_id: int, scope_type: str, folder_id: int | None, paper_ids: list[int] | None) -> RetrievalScope:
    if scope_type == "papers":
        return RetrievalScope(user_id=user_id, paper_ids=paper_ids or [])
    if scope_type == "folder":
        return RetrievalScope(user_id=user_id, folder_id=folder_id)
    return RetrievalScope(user_id=user_id)


async def route_intent(question: str, history: list[dict[str, str]]) -> str:
    if not rag_flag("ENABLE_INTENT_ROUTER"):
        return "knowledge"
    prompt = render_prompt(load_prompt("intent_router"), question=question, history=history_to_text(history))
    try:
        data = await chat_complete_json(prompt, max_tokens=256)
        intent = str(data.get("intent") or "knowledge").lower()
        if intent in {"chitchat", "knowledge", "complex", "followup"}:
            return intent
    except Exception as exc:  # noqa: BLE001 - routing failure should degrade to RAG.
        logger.warning(f"[chat_agent] intent routing failed: {exc}")
    return "knowledge"


async def _paper_titles(user_id: int, paper_ids: set[int]) -> dict[int, str]:
    if not paper_ids:
        return {}
    sorted_ids = sorted(paper_ids)
    placeholders = ", ".join(f":paper_id_{index}" for index, _ in enumerate(sorted_ids))
    params: dict[str, Any] = {"user_id": user_id}
    params.update({f"paper_id_{index}": paper_id for index, paper_id in enumerate(sorted_ids)})
    async with MySQLSessionLocal() as session:
        result = await session.execute(
            text(
                f"""
                SELECT id, title
                FROM papers
                WHERE user_id = :user_id AND id IN ({placeholders})
                """
            ),
            params,
        )
        return {int(row["id"]): str(row["title"]) for row in result.mappings()}


async def chunks_to_citations(chunks: list[Chunk], user_id: int) -> list[dict[str, Any]]:
    titles = await _paper_titles(user_id, {chunk.paper_id for chunk in chunks if chunk.paper_id})
    citations: list[dict[str, Any]] = []
    for chunk in chunks:
        page = chunk.page_num or 0
        citations.append(
            {
                "paper_id": chunk.paper_id,
                "paper_title": titles.get(chunk.paper_id, f"Paper {chunk.paper_id}"),
                "page": page,
                "page_num": page,
                "chunk_id": chunk.id,
                "bbox": chunk.bbox or "",
                "chunk_type": chunk.chunk_type,
                "content": chunk.content_en or chunk.content_zh,
                "image_key": chunk.image_key,
            }
        )
    return citations


def chunks_to_context(chunks: list[Chunk], citations: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, (chunk, citation) in enumerate(zip(chunks, citations), start=1):
        content = (chunk.content_zh or chunk.content_en or "")[:2500]
        lines.append(
            f"[{index}] paper_id={chunk.paper_id}; title={citation['paper_title']}; "
            f"page={chunk.page_num}; type={chunk.chunk_type}; section={chunk.section or ''}\n{content}"
        )
    return "\n\n".join(lines)


async def _save_query_log(
    *,
    user_id: int,
    conversation_id: int | None,
    question: str,
    rewritten_query: str | None,
    chunks: list[Chunk],
    latency_ms: int,
    answer: str,
) -> int | None:
    """Write query_log and return the inserted id for precise feedback binding."""
    try:
        async with MySQLSessionLocal() as session:
            result = await session.execute(
                text(
                    """
                    INSERT INTO query_logs (
                        user_id, conversation_id, question, rewritten_query, retrieved_chunk_ids,
                        top_k, latency_ms, prompt_tokens, completion_tokens
                    ) VALUES (
                        :user_id, :conversation_id, :question, :rewritten_query, :retrieved_chunk_ids,
                        :top_k, :latency_ms, :prompt_tokens, :completion_tokens
                    )
                    """
                ),
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "question": question,
                    "rewritten_query": rewritten_query,
                    "retrieved_chunk_ids": json.dumps([chunk.id for chunk in chunks], ensure_ascii=False),
                    "top_k": len(chunks),
                    "latency_ms": latency_ms,
                    "prompt_tokens": max(1, len(question) // 2),
                    "completion_tokens": max(1, len(answer) // 2),
                },
            )
            await session.commit()
            return int(result.lastrowid) if result.lastrowid else None
    except Exception as exc:  # noqa: BLE001 - logging failure must not break SSE response.
        logger.warning(f"[chat_agent] query log write failed: {exc}")
        return None


async def _yield_text(text: str) -> AsyncGenerator[str, None]:
    step = 8
    for index in range(0, len(text), step):
        yield sse_event("token", {"delta": text[index : index + step]})


async def _direct_answer(question: str, history: list[dict[str, str]]) -> str:
    prompt = f"对话历史：\n{history_to_text(history)}\n\n用户问题：{question}\n\n请用中文简洁回答。"
    return await chat_complete(prompt, max_tokens=1024)


async def _self_rag_reflect(answer: str, context: str) -> str:
    """Run self-RAG reflection to filter unsupported claims; returns revised answer."""
    try:
        from common.prompts import load_prompt, render_prompt
        from common.clients.llm import chat_complete_json
        prompt = render_prompt(load_prompt("self_rag_reflect"), answer=answer, context=context[:6000])
        data = await chat_complete_json(prompt, max_tokens=settings.LLM_MAX_TOKENS)
        if isinstance(data, dict):
            revised = data.get("revised_answer")
            if revised and str(revised).strip():
                return str(revised).strip()
    except Exception as exc:  # noqa: BLE001 - self-rag failure must not break the SSE stream.
        logger.warning(f"[chat_agent] self_rag_reflect failed: {exc}")
    return answer


async def _rag_answer(
    question: str,
    history: list[dict[str, str]],
    scope: RetrievalScope,
) -> tuple[str, list[Chunk], list[dict[str, Any]], str | None]:
    query_bundle = await optimize_query(question, history)
    chunks = await retrieve(question, scope, conversation_history=history, query_bundle=query_bundle)
    citations = await chunks_to_citations(chunks, scope.user_id)
    context = chunks_to_context(chunks, citations)
    prompt = render_prompt(
        load_prompt("answer_with_citation"),
        question=question,
        history=history_to_text(history),
        context=context,
    )
    answer = await chat_complete(prompt, max_tokens=settings.LLM_MAX_TOKENS)
    if rag_flag("ENABLE_SELF_RAG_REFLECT"):
        answer = await _self_rag_reflect(answer, context)
    return answer, chunks, citations, query_bundle.rewritten


async def stream_chat_query(
    *,
    question: str,
    user_id: int,
    conversation_id: int,
    scope_type: str = "all",
    folder_id: int | None = None,
    paper_ids: list[int] | None = None,
) -> AsyncGenerator[str, None]:
    started = time.perf_counter()
    history = await memory.get_history(user_id, conversation_id, limit=10)
    intent = await route_intent(question, history)
    scope = build_scope(user_id, scope_type, folder_id, paper_ids)
    chunks: list[Chunk] = []
    citations: list[dict[str, Any]] = []
    answer = ""
    rewritten_query: str | None = None

    try:
        if intent == "complex":
            from services.chat_agent.reviewer import generate_review

            async for event in generate_review(question, scope, user_id, conversation_id=conversation_id):
                yield event
            return

        if intent == "chitchat":
            answer = await _direct_answer(question, history)
        else:
            answer, chunks, citations, rewritten_query = await _rag_answer(question, history, scope)
            for citation in citations:
                yield sse_event("cite", citation)

        async for token_event in _yield_text(answer):
            yield token_event

        latency_ms = int((time.perf_counter() - started) * 1000)
        await memory.save_message(user_id, conversation_id, "user", question)
        await memory.save_message(user_id, conversation_id, "assistant", answer, citations=citations)
        query_log_id = await _save_query_log(
            user_id=user_id,
            conversation_id=conversation_id,
            question=question,
            rewritten_query=rewritten_query,
            chunks=chunks,
            latency_ms=latency_ms,
            answer=answer,
        )
        yield sse_event("done", {"latency_ms": latency_ms, "intent": intent, "query_log_id": query_log_id})
    except Exception as exc:  # noqa: BLE001 - convert failures to SSE error + done.
        logger.exception(f"[chat_agent] chat query failed: {exc}")
        latency_ms = int((time.perf_counter() - started) * 1000)
        fallback = "检索或生成过程中出现错误，请稍后重试或缩小检索范围。"
        await memory.save_message(user_id, conversation_id, "user", question)
        await memory.save_message(user_id, conversation_id, "assistant", fallback, citations=[])
        yield sse_event("error", {"msg": str(exc)})
        yield sse_event("token", {"delta": fallback})
        yield sse_event("done", {"latency_ms": latency_ms, "error": str(exc)})


__all__ = [
    "build_scope",
    "chunks_to_citations",
    "chunks_to_context",
    "route_intent",
    "sse_event",
    "stream_chat_query",
]
