from pydantic import BaseModel
from typing import Optional, List

class ReviewGenerateRequest(BaseModel):
    topic: str
    scope_type: str = "all"  # "all", "folder", "papers"
    folder_id: Optional[int] = None
    paper_ids: Optional[List[int]] = None

class CitationNode(BaseModel):
    id: int
    title: str
    authors: Optional[str] = None
    year: Optional[int] = None

class CitationEdge(BaseModel):
    source: int
    target: int
    type: Optional[str] = "citation"  # "citation", "reference"

class CitationGraphResponse(BaseModel):
    nodes: List[CitationNode]
    edges: List[CitationEdge]
