"""
Hybrid retrieval pipeline: cache, Milvus search, RRF fusion, rerank, and quality control.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from common.clients.llm import embed_texts
from common.clients.milvus import dense_search
from common.clients.redis import redis_get_json, redis_set_json
from common.config import settings
from common.logging import logger
from services.retrieval.query_optimizer import QueryBundle, optimize_query

RRF_K = 60
DEFAULT_RETRIEVAL_CACHE_TTL_SECONDS = 300
MIN_CORRECTIVE_CHUNKS = 3


class RetrievalQualityException(Exception):
    """Raised when retrieved evidence is insufficient after one retry."""


@dataclass(frozen=True)
class RetrievalScope:
    user_id: int
    folder_id: int | None = None
    paper_ids: list[int] | None = None


@dataclass
class Chunk:
    id: str
    content_en: str
    content_zh: str
    user_id: int
    paper_id: int
    folder_id: int | None
    chunk_type: str
    section: str | None
    page_num: int | None
    bbox: str | None
    block_id: int | None
    image_key: str | None
    score: float = 0.0
    rerank_score: float | None = None
    source_scores: dict[str, float] = field(default_factory=dict)


def build_scope_filter(scope: RetrievalScope) -> str:
    """Build a tenant-safe Milvus scalar filter."""
    if not isinstance(scope.user_id, int) or scope.user_id <= 0:
        raise ValueError("RetrievalScope.user_id must be a positive integer")

    expr = f"user_id == {scope.user_id}"
    if scope.paper_ids:
        paper_ids = sorted({int(pid) for pid in scope.paper_ids if int(pid) > 0})
        if not paper_ids:
            raise ValueError("RetrievalScope.paper_ids must contain positive integers")
        expr += f" && paper_id in {paper_ids}"
    elif scope.folder_id is not None:
        folder_id = int(scope.folder_id)
        if folder_id <= 0:
            raise ValueError("RetrievalScope.folder_id must be a positive integer")
        expr += f" && folder_id == {folder_id}"
    return expr


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def _scope_payload(scope: RetrievalScope) -> dict[str, Any]:
    return {
        "user_id": scope.user_id,
        "folder_id": scope.folder_id,
        "paper_ids": sorted(scope.paper_ids or []),
    }


def _cache_key(query: str, scope: RetrievalScope, top_k: int) -> str:
    payload = {
        "query": _normalize_query(query),
        "scope": _scope_payload(scope),
        "top_k": top_k,
        "rerank_top_n": settings.RERANK_TOP_N,
        "flags": {
            "rewrite": settings.ENABLE_QUERY_REWRITE,
            "translation": settings.ENABLE_QUERY_TRANSLATION,
            "hyde": settings.ENABLE_HYDE,
            "rerank": settings.ENABLE_RERANK,
            "corrective": settings.ENABLE_CORRECTIVE_RAG,
        },
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"retrieval:v3:{scope.user_id}:{digest}"


def _chunk_from_hit(hit: dict[str, Any], score: float, source_label: str) -> Chunk:
    return Chunk(
        id=str(hit.get("id") or ""),
        content_en=str(hit.get("content_en") or ""),
        content_zh=str(hit.get("content_zh") or ""),
        user_id=int(hit.get("user_id") or 0),
        paper_id=int(hit.get("paper_id") or 0),
        folder_id=int(hit.get("folder_id") or 0) or None,
        chunk_type=str(hit.get("chunk_type") or "text"),
        section=str(hit.get("section") or "") or None,
        page_num=int(hit.get("page_num") or 0) or None,
        bbox=str(hit.get("bbox") or "") or None,
        block_id=int(hit.get("block_id") or 0) or None,
        image_key=str(hit.get("image_key") or "") or None,
        score=score,
        source_scores={source_label: float(hit.get("score") or 0.0)},
    )


def _chunk_from_cache(item: dict[str, Any]) -> Chunk:
    source_scores = item.get("source_scores") or {}
    return Chunk(
        id=str(item.get("id") or ""),
        content_en=str(item.get("content_en") or ""),
        content_zh=str(item.get("content_zh") or ""),
        user_id=int(item.get("user_id") or 0),
        paper_id=int(item.get("paper_id") or 0),
        folder_id=item.get("folder_id"),
        chunk_type=str(item.get("chunk_type") or "text"),
        section=item.get("section"),
        page_num=item.get("page_num"),
        bbox=item.get("bbox"),
        block_id=item.get("block_id"),
        image_key=item.get("image_key"),
        score=float(item.get("score") or 0.0),
        rerank_score=item.get("rerank_score"),
        source_scores={str(k): float(v) for k, v in source_scores.items()},
    )


async def _cache_get(key: str) -> list[Chunk] | None:
    try:
        data = await redis_get_json(key)
        if not data:
            return None
        chunks = [_chunk_from_cache(item) for item in data.get("chunks", [])]
        logger.info(f"[retrieval] cache hit key={key} chunks={len(chunks)}")
        return chunks
    except Exception as exc:  # noqa: BLE001 - cache failure must not break retrieval.
        logger.warning(f"[retrieval] cache get failed key={key}: {exc}")
        return None


async def _cache_set(key: str, chunks: list[Chunk]) -> None:
    try:
        payload = {"chunks": [asdict(chunk) for chunk in chunks]}
        await redis_set_json(key, payload, DEFAULT_RETRIEVAL_CACHE_TTL_SECONDS)
        logger.info(f"[retrieval] cache write key={key} chunks={len(chunks)}")
    except Exception as exc:  # noqa: BLE001 - cache failure must not break retrieval.
        logger.warning(f"[retrieval] cache set failed key={key}: {exc}")


async def _dense_route(query_text: str, scope: RetrievalScope, top_k: int, label: str) -> list[dict[str, Any]]:
    filter_expr = build_scope_filter(scope)
    if "user_id" not in filter_expr:
        raise ValueError("Milvus search filter must include user_id")
    vectors = await embed_texts([query_text])
    if not vectors:
        return []
    hits = await dense_search(vectors[0], filter_expr, top_k)
    logger.info(f"[retrieval] route={label} hits={len(hits)} filter={filter_expr}")
    return hits


def _rrf_fuse(route_hits: dict[str, list[dict[str, Any]]], top_k: int) -> list[Chunk]:
    fused: dict[str, Chunk] = {}
    for label, hits in route_hits.items():
        for rank, hit in enumerate(hits, start=1):
            chunk_id = str(hit.get("id") or "")
            if not chunk_id:
                continue
            rrf_score = 1.0 / (RRF_K + rank)
            if chunk_id not in fused:
                fused[chunk_id] = _chunk_from_hit(hit, rrf_score, label)
            else:
                fused[chunk_id].score += rrf_score
                fused[chunk_id].source_scores[label] = float(hit.get("score") or 0.0)
    return sorted(fused.values(), key=lambda chunk: chunk.score, reverse=True)[:top_k]


async def hybrid_search(query_bundle: QueryBundle, scope: RetrievalScope, top_k: int) -> list[Chunk]:
    """Run three concurrent dense retrieval routes and fuse them with RRF."""
    results = await asyncio.gather(
        _dense_route(query_bundle.translated_en, scope, top_k, "en_dense"),
        _dense_route(query_bundle.rewritten, scope, top_k, "zh_dense"),
        _dense_route(query_bundle.hyde_doc, scope, top_k, "hyde_dense"),
        return_exceptions=True,
    )

    labels = ["en_dense", "zh_dense", "hyde_dense"]
    route_hits: dict[str, list[dict[str, Any]]] = {}
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            logger.warning(f"[retrieval] route failed label={label}: {result}")
            route_hits[label] = []
        else:
            route_hits[label] = result

    if not any(route_hits.values()):
        logger.warning("[retrieval] all search routes returned no hits")
    fused = _rrf_fuse(route_hits, top_k)
    logger.info(f"[retrieval] RRF fused candidates={len(fused)}")
    return fused


async def _retrieve_once(
    query: str,
    scope: RetrievalScope,
    top_k: int,
    conversation_history: str | list | None = None,
    query_bundle: QueryBundle | None = None,
) -> list[Chunk]:
    from services.retrieval.reranker import corrective_grade, rerank_chunks

    bundle = query_bundle or await optimize_query(query, conversation_history)
    candidates = await hybrid_search(bundle, scope, top_k)
    reranked = await rerank_chunks(bundle.rewritten or query, candidates, settings.RERANK_TOP_N)
    return await corrective_grade(query, reranked)


async def retrieve(
    query: str,
    scope: RetrievalScope,
    top_k: int | None = None,
    conversation_history: str | list | None = None,
    _retry_used: bool = False,
    query_bundle: QueryBundle | None = None,
) -> list[Chunk]:
    """Retrieve top chunks for a question within a tenant-safe scope."""
    top_k = top_k or settings.RETRIEVAL_TOP_K
    build_scope_filter(scope)

    key = _cache_key(query, scope, top_k)
    if not _retry_used:
        cached = await _cache_get(key)
        if cached is not None:
            return cached
        logger.info(f"[retrieval] cache miss key={key}")

    chunks = await _retrieve_once(query, scope, top_k, conversation_history, query_bundle=query_bundle)

    if settings.ENABLE_CORRECTIVE_RAG and len(chunks) < MIN_CORRECTIVE_CHUNKS:
        if _retry_used:
            raise RetrievalQualityException("Retrieved evidence is insufficient after one retry")
        logger.info("[retrieval] corrective retry triggered")
        retry_bundle = await optimize_query(query, conversation_history)
        retry_query = retry_bundle.rewritten or retry_bundle.translated_en or query
        chunks = await retrieve(
            retry_query,
            scope,
            top_k=top_k,
            conversation_history=conversation_history,
            _retry_used=True,
        )
        if len(chunks) < MIN_CORRECTIVE_CHUNKS:
            raise RetrievalQualityException("Retrieved evidence is insufficient after one retry")

    if not _retry_used:
        await _cache_set(key, chunks)
    return chunks
