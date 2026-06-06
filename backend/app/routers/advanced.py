from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.advanced import CitationEdge, CitationGraphResponse, CitationNode, ReviewGenerateRequest
from services.chat_agent.agent import DEFAULT_USER_ID, build_scope
from services.chat_agent.reviewer import generate_review as generate_review_stream

router = APIRouter(tags=["advanced"])


@router.post(
    "/review/generate",
    summary="Agentic 文献综述生成（SSE 流式）",
    description="基于子问题分解与混合检索生成多文献综述，SSE 事件格式：cite → token → done。",
)
async def generate_review(request: ReviewGenerateRequest):
    scope = build_scope(DEFAULT_USER_ID, request.scope_type, request.folder_id, request.paper_ids)
    return StreamingResponse(
        generate_review_stream(request.topic, scope, DEFAULT_USER_ID),
        media_type="text/event-stream",
    )


@router.get(
    "/graph/citations",
    response_model=CitationGraphResponse,
    summary="论文引用关系图谱",
    description="返回论文间的引用网络（节点+有向边），可指定 `paper_id` 只返回与该论文相关的子图。节点含标题/作者/年份，边含引用方向。前端用于渲染知识图谱可视化。",
)
async def get_citation_graph(paper_id: Optional[int] = None):
    # TODO: Replace with MySQL citations table query in citation graph task.
    nodes = [
        CitationNode(id=1, title="Attention Is All You Need", authors="Vaswani et al.", year=2017),
        CitationNode(id=2, title="Retrieval-Augmented Generation for NLP Tasks", authors="Lewis et al.", year=2020),
        CitationNode(id=3, title="BERT: Pre-training of Deep Bidirectional Transformers", authors="Devlin et al.", year=2018),
        CitationNode(id=4, title="GPT-3: Language Models are Few-Shot Learners", authors="Brown et al.", year=2020),
        CitationNode(id=5, title="RAGMeet: Multimodal Document Retrieval", authors="Scholar et al.", year=2024),
    ]
    edges = [
        CitationEdge(source=2, target=1, type="reference"),
        CitationEdge(source=3, target=1, type="reference"),
        CitationEdge(source=4, target=1, type="reference"),
        CitationEdge(source=5, target=2, type="reference"),
        CitationEdge(source=5, target=4, type="reference"),
    ]

    if paper_id is not None:
        connected_ids = {paper_id}
        for edge in edges:
            if edge.source == paper_id:
                connected_ids.add(edge.target)
            elif edge.target == paper_id:
                connected_ids.add(edge.source)
        return CitationGraphResponse(
            nodes=[node for node in nodes if node.id in connected_ids],
            edges=[edge for edge in edges if edge.source in connected_ids and edge.target in connected_ids],
        )

    return CitationGraphResponse(nodes=nodes, edges=edges)
