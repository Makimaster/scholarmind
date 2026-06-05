from redis import Redis
from rq import Queue, Retry

from common.config import settings

INGEST_QUEUE_NAME = "ingest"
INGEST_JOB_TIMEOUT_SECONDS = 900

_redis: Redis | None = None
_queue: Queue | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
        )
    return _redis


def get_ingest_queue() -> Queue:
    global _queue
    if _queue is None:
        _queue = Queue(INGEST_QUEUE_NAME, connection=get_redis())
    return _queue


def enqueue_ingest_task(user_id: int, paper_id: int, pdf_key: str, task_id: int) -> str:
    job = get_ingest_queue().enqueue(
        "app.worker.main.handle_ingest_job",
        user_id,
        paper_id,
        pdf_key,
        task_id,
        job_timeout=INGEST_JOB_TIMEOUT_SECONDS,
        result_ttl=86400,
        failure_ttl=604800,
        retry=Retry(max=2, interval=[60, 300]),
    )
    return job.id
