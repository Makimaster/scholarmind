import asyncio

from rq import Connection, Worker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from common.clients.redis import get_ingest_queue, get_redis
from common.db.mysql import AsyncSessionLocal
from common.logging import logger
from services.parsing.parser import parse_paper


async def _update_batch_counts(db: AsyncSession, batch_id: int, user_id: int) -> None:
    await db.execute(
        text("""
            UPDATE ingest_batches b
            SET
                done = (
                    SELECT COUNT(*) FROM ingest_tasks t
                    WHERE t.batch_id = b.id AND t.user_id = b.user_id AND t.stage = 'done'
                ),
                failed = (
                    SELECT COUNT(*) FROM ingest_tasks t
                    WHERE t.batch_id = b.id AND t.user_id = b.user_id AND t.stage = 'failed'
                ),
                status = CASE
                    WHEN (
                        SELECT COUNT(*) FROM ingest_tasks t
                        WHERE t.batch_id = b.id AND t.user_id = b.user_id
                          AND t.stage IN ('done', 'failed')
                    ) >= b.total THEN 'done'
                    ELSE 'running'
                END
            WHERE b.id = :batch_id AND b.user_id = :user_id
        """),
        {"batch_id": batch_id, "user_id": user_id},
    )


async def _mark_failed(
    db: AsyncSession,
    user_id: int,
    paper_id: int,
    task_id: int,
    batch_id: int | None,
    error: Exception,
) -> None:
    await db.execute(
        text("""
            UPDATE ingest_tasks
            SET stage = 'failed', error_msg = :error_msg, finished_at = NOW()
            WHERE id = :task_id AND user_id = :user_id
        """),
        {"task_id": task_id, "user_id": user_id, "error_msg": str(error)[:2000]},
    )
    await db.execute(
        text("""
            UPDATE papers
            SET status = 'failed'
            WHERE id = :paper_id AND user_id = :user_id
        """),
        {"paper_id": paper_id, "user_id": user_id},
    )
    if batch_id is not None:
        await _update_batch_counts(db, batch_id, user_id)


async def _run_indexing_if_available(user_id: int, paper_id: int, db: AsyncSession) -> None:
    try:
        from services.indexing.indexer import index_paper
    except ModuleNotFoundError:
        logger.warning(f"[worker] indexing service not implemented, skipped paper_id={paper_id}")
        return

    await index_paper(user_id=user_id, paper_id=paper_id, db=db)


async def _handle_ingest_job_async(user_id: int, paper_id: int, pdf_key: str, task_id: int) -> None:
    batch_id: int | None = None
    async with AsyncSessionLocal() as db:
        try:
            task_result = await db.execute(
                text("""
                    SELECT id, batch_id, stage
                    FROM ingest_tasks
                    WHERE id = :task_id AND user_id = :user_id AND paper_id = :paper_id
                    LIMIT 1
                """),
                {"task_id": task_id, "user_id": user_id, "paper_id": paper_id},
            )
            task = task_result.mappings().first()
            if task is None:
                raise RuntimeError(f"ingest task not found: task_id={task_id} user_id={user_id}")
            if task["stage"] == "done":
                return
            batch_id = int(task["batch_id"]) if task["batch_id"] is not None else None

            paper_result = await db.execute(
                text("""
                    SELECT id, pdf_key
                    FROM papers
                    WHERE id = :paper_id AND user_id = :user_id
                    LIMIT 1
                """),
                {"paper_id": paper_id, "user_id": user_id},
            )
            paper = paper_result.mappings().first()
            if paper is None:
                raise RuntimeError(f"paper not found: paper_id={paper_id} user_id={user_id}")

            await db.execute(
                text("""
                    UPDATE ingest_tasks
                    SET stage = 'parsing', progress = 10, error_msg = NULL,
                        started_at = COALESCE(started_at, NOW())
                    WHERE id = :task_id AND user_id = :user_id
                """),
                {"task_id": task_id, "user_id": user_id},
            )
            await db.commit()

            await parse_paper(user_id, paper_id, pdf_key or str(paper["pdf_key"]), db)

            await db.execute(
                text("""
                    UPDATE ingest_tasks
                    SET stage = 'indexing', progress = 50
                    WHERE id = :task_id AND user_id = :user_id
                """),
                {"task_id": task_id, "user_id": user_id},
            )
            await db.commit()

            await _run_indexing_if_available(user_id, paper_id, db)

            await db.execute(
                text("""
                    UPDATE ingest_tasks
                    SET stage = 'done', progress = 100, finished_at = NOW()
                    WHERE id = :task_id AND user_id = :user_id
                """),
                {"task_id": task_id, "user_id": user_id},
            )
            await db.execute(
                text("""
                    UPDATE papers
                    SET status = 'done'
                    WHERE id = :paper_id AND user_id = :user_id
                """),
                {"paper_id": paper_id, "user_id": user_id},
            )
            if batch_id is not None:
                await _update_batch_counts(db, batch_id, user_id)
            await db.commit()
        except Exception as e:
            logger.exception(f"[worker] ingest job failed task_id={task_id} paper_id={paper_id}: {e}")
            await db.rollback()
            await _mark_failed(db, user_id, paper_id, task_id, batch_id, e)
            await db.commit()
            raise


def handle_ingest_job(user_id: int, paper_id: int, pdf_key: str, task_id: int) -> None:
    asyncio.run(_handle_ingest_job_async(user_id, paper_id, pdf_key, task_id))


def start_worker() -> None:
    logger.info("Starting ScholarMind RQ Worker...")
    redis_conn = get_redis()
    queue = get_ingest_queue()
    with Connection(redis_conn):
        worker = Worker([queue])
        logger.info(f"Worker listening on queue: {queue.name}")
        worker.work()


if __name__ == "__main__":
    start_worker()
