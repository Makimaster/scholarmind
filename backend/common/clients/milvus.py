"""
Milvus client: collection init, bulk insert, delete.

All sync MilvusClient calls are wrapped in asyncio.to_thread to avoid
blocking the async event loop.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from pymilvus import MilvusClient, DataType
from pymilvus.exceptions import MilvusException

from common.config import settings
from common.logging import logger

_client: MilvusClient | None = None
_collection_ready = False
DENSE_INDEX_NAME = "dense_hnsw_idx"
SPARSE_INDEX_NAME = "sparse_inverted_idx"


def get_milvus_client() -> MilvusClient:
    global _client
    if _client is None:
        _client = MilvusClient(
            uri=settings.MILVUS_URI,
            token=settings.MILVUS_TOKEN or "",
        )
    return _client


def _object_to_dict(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    for method_name in ("model_dump", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                result = method()
                if isinstance(result, dict):
                    return result
            except Exception:
                pass
    raw = getattr(value, "__dict__", None)
    return raw if isinstance(raw, dict) else {}


def _build_schema() -> Any:
    from pymilvus import MilvusClient
    schema = MilvusClient.create_schema(
        auto_id=False,
        enable_dynamic_field=False,
        partition_key_field="user_id",
        num_partitions=64,
    )
    schema.add_field("id",          DataType.VARCHAR,        max_length=64,  is_primary=True)
    schema.add_field("dense_vec",   DataType.FLOAT_VECTOR,   dim=settings.EMBEDDING_DIM)
    schema.add_field("sparse_vec",  DataType.SPARSE_FLOAT_VECTOR)
    schema.add_field("content_en",  DataType.VARCHAR,        max_length=8192)
    schema.add_field("content_zh",  DataType.VARCHAR,        max_length=4096)
    schema.add_field("user_id",     DataType.INT64)
    schema.add_field("paper_id",    DataType.INT64)
    schema.add_field("folder_id",   DataType.INT64)
    schema.add_field("acl",         DataType.VARCHAR,        max_length=256)
    schema.add_field("chunk_type",  DataType.VARCHAR,        max_length=32)
    schema.add_field("section",     DataType.VARCHAR,        max_length=512)
    schema.add_field("page_num",    DataType.INT64)
    schema.add_field("bbox",        DataType.VARCHAR,        max_length=256)
    schema.add_field("block_id",    DataType.INT64)
    schema.add_field("image_key",   DataType.VARCHAR,        max_length=256)
    return schema


def _build_index_params(fields: tuple[str, ...] = ("dense_vec", "sparse_vec")) -> Any:
    from pymilvus import MilvusClient
    index_params = MilvusClient.prepare_index_params()
    if "dense_vec" in fields:
        index_params.add_index(
            field_name="dense_vec",
            index_type=settings.MILVUS_INDEX_TYPE,
            index_name=DENSE_INDEX_NAME,
            metric_type=settings.MILVUS_METRIC,
            params={"M": 16, "efConstruction": 200},
        )
    if "sparse_vec" in fields:
        index_params.add_index(
            field_name="sparse_vec",
            index_type="SPARSE_INVERTED_INDEX",
            index_name=SPARSE_INDEX_NAME,
            metric_type="IP",
            params={"drop_ratio_build": 0.2},
        )
    return index_params


def _has_field_index(client: MilvusClient, collection_name: str, field_name: str) -> bool:
    try:
        return bool(client.list_indexes(collection_name, field_name=field_name))
    except MilvusException as e:
        logger.warning(f"[milvus] list indexes failed for {field_name}: {e}")
        return False


def _ensure_collection_sync() -> None:
    global _collection_ready
    if _collection_ready:
        return
    client = get_milvus_client()
    col = settings.MILVUS_COLLECTION
    if not client.has_collection(col):
        client.create_collection(
            collection_name=col,
            schema=_build_schema(),
            index_params=_build_index_params(),
        )
        logger.info(f"[milvus] collection '{col}' created")
    else:
        missing_fields = tuple(
            field_name
            for field_name in ("dense_vec", "sparse_vec")
            if not _has_field_index(client, col, field_name)
        )
        if missing_fields:
            client.create_index(col, _build_index_params(missing_fields))
            logger.info(f"[milvus] missing indexes added to existing collection '{col}': {missing_fields}")
    client.load_collection(col)
    _collection_ready = True
    logger.info(f"[milvus] collection '{col}' ready")


async def ensure_collection() -> None:
    await asyncio.to_thread(_ensure_collection_sync)


def _bulk_insert_sync(records: list[dict]) -> None:
    client = get_milvus_client()
    col = settings.MILVUS_COLLECTION
    batch_size = 256
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        client.insert(collection_name=col, data=batch)
    logger.info(f"[milvus] inserted {len(records)} chunks into '{col}'")


async def bulk_insert(records: list[dict]) -> None:
    if not records:
        return
    await asyncio.to_thread(_bulk_insert_sync, records)


def _delete_by_paper_sync(user_id: int, paper_id: int) -> None:
    client = get_milvus_client()
    col = settings.MILVUS_COLLECTION
    expr = f"user_id == {user_id} && paper_id == {paper_id}"
    try:
        client.delete(collection_name=col, filter=expr)
        logger.info(f"[milvus] deleted chunks for paper_id={paper_id} user_id={user_id}")
    except MilvusException as e:
        logger.warning(f"[milvus] delete failed (may not exist): {e}")


async def delete_by_paper(user_id: int, paper_id: int) -> None:
    await asyncio.to_thread(_delete_by_paper_sync, user_id, paper_id)


DEFAULT_CHUNK_OUTPUT_FIELDS = [
    "id",
    "content_en",
    "content_zh",
    "user_id",
    "paper_id",
    "folder_id",
    "chunk_type",
    "section",
    "page_num",
    "bbox",
    "block_id",
    "image_key",
]


def _read_entity_field(entity: Any, field_name: str) -> Any:
    if entity is None:
        return None
    if isinstance(entity, dict):
        return entity.get(field_name)
    getter = getattr(entity, "get", None)
    if callable(getter):
        try:
            return getter(field_name)
        except Exception:
            pass
    try:
        return entity[field_name]  # type: ignore[index]
    except Exception:
        pass
    return getattr(entity, field_name, None)


def _dense_search_sync(
    vector: list[float],
    filter_expr: str,
    limit: int,
    output_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    if "user_id" not in filter_expr:
        raise ValueError("Milvus search filter must include user_id")

    _ensure_collection_sync()
    client = get_milvus_client()
    fields = output_fields or DEFAULT_CHUNK_OUTPUT_FIELDS
    results = client.search(
        collection_name=settings.MILVUS_COLLECTION,
        data=[vector],
        anns_field="dense_vec",
        search_params={"metric_type": settings.MILVUS_METRIC, "params": {"ef": 64}},
        filter=filter_expr,
        limit=limit,
        output_fields=fields,
    )

    hits: list[dict[str, Any]] = []
    for hit in results[0] if results else []:
        entity = hit.get("entity", {}) if isinstance(hit, dict) else getattr(hit, "entity", None)
        entity_dict = _read_entity_field(entity, "entity")
        if not isinstance(entity_dict, dict):
            entity_dict = _object_to_dict(entity)
        if isinstance(entity_dict.get("entity"), dict):
            entity_dict = entity_dict["entity"]

        record: dict[str, Any] = {}
        for field_name in fields:
            value = entity_dict.get(field_name)
            if value is not None:
                record[field_name] = value

        if isinstance(hit, dict):
            for key, value in hit.items():
                if key != "entity" and value is not None:
                    record.setdefault(key, value)
            hit_id = hit.get("id") or record.get("id")
            score = hit.get("score", hit.get("distance", 0.0))
        else:
            hit_id = getattr(hit, "id", None) or record.get("id")
            score = getattr(hit, "score", None)
            if score is None:
                score = getattr(hit, "distance", 0.0)

        record["id"] = str(hit_id or record.get("id", ""))
        record["score"] = float(score or 0.0)
        hits.append(record)
    return hits


async def dense_search(
    vector: list[float],
    filter_expr: str,
    limit: int,
    output_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run tenant-safe dense vector search over indexed Milvus chunks."""
    return await asyncio.to_thread(_dense_search_sync, vector, filter_expr, limit, output_fields)
