"""
Query optimization for retrieval: rewrite, translation, and HyDE.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.clients.llm import chat_complete
from common.config import settings
from common.logging import logger
from common.prompts import load_prompt, render_prompt

@dataclass(frozen=True)
class QueryBundle:
    original: str
    rewritten: str
    translated_en: str
    hyde_doc: str




def _history_to_text(conversation_history: str | list | None) -> str:
    if conversation_history is None:
        return ""
    if isinstance(conversation_history, str):
        return conversation_history
    lines: list[str] = []
    for item in conversation_history:
        if isinstance(item, dict):
            role = item.get("role") or item.get("sender") or "message"
            content = item.get("content") or item.get("text") or ""
            lines.append(f"{role}: {content}")
        else:
            lines.append(str(item))
    return "\n".join(lines)


async def _safe_completion(label: str, prompt: str, fallback: str) -> str:
    try:
        text = await chat_complete(prompt, max_tokens=512)
        return text.strip() or fallback
    except Exception as exc:  # noqa: BLE001 - retrieval optimization must degrade gracefully.
        logger.warning(f"[retrieval] query optimization step failed label={label}: {exc}")
        return fallback


async def optimize_query(
    question: str,
    conversation_history: str | list | None = None,
) -> QueryBundle:
    """Optimize a user question into rewrite, English translation, and HyDE probe."""
    history = _history_to_text(conversation_history)

    async def rewrite() -> str:
        if not settings.ENABLE_QUERY_REWRITE:
            return question
        prompt = render_prompt(load_prompt("query_rewrite"), question=question, history=history)
        return await _safe_completion("rewrite", prompt, question)

    async def translate() -> str:
        if not settings.ENABLE_QUERY_TRANSLATION:
            return question
        prompt = render_prompt(load_prompt("query_translate"), question=question)
        return await _safe_completion("translate", prompt, question)

    async def hyde() -> str:
        if not settings.ENABLE_HYDE:
            return question
        prompt = render_prompt(load_prompt("hyde"), question=question)
        return await _safe_completion("hyde", prompt, question)

    rewritten, translated_en, hyde_doc = await asyncio.gather(rewrite(), translate(), hyde())
    return QueryBundle(
        original=question,
        rewritten=rewritten,
        translated_en=translated_en,
        hyde_doc=hyde_doc,
    )
