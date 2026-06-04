from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status
from typing import List, Optional
from datetime import datetime
import uuid
from app.schemas.papers import PaperResponse, PaperUploadResponse, PaperDetailResponse, FolderCreate, FolderResponse

router = APIRouter(prefix="/papers", tags=["papers"])
folders_router = APIRouter(prefix="/folders", tags=["folders"])

# Mock In-Memory Databases
MOCK_FOLDERS = [
    FolderResponse(id=1, name="大语言模型 (LLM)", parent_id=None, paper_count=2, created_at=datetime.now()),
    FolderResponse(id=2, name="多模态与 VLM", parent_id=None, paper_count=0, created_at=datetime.now()),
    FolderResponse(id=3, name="RAG 检索增强生成", parent_id=None, paper_count=3, created_at=datetime.now())
]

MOCK_PAPERS = [
    PaperDetailResponse(
        id=1,
        title="Attention Is All You Need",
        authors="Vaswani, Shazeer, Parmar, Uszkoreit, Jones, Gomez, Kaiser, Polosukhin",
        journal="NeurIPS",
        year=2017,
        abstract="The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...",
        folder_id=1,
        status="completed",
        file_key="papers/attention_is_all_you_need.pdf",
        file_size=220392,
        pages=15,
        created_at=datetime.now(),
        batch_id="batch-782a-4bc3",
        meta_data={"citations_count": 98000, "publisher": "Google"}
    ),
    PaperDetailResponse(
        id=2,
        title="Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        authors="Lewis, Perez, Piktus, Petroni, Karpukhin, Goyal, Küttler, Lewis, Yih, Riedel, Kiela",
        journal="NeurIPS",
        year=2020,
        abstract="We show that hybrid retrieval-augmented models outperform traditional parametric-only language models...",
        folder_id=3,
        status="parsing",
        file_key="papers/rag_nlp.pdf",
        file_size=1049280,
        pages=18,
        created_at=datetime.now(),
        batch_id="batch-591c-99d1",
        meta_data={"citations_count": 3200, "publisher": "Meta AI"}
    )
]

# --- Papers Router Endpoints ---

@router.post("/upload", response_model=PaperUploadResponse, status_code=status.HTTP_202_ACCEPTED,
             summary="批量上传 PDF 论文",
             description="上传一个或多个 PDF 文件，异步入库（202 立即返回）。返回 `batch_id` 和各文件对应的 `task_id`，通过 `/ingest/batches/{batch_id}` 轮询进度。")
async def upload_papers(
    files: List[UploadFile] = File(...),
    folder_id: Optional[int] = Form(None)
):
    batch_id = f"batch-{uuid.uuid4().hex[:8]}"
    task_ids = [f"task-{uuid.uuid4().hex[:12]}" for _ in files]
    
    # Save upload state into mock database (for list query)
    for idx, f in enumerate(files):
        new_paper = PaperDetailResponse(
            id=len(MOCK_PAPERS) + 1,
            title=f.filename.replace(".pdf", ""),
            authors="待解析",
            journal=None,
            year=None,
            abstract="排队解析中...",
            folder_id=folder_id,
            status="pending",
            file_key=f"papers/{f.filename}",
            file_size=123456,  # Mock size
            pages=0,
            created_at=datetime.now(),
            batch_id=batch_id,
            meta_data={}
        )
        MOCK_PAPERS.append(new_paper)

    return PaperUploadResponse(
        batch_id=batch_id,
        tasks=task_ids
    )

@router.get("", response_model=List[PaperResponse],
            summary="论文列表",
            description="获取当前用户的论文列表，支持按文件夹（`folder_id`）和解析状态（`pending/parsing/indexing/completed/failed`）过滤。")
async def list_papers(
    folder_id: Optional[int] = None,
    status: Optional[str] = None
):
    results = MOCK_PAPERS
    if folder_id is not None:
        results = [p for p in results if p.folder_id == folder_id]
    if status is not None:
        results = [p for p in results if p.status == status]
    return results

@router.get("/{id}", response_model=PaperDetailResponse,
            summary="论文详情",
            description="获取单篇论文的完整信息，包含标题、作者、摘要、解析状态、MinIO 文件路径及附加元数据。")
async def get_paper_detail(id: int):
    for paper in MOCK_PAPERS:
        if paper.id == id:
            return paper
    raise HTTPException(status_code=404, detail="Paper not found")

@router.delete("/{id}", status_code=status.HTTP_200_OK,
               summary="删除论文",
               description="删除指定论文，同步清理 MinIO 中的 PDF/图片文件及 Milvus 中对应的所有 chunk 向量。")
async def delete_paper(id: int):
    global MOCK_PAPERS
    initial_len = len(MOCK_PAPERS)
    MOCK_PAPERS = [p for p in MOCK_PAPERS if p.id != id]
    if len(MOCK_PAPERS) < initial_len:
        return {"status": "success", "message": f"Paper {id} has been deleted successfully."}
    raise HTTPException(status_code=404, detail="Paper not found")


# --- Folders Router Endpoints ---

@folders_router.get("", response_model=List[FolderResponse],
                    summary="文件夹列表",
                    description="获取当前用户的所有文件夹及每个文件夹的论文数量。")
async def list_folders():
    return MOCK_FOLDERS

@folders_router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED,
                     summary="创建文件夹",
                     description="新建论文文件夹，支持嵌套（传 `parent_id`）。")
async def create_folder(folder_data: FolderCreate):
    new_folder = FolderResponse(
        id=len(MOCK_FOLDERS) + 1,
        name=folder_data.name,
        parent_id=folder_data.parent_id,
        paper_count=0,
        created_at=datetime.now()
    )
    MOCK_FOLDERS.append(new_folder)
    return new_folder
