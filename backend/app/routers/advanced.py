from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.deps import CurrentUserId
from app.schemas.advanced import CitationEdge, CitationGraphResponse, CitationNode, ReviewGenerateRequest
from common.db.mysql import AsyncSessionLocal
from services.chat_agent.agent import build_scope
from services.chat_agent.reviewer import generate_review as generate_review_stream


router = APIRouter(tags=["advanced"])


@router.post(
    "/review/generate",
    summary="Agentic 文献综述生成（SSE 流式）",
    description="基于子问题分解与混合检索生成多文献综述，SSE 事件格式：cite → token → done。",
)
async def generate_review(request: ReviewGenerateRequest, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    scope = build_scope(user_id, request.scope_type, request.folder_id, request.paper_ids)
    return StreamingResponse(
        generate_review_stream(request.topic, scope, user_id),
        media_type="text/event-stream",
    )


@router.get(
    "/graph/citations",
    response_model=CitationGraphResponse,
    summary="论文引用关系图谱",
    description="返回论文间的引用网络（节点+有向边），可指定 `paper_id` 只返回与该论文相关的子图。前端用于渲染知识图谱可视化。",
)
async def get_citation_graph(paper_id: Optional[int] = None, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with AsyncSessionLocal() as session:
        # Build node set: papers with citations
        node_query = text("""
            SELECT DISTINCT p.id, p.title, p.authors, p.year
            FROM papers p
            WHERE p.user_id = :user_id AND (
                EXISTS (SELECT 1 FROM citations c WHERE c.src_paper_id = p.id)
                OR EXISTS (SELECT 1 FROM citations c WHERE c.dst_paper_id = p.id)
            )
        """)
        nodes_raw = await session.execute(node_query, {"user_id": user_id})
        node_rows = nodes_raw.mappings().all()

        paper_ids = [int(r["id"]) for r in node_rows]
        if not paper_ids:
            return CitationGraphResponse(nodes=[], edges=[])

        id_set = set(paper_ids)
        placeholders = ", ".join(f":paper_id_{index}" for index, _ in enumerate(paper_ids))
        params = {f"paper_id_{index}": paper_id_value for index, paper_id_value in enumerate(paper_ids)}
        edges_raw = await session.execute(
            text(f"""
                SELECT c.src_paper_id, c.dst_paper_id
                FROM citations c
                WHERE c.src_paper_id IN ({placeholders}) AND c.dst_paper_id IN ({placeholders})
                  AND c.dst_paper_id IS NOT NULL
            """),
            params,
        )

    nodes = [
        CitationNode(
            id=int(r["id"]),
            title=str(r["title"]),
            authors=str(r["authors"] or ""),
            year=int(r["year"]) if r["year"] else None,
        )
        for r in node_rows
    ]
    edges = [
        CitationEdge(source=int(e["src_paper_id"]), target=int(e["dst_paper_id"]), type="citation")
        for e in edges_raw.mappings()
        if int(e["src_paper_id"]) in id_set and int(e["dst_paper_id"]) in id_set
    ]

    if paper_id is not None:
        connected_ids = {paper_id}
        for edge in edges:
            if edge.source == paper_id:
                connected_ids.add(edge.target)
            elif edge.target == paper_id:
                connected_ids.add(edge.source)
        return CitationGraphResponse(
            nodes=[n for n in nodes if n.id in connected_ids],
            edges=[e for e in edges if e.source in connected_ids and e.target in connected_ids],
        )

    return CitationGraphResponse(nodes=nodes, edges=edges)
