"""
Reranking and Corrective RAG grading for retrieved chunks.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from common.clients.llm import chat_complete_json, rerank
from common.config import settings
from common.logging import logger
from common.prompts import load_prompt, render_prompt

if TYPE_CHECKING:
    from services.retrieval.searcher import Chunk


def _chunk_document(chunk: "Chunk") -> str:
    parts = []
    if chunk.section:
        parts.append(f"Section: {chunk.section}")
    if chunk.content_zh:
        parts.append(chunk.content_zh)
    if chunk.content_en and chunk.content_en != chunk.content_zh:
        parts.append(chunk.content_en)
    return "\n".join(parts).strip()


async def rerank_chunks(
    question: str,
    chunks: list["Chunk"],
    top_n: int | None = None,
) -> list["Chunk"]:
    """Rerank candidate chunks with the configured reranker service."""
    top_n = top_n or settings.RERANK_TOP_N
    if not chunks:
        return []
    if not settings.ENABLE_RERANK:
        return chunks[:top_n]

    documents = [_chunk_document(chunk) for chunk in chunks]
    try:
        ranked = await rerank(question, documents, top_n=top_n)
    except Exception as exc:  # noqa: BLE001 - rerank failure should fall back to RRF order.
        logger.warning(f"[retrieval] rerank failed, fallback to RRF order: {exc}")
        return chunks[:top_n]

    ordered: list[Chunk] = []
    seen: set[int] = set()
    for item in ranked:
        index = item.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(chunks) or index in seen:
            logger.warning(f"[retrieval] invalid rerank index ignored: {item}")
            continue
        chunk = chunks[index]
        chunk.rerank_score = float(item.get("score", 0.0) or 0.0)
        ordered.append(chunk)
        seen.add(index)

    if len(ordered) < top_n:
        for index, chunk in enumerate(chunks):
            if index not in seen:
                ordered.append(chunk)
            if len(ordered) >= top_n:
                break
    return ordered[:top_n]


def _grade_to_score(data: Any) -> float:
    if not isinstance(data, dict):
        return 0.0
    raw_score = data.get("score")
    if isinstance(raw_score, int | float):
        return max(0.0, min(1.0, float(raw_score)))
    grade = str(data.get("grade", "")).lower()
    if grade == "sufficient":
        return 1.0
    if grade == "partial":
        return 0.6
    return 0.0


async def corrective_grade(question: str, chunks: list["Chunk"]) -> list["Chunk"]:
    """Grade chunks and filter low-quality evidence when Corrective RAG is enabled."""
    if not settings.ENABLE_CORRECTIVE_RAG or not chunks:
        return chunks

    prompt_template = load_prompt("corrective_grade")
    graded: list[Chunk] = []
    for chunk in chunks:
        context = _chunk_document(chunk)[:3000]
        prompt = render_prompt(prompt_template, question=question, context=context)
        try:
            data = await chat_complete_json(prompt, max_tokens=512)
            score = _grade_to_score(data)
            chunk.source_scores["corrective_grade"] = score
            if score >= 0.5:
                graded.append(chunk)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning(f"[retrieval] corrective grade parse failed for chunk={chunk.id}: {exc}")
            graded.append(chunk)
        except Exception as exc:  # noqa: BLE001 - grader failure should not break retrieval.
            logger.warning(f"[retrieval] corrective grade failed for chunk={chunk.id}: {exc}")
            graded.append(chunk)
    return graded
