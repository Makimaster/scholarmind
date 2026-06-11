import asyncio
from datetime import timedelta
from io import BytesIO

from minio import Minio
from minio.deleteobjects import DeleteObject

from common.config import settings

_client = Minio(
    settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE,
)
_buckets_ready = False


def _ensure_buckets_sync() -> None:
    global _buckets_ready
    if _buckets_ready:
        return
    for bucket in (settings.MINIO_BUCKET_PDF, settings.MINIO_BUCKET_FIG):
        if not _client.bucket_exists(bucket):
            _client.make_bucket(bucket)
    _buckets_ready = True


async def ensure_buckets() -> None:
    await asyncio.to_thread(_ensure_buckets_sync)


async def upload_object(bucket: str, key: str, data: bytes, content_type: str) -> str:
    await ensure_buckets()
    await asyncio.to_thread(
        _client.put_object,
        bucket,
        key,
        BytesIO(data),
        len(data),
        content_type=content_type,
    )
    return key


async def upload_pdf(user_id: int, paper_id: int, data: bytes) -> str:
    key = f"{user_id}/{paper_id}/original.pdf"
    return await upload_object(settings.MINIO_BUCKET_PDF, key, data, "application/pdf")


async def download_pdf(pdf_key: str) -> bytes:
    await ensure_buckets()

    def _download() -> bytes:
        response = _client.get_object(settings.MINIO_BUCKET_PDF, pdf_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    return await asyncio.to_thread(_download)


async def upload_figure(
    user_id: int,
    paper_id: int,
    name: str,
    data: bytes,
    content_type: str = "image/png",
) -> str:
    safe_name = name.strip().replace("\\", "/").lstrip("/") or "figure.png"
    key = f"{user_id}/{paper_id}/raw/{safe_name}"
    return await upload_object(settings.MINIO_BUCKET_FIG, key, data, content_type)


async def download_object(bucket: str, key: str) -> bytes:
    """Download object bytes directly from MinIO (for proxying to browser)."""
    await ensure_buckets()

    def _download() -> bytes:
        response = _client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    return await asyncio.to_thread(_download)


async def presigned_get_url(bucket: str, key: str, expires_seconds: int = 3600) -> str:
    """Generate a presigned URL.

    The URL is signed with the internal host (e.g. minio:9000), which means
    it is only valid when the caller can reach that host.  For browser access
    (which cannot reach the Docker-internal host), use the /papers/figures/{key}
    proxy endpoint instead.
    """
    await ensure_buckets()
    return await asyncio.to_thread(
        _client.presigned_get_object,
        bucket,
        key,
        expires=timedelta(seconds=expires_seconds),
    )


async def remove_object(bucket: str, key: str | None) -> None:
    if not key:
        return
    await ensure_buckets()
    await asyncio.to_thread(_client.remove_object, bucket, key)


async def remove_objects_by_prefix(bucket: str, prefix: str) -> None:
    await ensure_buckets()

    def _remove() -> None:
        objects = _client.list_objects(bucket, prefix=prefix, recursive=True)
        errors = _client.remove_objects(bucket, (DeleteObject(obj.object_name) for obj in objects))
        for error in errors:
            raise RuntimeError(f"MinIO delete failed for {error.object_name}: {error}")

    await asyncio.to_thread(_remove)
