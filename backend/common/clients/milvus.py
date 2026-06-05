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


def get_milvus_client() -> MilvusClient:
    global _client
    if _client is None:
        _client = MilvusClient(
            uri=settings.MILVUS_URI,
            token=settings.MILVUS_TOKEN or "",
        )
    return _client


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


def _build_index_params() -> Any:
    from pymilvus import MilvusClient
    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(
        field_name="dense_vec",
        index_type=settings.MILVUS_INDEX_TYPE,
        metric_type=settings.MILVUS_METRIC,
        params={"M": 16, "efConstruction": 200},
    )
    index_params.add_index(
        field_name="sparse_vec",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="IP",
        params={"drop_ratio_build": 0.2},
    )
    return index_params


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
        existing = client.describe_index(col, "dense_vec")
        if not existing:
            client.create_index(col, _build_index_params())
            logger.info(f"[milvus] index added to existing collection '{col}'")
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
