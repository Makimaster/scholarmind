from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import CurrentUserId
from app.schemas.papers import (
    FolderCreate,
    FolderResponse,
    PaperDetailResponse,
    PaperResponse,
    PaperUploadResponse,
)
from common.clients.minio import presigned_get_url, remove_object, remove_objects_by_prefix, upload_pdf
from common.config import settings
from common.clients.milvus import delete_by_paper
from common.clients.redis import enqueue_ingest_task
from common.db.mysql import AsyncSessionLocal, get_mysql_session

router = APIRouter(prefix="/papers", tags=["papers"])
folders_router = APIRouter(prefix="/folders", tags=["folders"])


async def _clear_paper_data(user_id: int, paper_id: int, db: AsyncSession) -> None:
    """Remove all previous parse data for a paper before re-ingesting."""
    await delete_by_paper(user_id, paper_id)
    await remove_objects_by_prefix(settings.MINIO_BUCKET_FIG, f"{user_id}/{paper_id}/")
    await db.execute(
        text("DELETE FROM doc_blocks WHERE paper_id = :id AND user_id = :user_id"),
        {"id": paper_id, "user_id": user_id},
    )


async def _get_existing_paper(db: AsyncSession, user_id: int, file_hash: str):
    result = await db.execute(
        text("""
            SELECT id, pdf_key, status
            FROM papers
            WHERE user_id = :user_id AND file_hash = :file_hash
            LIMIT 1
        """),
        {"user_id": user_id, "file_hash": file_hash},
    )
    return result.mappings().first()


async def _create_paper(
    db: AsyncSession,
    user_id: int,
    folder_id: int | None,
    filename: str,
    file_hash: str,
) -> int:
    title = Path(filename).stem or filename
    result = await db.execute(
        text("""
            INSERT INTO papers (user_id, folder_id, title, file_hash, pdf_key, status)
            VALUES (:user_id, :folder_id, :title, :file_hash, :pdf_key, 'pending')
        """),
        {"user_id": user_id, "folder_id": folder_id, "title": title, "file_hash": file_hash, "pdf_key": "pending"},
    )
    paper_id = result.lastrowid
    pdf_key = f"{user_id}/{paper_id}/original.pdf"
    await db.execute(
        text("UPDATE papers SET pdf_key = :pdf_key WHERE user_id = :user_id AND id = :paper_id"),
        {"user_id": user_id, "paper_id": paper_id, "pdf_key": pdf_key},
    )
    return int(paper_id)


async def _create_task(
    db: AsyncSession, batch_id: int, user_id: int, paper_id: int,
    filename: str, file_hash: str, stage: str, progress: int,
) -> int:
    result = await db.execute(
        text("""
            INSERT INTO ingest_tasks (batch_id, user_id, paper_id, file_name, file_hash, stage, progress)
            VALUES (:batch_id, :user_id, :paper_id, :file_name, :file_hash, :stage, :progress)
        """),
        {"batch_id": batch_id, "user_id": user_id, "paper_id": paper_id, "file_name": filename, "file_hash": file_hash, "stage": stage, "progress": progress},
    )
    return int(result.lastrowid)


async def _update_batch_counts(db: AsyncSession, batch_id: int, user_id: int) -> None:
    await db.execute(
        text("""
            UPDATE ingest_batches b SET
                done = (SELECT COUNT(*) FROM ingest_tasks t WHERE t.batch_id = b.id AND t.user_id = b.user_id AND t.stage = 'done'),
                failed = (SELECT COUNT(*) FROM ingest_tasks t WHERE t.batch_id = b.id AND t.user_id = b.user_id AND t.stage = 'failed'),
                status = CASE
                    WHEN (SELECT COUNT(*) FROM ingest_tasks t WHERE t.batch_id = b.id AND t.user_id = b.user_id AND t.stage IN ('done','failed')) >= b.total THEN 'done'
                    ELSE 'running'
                END
            WHERE b.id = :batch_id AND b.user_id = :user_id
        """),
        {"batch_id": batch_id, "user_id": user_id},
    )


# --------------------------------------------------------------------------- upload
@router.post("/upload", response_model=PaperUploadResponse, status_code=status.HTTP_202_ACCEPTED,
    summary="批量上传 PDF 论文",
    description="上传一个或多个 PDF 文件，异步入库（202 立即返回）。")
