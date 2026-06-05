"""
vectorizer: dense+sparse embeddings → Milvus bulk insert.

Dense:  embed_texts() from common/clients/llm.py
Sparse: rank-bm25 BM25Okapi, token hashed to uint32 space
"""
from __future__ import annotations

import json

import xxhash
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from common.clients.llm import embed_texts
from common.clients.milvus import bulk_insert, delete_by_paper
from common.config import settings
from common.logging import logger
from services.indexing.chunker import Chunk


def _tokenize(s: str) -> list[str]:
    return s.lower().split()


def _token_id(token: str) -> int:
    return xxhash.xxh32(token).intdigest() % (2**20)


def _bm25_sparse(chunks: list[Chunk]) -> list[dict[int, float]]:
    from rank_bm25 import BM25Okapi

    corpus = [_tokenize(c.content_en) for c in chunks]
    if not any(corpus):
        return [{} for _ in chunks]

    bm25 = BM25Okapi(corpus)
    sparse_vecs: list[dict[int, float]] = []
    for tokens in corpus:
        if not tokens:
            sparse_vecs.append({})
            continue
        scores = bm25.get_scores(tokens)
        vec: dict[int, float] = {}
        for token, score in zip(
            [t for doc in corpus for t in doc],
            scores,
        ):
            if score > 0:
                tid = _token_id(token)
                vec[tid] = max(vec.get(tid, 0.0), float(score))
        sparse_vecs.append(vec)
    return sparse_vecs


async def vectorize_and_store(
    chunks: list[Chunk],
    user_id: int,
    paper_id: int,
    folder_id: int | None,
    db: AsyncSession,
) -> None:
    if not chunks:
        return

    logger.info(f"[vectorizer] vectorizing {len(chunks)} chunks for paper_id={paper_id}")

    content_en_list = [c.content_en for c in chunks]
    dense_vecs = await embed_texts(content_en_list)
    sparse_vecs = _bm25_sparse(chunks)

    await delete_by_paper(user_id, paper_id)

    records: list[dict] = []
    for chunk, dense, sparse in zip(chunks, dense_vecs, sparse_vecs):
        chunk_id = xxhash.xxh64(chunk.content_en + str(paper_id)).hexdigest()
        records.append({
            "id":         chunk_id,
            "dense_vec":  dense,
            "sparse_vec": sparse if sparse else {0: 0.0},
            "content_en": chunk.content_en[:8192],
            "content_zh": (chunk.content_zh or "")[:4096],
            "user_id":    user_id,
            "paper_id":   paper_id,
            "folder_id":  folder_id if folder_id is not None else 0,
            "acl":        "",
            "chunk_type": chunk.block_type,
            "section":    (chunk.section or "")[:512],
            "page_num":   chunk.page_num or 0,
            "bbox":       json.dumps(chunk.bbox) if chunk.bbox else "",
            "block_id":   chunk.block_id or 0,
            "image_key":  chunk.image_key or "",
        })

    await bulk_insert(records)

    await db.execute(
        text("""
            UPDATE papers
            SET chunk_count = :count
            WHERE id = :paper_id AND user_id = :user_id
        """),
        {"count": len(records), "paper_id": paper_id, "user_id": user_id},
    )
    await db.commit()
    logger.info(f"[vectorizer] done: {len(records)} chunks, paper_id={paper_id}")
