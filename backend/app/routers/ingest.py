from fastapi import APIRouter, HTTPException
from typing import List, Optional
from datetime import datetime
from app.schemas.ingest import IngestBatchResponse, IngestTaskResponse, TaskRetryResponse

router = APIRouter(prefix="/ingest", tags=["ingest"])

# Mock Database for Ingestion Progress
MOCK_BATCHES = {
    "batch-782a-4bc3": IngestBatchResponse(
        batch_id="batch-782a-4bc3",
        status="completed",
        total_tasks=1,
        completed_tasks=1,
        failed_tasks=0,
        created_at=datetime.now()
    ),
    "batch-591c-99d1": IngestBatchResponse(
        batch_id="batch-591c-99d1",
        status="processing",
        total_tasks=2,
        completed_tasks=0,
        failed_tasks=1,
        created_at=datetime.now()
    )
}

MOCK_TASKS = [
    IngestTaskResponse(
        id="task-01-attention",
        paper_id=1,
        status="completed",
        stage="completed",
        progress=100.0,
        error=None,
        updated_at=datetime.now()
    ),
    IngestTaskResponse(
        id="task-02-rag-nlp",
        paper_id=2,
        status="failed",
        stage="parsing",
        progress=45.5,
        error="MinerU cloud API connection timed out",
        updated_at=datetime.now()
    )
]

@router.get("/batches/{batch_id}", response_model=IngestBatchResponse,
            summary="批次解析进度",
            description="查询一次批量上传的整体进度，返回总任务数、已完成数、失败数及状态（processing/completed/failed）。前端上传后轮询此接口。")
async def get_batch_progress(batch_id: str):
    if batch_id in MOCK_BATCHES:
        return MOCK_BATCHES[batch_id]
    # Dynamically generate progress for new uploads
    return IngestBatchResponse(
        batch_id=batch_id,
        status="processing",
        total_tasks=3,
        completed_tasks=1,
        failed_tasks=0,
        created_at=datetime.now()
    )

@router.get("/tasks", response_model=List[IngestTaskResponse],
            summary="解析任务列表",
            description="查询单个或所有解析任务的详细状态，包含当前阶段（queued/parsing/indexing/done）、进度百分比和错误信息。可按 `batch_id` 过滤。")
async def list_tasks(batch_id: Optional[str] = None):
    # For mock simplicity, we return all tasks or filter by batch_id
    if batch_id == "batch-782a-4bc3":
        return [MOCK_TASKS[0]]
    elif batch_id == "batch-591c-99d1":
        return [MOCK_TASKS[1]]
    return MOCK_TASKS

@router.post("/tasks/{id}/retry", response_model=TaskRetryResponse,
             summary="重试失败任务",
             description="将 `failed` 状态的解析任务重新入队，从头开始解析。任务 stage 重置为 parsing，progress 重置为 0。")
async def retry_task(id: str):
    for task in MOCK_TASKS:
        if task.id == id:
            task.status = "pending"
            task.stage = "parsing"
            task.progress = 0.0
            task.error = None
            task.updated_at = datetime.now()
            return TaskRetryResponse(
                task_id=id,
                status="pending",
                message="Task has been successfully queued for retry."
            )
    raise HTTPException(status_code=404, detail="Task not found")