async def upload_papers(
    files: List[UploadFile] = File(...),
    folder_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_mysql_session),
    user_id: CurrentUserId = None,  # type: ignore[valid-type]
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    batch_result = await db.execute(
        text("INSERT INTO ingest_batches (user_id, total, done, failed, status) VALUES (:user_id, :total, 0, 0, 'running')"),
        {"user_id": user_id, "total": len(files)},
    )
    batch_id = int(batch_result.lastrowid)
    task_ids: list[str] = []
    queued_jobs: list[tuple[int, int, str, int]] = []
    try:
        for uploaded_file in files:
            filename = uploaded_file.filename or "paper.pdf"
            if not filename.lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail=f"Only PDF files are supported: {filename}")
            data = await uploaded_file.read()
            if not data.startswith(b"%PDF"):
                raise HTTPException(status_code=400, detail=f"Invalid PDF file: {filename}")
            try:
                import xxhash
            except ModuleNotFoundError as exc:
                raise HTTPException(status_code=500, detail="xxhash dependency is not installed") from exc
            file_hash = xxhash.xxh64(data).hexdigest()
            existing = await _get_existing_paper(db, user_id, file_hash)
            if existing is None:
                try:
                    async with db.begin_nested():
                        paper_id = await _create_paper(db, user_id, folder_id, filename, file_hash)
                except IntegrityError:
                    existing = await _get_existing_paper(db, user_id, file_hash)
                    if existing is None:
                        raise
                    paper_id = int(existing["id"])
                    pdf_key = str(existing["pdf_key"])
                else:
                    pdf_key = await upload_pdf(user_id, paper_id, data)
            else:
                paper_id = int(existing["id"])
                # Re-upload PDF to overwrite the old one
                pdf_key = await upload_pdf(user_id, paper_id, data)
                # Clear old parse data so the re-ingest starts fresh
                await _clear_paper_data(user_id, paper_id, db)

            await db.execute(
                text("UPDATE papers SET status = 'queued' WHERE id = :paper_id AND user_id = :user_id"),
                {"paper_id": paper_id, "user_id": user_id},
            )
            task_id = await _create_task(db, batch_id, user_id, paper_id, filename, file_hash, "queued", 0)
            queued_jobs.append((user_id, paper_id, pdf_key, task_id))
            task_ids.append(str(task_id))
        await _update_batch_counts(db, batch_id, user_id)
        await db.commit()
        enqueue_errors: list[str] = []
        for uid, pid, key, tid in queued_jobs:
            try:
                enqueue_ingest_task(uid, pid, key, tid)
            except Exception as exc:  # noqa: BLE001 - persist failed enqueue state for recovery.
                message = f"Failed to enqueue ingest task: {exc}"
                enqueue_errors.append(message)
                async with AsyncSessionLocal() as fail_session:
                    await fail_session.execute(
                        text(
                            """
                            UPDATE ingest_tasks
                            SET stage = 'failed', progress = 0, error_msg = :error_msg, finished_at = NOW()
                            WHERE id = :task_id AND user_id = :user_id
                            """
                        ),
                        {"task_id": tid, "user_id": uid, "error_msg": message[:2000]},
                    )
                    await fail_session.execute(
                        text("UPDATE papers SET status = 'failed' WHERE id = :paper_id AND user_id = :user_id"),
                        {"paper_id": pid, "user_id": uid},
                    )
                    await _update_batch_counts(fail_session, batch_id, uid)
                    await fail_session.commit()
        if enqueue_errors:
            raise HTTPException(status_code=500, detail="; ".join(enqueue_errors))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Upload pipeline error: {exc}") from exc
    return PaperUploadResponse(batch_id=str(batch_id), tasks=task_ids)


# --------------------------------------------------------------------------- list papers
@router.get("", response_model=List[PaperResponse],
    summary="论文列表", description="获取当前用户的论文列表，支持按文件夹和状态过滤。")
