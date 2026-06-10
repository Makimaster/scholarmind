from __future__ import annotations

from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


class QueryLogResponse(BaseModel):
    id: int
    user_id: int
    question: str
    rewritten_query: Optional[str] = None
    retrieved_chunk_ids: List[str] = []
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    feedback: Optional[int] = None
    created_at: datetime


class IngestionTaskResponse(BaseModel):
    id: int
    paper_id: Optional[int] = None
    title: str
    file_name: str
    status: str
    stage: str
    progress: int
    error_msg: Optional[str] = None
    started_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AccessLogResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    path: str
    method: str
    status_code: int
    ip_address: str
    created_at: datetime


class StatsOverviewResponse(BaseModel):
    paper_count: int
    chunk_count: int
    total_queries: int
    average_latency_ms: float
