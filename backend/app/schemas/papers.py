from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None

class FolderResponse(BaseModel):
    id: int
    name: str
    parent_id: Optional[int] = None
    paper_count: int = 0
    created_at: datetime

class PaperResponse(BaseModel):
    id: int
    title: str
    authors: Optional[str] = None
    journal: Optional[str] = None
    year: Optional[int] = None
    abstract: Optional[str] = None
    folder_id: Optional[int] = None
    status: str  # "pending", "parsing", "indexing", "completed", "failed"
    file_key: str
    file_size: int
    pages: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None
    batch_id: Optional[str] = None

class PaperUploadResponse(BaseModel):
    batch_id: str
    tasks: List[str]

class PaperDetailResponse(PaperResponse):
    meta_data: Optional[dict] = None