async def list_papers(
    folder_id: Optional[int] = None,
    status: Optional[str] = None,
    user_id: CurrentUserId = None,  # type: ignore[valid-type]
):
    async with AsyncSessionLocal() as session:
        clauses = ["user_id = :user_id"]
        params = {"user_id": user_id}
        if folder_id is not None:
            clauses.append("folder_id = :folder_id")
            params["folder_id"] = folder_id
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        result = await session.execute(
            text(f"SELECT * FROM papers WHERE {' AND '.join(clauses)} ORDER BY created_at DESC"),
            params,
        )
        rows = result.mappings().all()
    return [
        PaperResponse(
            id=int(r["id"]), title=str(r["title"] or ""), authors=r.get("authors"), journal=None, year=r.get("year"),
            abstract=r.get("abstract"), folder_id=r.get("folder_id"),
            status=str(r["status"] or "pending"), file_key=str(r["pdf_key"] or ""),
            file_size=0, pages=r.get("num_pages") or 0, created_at=r["created_at"], batch_id=None,
        )
        for r in rows
    ]


# --------------------------------------------------------------------------- figure preview
@router.get("/figures/url", summary="获取图像预签名 URL", description="按 image_key 获取当前用户图像对象的临时访问 URL。")
async def get_figure_url(image_key: str, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    prefix = f"{user_id}/"
    if not image_key.startswith(prefix):
        raise HTTPException(status_code=404, detail="Figure not found")
    return {"url": await presigned_get_url(settings.MINIO_BUCKET_FIG, image_key)}


# --------------------------------------------------------------------------- paper detail
@router.get("/{id}", response_model=PaperDetailResponse, summary="论文详情", description="获取单篇论文的完整信息。")
async def get_paper_detail(id: int, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM papers WHERE id = :id AND user_id = :user_id LIMIT 1"),
            {"id": id, "user_id": user_id},
        )
        r = result.mappings().first()
    if r is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return PaperDetailResponse(
        id=int(r["id"]), title=str(r["title"] or ""), authors=r.get("authors"), journal=None, year=r.get("year"),
        abstract=r.get("abstract"), folder_id=r.get("folder_id"),
        status=str(r["status"] or "pending"), file_key=str(r["pdf_key"] or ""),
        file_size=0, pages=r.get("num_pages") or 0, created_at=r["created_at"], batch_id=None, meta_data=None,
    )


# --------------------------------------------------------------------------- delete paper
@router.delete("/{id}", status_code=status.HTTP_200_OK, summary="删除论文",
    description="删除指定论文及其解析块、引用边和向量索引。")
async def delete_paper(id: int, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with AsyncSessionLocal() as session:
        exists = await session.execute(
            text("SELECT id, pdf_key FROM papers WHERE id = :id AND user_id = :user_id LIMIT 1"),
            {"id": id, "user_id": user_id},
        )
        paper = exists.mappings().first()
        if paper is None:
            raise HTTPException(status_code=404, detail="Paper not found")

        await delete_by_paper(user_id, id)
        await remove_object(settings.MINIO_BUCKET_PDF, str(paper["pdf_key"] or ""))
        await remove_objects_by_prefix(settings.MINIO_BUCKET_FIG, f"{user_id}/{id}/")
        await session.execute(
            text("DELETE FROM doc_blocks WHERE paper_id = :id AND user_id = :user_id"),
            {"id": id, "user_id": user_id},
        )
        await session.execute(
            text("""
                DELETE c FROM citations c
                LEFT JOIN papers src ON src.id = c.src_paper_id
                LEFT JOIN papers dst ON dst.id = c.dst_paper_id
                WHERE (c.src_paper_id = :id AND src.user_id = :user_id)
                   OR (c.dst_paper_id = :id AND dst.user_id = :user_id)
            """),
            {"id": id, "user_id": user_id},
        )
        await session.execute(
            text("DELETE FROM ingest_tasks WHERE paper_id = :id AND user_id = :user_id"),
            {"id": id, "user_id": user_id},
        )
        await session.execute(
            text("DELETE FROM papers WHERE id = :id AND user_id = :user_id"),
            {"id": id, "user_id": user_id},
        )
        await session.commit()
    return {"status": "success", "message": f"Paper {id} has been deleted successfully."}


# --------------------------------------------------------------------------- reparse paper
@router.post("/{id}/reparse", status_code=status.HTTP_202_ACCEPTED, summary="强制重新解析",
    description="重置论文状态并重新入队解析，跳过文件 hash 去重。")
async def reparse_paper(id: int, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with AsyncSessionLocal() as session:
        paper = await session.execute(
            text("SELECT id, pdf_key, folder_id FROM papers WHERE id = :id AND user_id = :user_id LIMIT 1"),
            {"id": id, "user_id": user_id},
        )
        row = paper.mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Paper not found")

        pdf_key = str(row["pdf_key"] or "")
        # Remove old parse data: doc_blocks, Milvus vectors, MinIO figures
        await delete_by_paper(user_id, id)
        await remove_objects_by_prefix(settings.MINIO_BUCKET_FIG, f"{user_id}/{id}/")
        await session.execute(
            text("DELETE FROM doc_blocks WHERE paper_id = :id AND user_id = :user_id"),
            {"id": id, "user_id": user_id},
        )
        # Reset ingest task: mark as queued again (old task row reused)
        task_result = await session.execute(
            text("SELECT id FROM ingest_tasks WHERE paper_id = :id AND user_id = :user_id ORDER BY id DESC LIMIT 1"),
            {"id": id, "user_id": user_id},
        )
        task_row = task_result.mappings().first()
        if task_row is None:
            # Create a new ingest task if none exists
            ingest_result = await session.execute(
                text("""
                    INSERT INTO ingest_batches (user_id, total, done, failed, status)
                    VALUES (:user_id, 1, 0, 0, 'running')
                """),
                {"user_id": user_id},
            )
            batch_id = int(ingest_result.lastrowid)
            task_insert = await session.execute(
                text("""
                    INSERT INTO ingest_tasks (batch_id, user_id, paper_id, file_name, file_hash, stage, progress)
                    VALUES (:batch_id, :user_id, :paper_id, :file_name, :file_hash, :stage, :progress)
                """),
                {
                    "batch_id": batch_id, "user_id": user_id, "paper_id": id,
                    "file_name": "reparse", "file_hash": f"reparse-{id}",
                    "stage": "queued", "progress": 0,
                },
            )
            task_id = int(ingest_result.lastrowid)
        else:
            task_id = int(task_row["id"])
            await session.execute(
                text("UPDATE ingest_tasks SET stage = 'queued', progress = 0, error_msg = NULL, updated_at = NOW() WHERE id = :id"),
                {"id": task_id},
            )

        await session.execute(
            text("UPDATE papers SET status = 'queued' WHERE id = :id AND user_id = :user_id"),
            {"id": id, "user_id": user_id},
        )
        await session.commit()
        enqueue_ingest_task(user_id, id, pdf_key, task_id)

    return {"status": "success", "message": f"Paper {id} has been queued for re-parse.", "task_id": str(task_id)}


# --------------------------------------------------------------------------- folders
@folders_router.get("", response_model=List[FolderResponse],
    summary="文件夹列表", description="获取当前用户的文件夹及论文数量。")
async def list_folders(user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT f.id, f.name, f.parent_id, f.created_at,
                       (SELECT COUNT(*) FROM papers WHERE user_id = f.user_id AND folder_id = f.id) AS paper_count
                FROM folders f WHERE f.user_id = :user_id ORDER BY f.created_at
            """),
            {"user_id": user_id},
        )
        rows = result.mappings().all()
    return [FolderResponse(
        id=int(r["id"]), name=str(r["name"]), parent_id=r.get("parent_id"),
        paper_count=int(r["paper_count"]), created_at=r["created_at"],
    ) for r in rows]


@folders_router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED,
    summary="创建文件夹", description="新建论文文件夹。")
async def create_folder(folder_data: FolderCreate, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("INSERT INTO folders (user_id, name, parent_id) VALUES (:user_id, :name, :parent_id)"),
            {"user_id": user_id, "name": folder_data.name, "parent_id": folder_data.parent_id},
        )
        await session.commit()
        folder_id = int(result.lastrowid)
    return FolderResponse(id=folder_id, name=folder_data.name, parent_id=folder_data.parent_id, paper_count=0, created_at=datetime.now())


@folders_router.delete("/{id}", status_code=status.HTTP_200_OK, summary="删除文件夹")
async def delete_folder(id: int, user_id: CurrentUserId = None):  # type: ignore[valid-type]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("DELETE FROM folders WHERE id = :id AND user_id = :user_id"),
            {"id": id, "user_id": user_id},
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Folder not found")
    return {"status": "success", "message": f"Folder {id} has been deleted successfully."}
