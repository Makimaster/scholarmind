from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class ConversationCreate(BaseModel):
    title: Optional[str] = None
    folder_id: Optional[int] = None
    paper_ids: Optional[List[int]] = None

class ConversationResponse(BaseModel):
    id: int
    title: str
    folder_id: Optional[int] = None
    paper_ids: Optional[List[int]] = None
    created_at: datetime
    updated_at: datetime

class CitationResponse(BaseModel):
    paper_id: int
    paper_title: str
    page: int
    page_num: int
    chunk_id: str
    bbox: str
    chunk_type: str  # "text", "table", "figure", "formula"
    content: str
    image_key: Optional[str] = None

class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str  # "user", "assistant"
    content: str
    citations: Optional[List[CitationResponse]] = None
    created_at: datetime

class ChatQueryRequest(BaseModel):
    question: str
    conversation_id: int
    scope_type: str = "all"  # "all", "folder", "papers"
    folder_id: Optional[int] = None
    paper_ids: Optional[List[int]] = None

class FeedbackRequest(BaseModel):
    message_id: int
    is_positive: bool
    reason: Optional[str] = None

class FeedbackResponse(BaseModel):
    status: str
    message: str
