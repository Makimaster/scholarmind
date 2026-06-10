from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from typing import Any

from common.clients.llm import chat_complete, chat_complete_json
from common.config import settings
from common.logging import logger
from services.chat_agent import memory
from services.retrieval import Chunk, RetrievalScope, retrieve
from services.retrieval.query_optimizer import _load_prompt, _render_prompt
from services.chat_agent.agent import chunks_to_citations, chunks_to_context, sse_event


async def _split_topic(topic: str) -> list[str]:
    prompt = (
        "你是学术综述规划助手。请把用户综述主题拆成 3-5 个可检索的子问题。"
        "只输出 JSON：{\"questions\":[\"...\"]}\n\n"
        f"主题：{topic}"
    )
    try:
        data = await chat_complete_json(prompt, max_tokens=512)
        questions = data.get("questions") if isinstance(data, dict) else None
        if isinstance(questions, list):
            cleaned = [str(item).strip() for item in questions if str(item).strip()]
            if cleaned:
                return cleaned[:5]
    except Exception as exc:  # noqa: BLE001 - topic splitting can degrade to original topic.
        logger.warning(f"[reviewer] topic split failed: {exc}")
    return [topic]


def _dedupe_chunks(groups: list[list[Chunk]], limit: int = 12) -> list[Chunk]:
    seen: set[str] = set()
    merged: list[Chunk] = []
    for chunks in groups:
        for chunk in chunks:
            if chunk.id in seen:
                continue
            seen.add(chunk.id)
            merged.append(chunk)
            if len(merged) >= limit:
                return merged
    return merged


async def generate_review(
    topic: str,
    scope: RetrievalScope,
    user_id: int,
    conversation_id: int | None = None,
) -> AsyncGenerator[str, None]:
    """Generate an agentic literature review as SSE events."""
    started = time.perf_counter()
    try:
        subquestions = await _split_topic(topic)
        retrieved_groups = await asyncio_gather_retrieve(subquestions, scope)
        chunks = _dedupe_chunks(retrieved_groups)
        citations = await chunks_to_citations(chunks, user_id)

        for citation in citations:
            yield sse_event("cite", citation)

        prompt = _render_prompt(
            _load_prompt("review_generation"),
            topic=topic,
            papers_context=chunks_to_context(chunks, citations),
            min_citations=min(3, max(1, len(citations))),
        )
        answer = await chat_complete(prompt, model=settings.LLM_REASON_MODEL, max_tokens=settings.LLM_MAX_TOKENS)
        for index in range(0, len(answer), 8):
            yield sse_event("token", {"delta": answer[index : index + 8]})

        latency_ms = int((time.perf_counter() - started) * 1000)
        if conversation_id is not None:
            await memory.save_message(user_id, conversation_id, "user", topic)
            await memory.save_message(user_id, conversation_id, "assistant", answer, citations=citations)
        yield sse_event("done", {"latency_ms": latency_ms, "subquestions": subquestions})
    except Exception as exc:  # noqa: BLE001 - keep SSE contract on failure.
        logger.exception(f"[reviewer] review generation failed: {exc}")
        latency_ms = int((time.perf_counter() - started) * 1000)
        fallback = "综述生成过程中出现错误，请稍后重试或缩小范围。"
        if conversation_id is not None:
            await memory.save_message(user_id, conversation_id, "user", topic)
            await memory.save_message(user_id, conversation_id, "assistant", fallback, citations=[])
        yield sse_event("token", {"delta": fallback})
        yield sse_event("done", {"latency_ms": latency_ms, "error": str(exc)})


async def asyncio_gather_retrieve(subquestions: list[str], scope: RetrievalScope) -> list[list[Chunk]]:
    import asyncio

    results = await asyncio.gather(
        *(retrieve(question, scope) for question in subquestions),
        return_exceptions=True,
    )
    groups: list[list[Chunk]] = []
    for question, result in zip(subquestions, results):
        if isinstance(result, Exception):
            logger.warning(f"[reviewer] retrieval failed question={question}: {result}")
            groups.append([])
        else:
            groups.append(result)
    return groups


__all__ = ["generate_review"]
