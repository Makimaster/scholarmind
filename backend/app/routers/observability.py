from fastapi import APIRouter
from typing import List
from datetime import datetime
from app.schemas.observability import QueryLogResponse, AccessLogResponse, StatsOverviewResponse

router = APIRouter(tags=["observability"])

# Mock database for query logs
MOCK_QUERY_LOGS = [
    QueryLogResponse(
        id=1,
        user_id=999,
        question="什么是 Transformer 架构的核心？",
        answer_snippet="Transformer 架构的核心是自注意力机制（Self-Attention）...",
        latency_ms=452,
        tokens_used=180,
        created_at=datetime.now()
    ),
    QueryLogResponse(
        id=2,
        user_id=999,
        question="RAG 包含哪几个阶段？",
        answer_snippet="RAG 检索增强生成主要包含文档载入、切分（Chunking）、向量索引、混合检索重排以及大模型集成回答五个阶段...",
        latency_ms=895,
        tokens_used=350,
        created_at=datetime.now()
    )
]

# Mock database for access logs
MOCK_ACCESS_LOGS = [
    AccessLogResponse(
        id=1,
        user_id=999,
        path="/api/chat/query",
        method="POST",
        status_code=200,
        ip_address="127.0.0.1",
        created_at=datetime.now()
    ),
    AccessLogResponse(
        id=2,
        user_id=999,
        path="/api/papers",
        method="GET",
        status_code=200,
        ip_address="127.0.0.1",
        created_at=datetime.now()
    ),
    AccessLogResponse(
        id=3,
        user_id=None,
        path="/api/auth/login",
        method="POST",
        status_code=200,
        ip_address="127.0.0.1",
        created_at=datetime.now()
    )
]

@router.get("/logs/queries", response_model=List[QueryLogResponse],
            summary="查询日志",
            description="分页获取用户提问记录，包含问题内容、回答摘要、延迟（ms）和 token 消耗。用于可观测性面板和问答质量分析。")
async def list_query_logs(limit: int = 10, offset: int = 0):
    return MOCK_QUERY_LOGS[offset:offset + limit]

@router.get("/logs/access", response_model=List[AccessLogResponse],
            summary="访问日志",
            description="分页获取 API 访问记录，含路径、方法、状态码和 IP。用于安全审计和流量监控。")
async def list_access_logs(limit: int = 10, offset: int = 0):
    return MOCK_ACCESS_LOGS[offset:offset + limit]

@router.get("/stats/overview", response_model=StatsOverviewResponse,
            summary="系统概览统计",
            description="返回系统核心指标：已入库论文总数、向量 chunk 总数、历史查询总次数、平均问答延迟（ms）。用于可观测性面板首页。")
async def get_stats_overview():
    return StatsOverviewResponse(
        paper_count=12,
        chunk_count=2480,
        total_queries=158,
        average_latency_ms=625.5
    )
