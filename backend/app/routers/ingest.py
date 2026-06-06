from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.deps import CurrentUserId
from app.schemas.ingest import IngestBatchResponse, IngestTaskResponse, TaskRetryResponse
from common.clients.redis import enqueue_ingest_task
from common.db.mysql import AsyncSessionLocal

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.get("/batches/{batch_id}", response_model=IngestBatchResponse,
    summary="批次解析进度", description="查询一次批量上传的整体进度。")
async def get_batch_progress(batch_id: str, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, user_id, total, done, failed, status, created_at FROM ingest_batches WHERE id = :batch_id AND user_id = :user_id LIMIT 1"),
            {"batch_id": int(batch_id), "user_id": user_id},
        )
        row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return IngestBatchResponse(
        batch_id=batch_id,
        status=str(row["status"]),
        total_tasks=int(row["total"]),
        completed_tasks=int(row["done"]),
        failed_tasks=int(row["failed"]),
        created_at=row["created_at"],
    )


@router.get("/tasks", response_model=List[IngestTaskResponse],
    summary="解析任务列表", description="查询解析任务详细状态，可按 batch_id 过滤。")
async def list_tasks(batch_id: Optional[str] = None, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    clauses = ["t.user_id = :user_id"]
    params = {"user_id": user_id}
    if batch_id is not None:
        clauses.append("t.batch_id = :batch_id")
        params["batch_id"] = int(batch_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(f"""
                SELECT t.id, t.paper_id, t.file_name, t.stage, t.progress, t.error_msg,
                       COALESCE(p.status, t.stage) AS status, t.updated_at
                FROM ingest_tasks t LEFT JOIN papers p ON p.id = t.paper_id AND p.user_id = t.user_id
                WHERE {' AND '.join(clauses)}
                ORDER BY t.created_at DESC
            """),
            params,
        )
        rows = result.mappings().all()
    return [
        IngestTaskResponse(
            id=str(row["id"]),
            paper_id=int(row["paper_id"]) if row["paper_id"] else 0,
            status=str(row["status"]),
            stage=str(row["stage"]),
            progress=float(row["progress"] or 0),
            error=row.get("error_msg"),
            updated_at=row.get("updated_at") or datetime.now(),
        )
        for row in rows
    ]


@router.post("/tasks/{id}/retry", response_model=TaskRetryResponse,
    summary="重试失败任务", description="将 failed 状态任务重新入队。")
async def retry_task(id: str, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, paper_id, user_id, file_name, file_hash FROM ingest_tasks WHERE id = :id AND user_id = :user_id LIMIT 1"),
            {"id": int(id), "user_id": user_id},
        )
        row = result.mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Task not found")
        await session.execute(
            text("UPDATE ingest_tasks SET stage = 'queued', progress = 0, error_msg = NULL, updated_at = NOW() WHERE id = :id"),
            {"id": int(id)},
        )
        await session.commit()
        enqueue_ingest_task(int(row["user_id"]), int(row["paper_id"]), f"{row['user_id']}/{row['paper_id']}/original.pdf", int(row["id"]))
    return TaskRetryResponse(task_id=id, status="pending", message="Task has been successfully queued for retry.")
