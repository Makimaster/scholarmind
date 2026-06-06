from __future__ import annotations

import json
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.deps import CurrentUserId
from app.schemas.observability import AccessLogResponse, IngestionTaskResponse, QueryLogResponse, StatsOverviewResponse
from common.db.mysql import AsyncSessionLocal

router = APIRouter(tags=["observability"])


@router.get("/observability/ingestion", response_model=List[IngestionTaskResponse], summary="真实导入任务监控")
async def list_ingestion_tasks(limit: int = 50, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT t.id, t.paper_id, COALESCE(p.title, t.file_name) AS title,
                       t.file_name, COALESCE(p.status, t.stage) AS status,
                       t.stage, t.progress, t.error_msg, t.started_at, t.created_at
                FROM ingest_tasks t LEFT JOIN papers p ON p.id = t.paper_id AND p.user_id = t.user_id
                WHERE t.user_id = :user_id
                ORDER BY t.created_at DESC, t.id DESC
                LIMIT :limit
                """
            ),
            {"user_id": user_id, "limit": limit},
        )
        return [IngestionTaskResponse(**dict(row)) for row in result.mappings()]


@router.get("/observability/query-logs", response_model=List[QueryLogResponse], summary="真实查询日志")
async def list_observability_query_logs(limit: int = 50, offset: int = 0, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT id, user_id, question, rewritten_query, retrieved_chunk_ids,
                       COALESCE(latency_ms, 0) AS latency_ms,
                       COALESCE(prompt_tokens, 0) AS prompt_tokens,
                       COALESCE(completion_tokens, 0) AS completion_tokens,
                       feedback, created_at
                FROM query_logs
                WHERE user_id = :user_id
                ORDER BY created_at DESC, id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"user_id": user_id, "limit": limit, "offset": offset},
        )
        logs = []
        for row in result.mappings():
            item = dict(row)
            raw_ids = item.get("retrieved_chunk_ids") or []
            if isinstance(raw_ids, str):
                try:
                    raw_ids = json.loads(raw_ids)
                except json.JSONDecodeError:
                    raw_ids = []
            item["retrieved_chunk_ids"] = [str(value) for value in raw_ids]
            logs.append(QueryLogResponse(**item))
        return logs


@router.get("/logs/queries", response_model=List[QueryLogResponse], summary="查询日志兼容路径")
async def list_query_logs(limit: int = 10, offset: int = 0, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    return await list_observability_query_logs(limit=limit, offset=offset, user_id=user_id)


@router.get("/logs/access", response_model=List[AccessLogResponse], summary="访问日志")
async def list_access_logs(limit: int = 10, offset: int = 0):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT id, user_id, path, method, status_code, COALESCE(ip, '') AS ip_address, created_at
                FROM access_logs
                ORDER BY created_at DESC, id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        )
        return [AccessLogResponse(**dict(row)) for row in result.mappings()]


@router.get("/stats/overview", response_model=StatsOverviewResponse, summary="系统概览统计")
async def get_stats_overview(user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(*) FROM papers WHERE user_id = :user_id) AS paper_count,
                    (SELECT COALESCE(SUM(chunk_count), 0) FROM papers WHERE user_id = :user_id) AS chunk_count,
                    (SELECT COUNT(*) FROM query_logs WHERE user_id = :user_id) AS total_queries,
                    (SELECT COALESCE(AVG(latency_ms), 0) FROM query_logs WHERE user_id = :user_id) AS average_latency_ms
                """
            ),
            {"user_id": user_id},
        )
        row = result.mappings().one()
        return StatsOverviewResponse(
            paper_count=int(row["paper_count"] or 0),
            chunk_count=int(row["chunk_count"] or 0),
            total_queries=int(row["total_queries"] or 0),
            average_latency_ms=float(row["average_latency_ms"] or 0),
        )
