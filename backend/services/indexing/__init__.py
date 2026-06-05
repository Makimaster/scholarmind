from services.indexing.chunker import chunk_blocks, Chunk
from services.indexing.enricher import enrich_chunks
from services.indexing.vectorizer import vectorize_and_store
from common.clients.milvus import ensure_collection


async def index_paper(user_id, paper_id, folder_id, blocks, db):
    await ensure_collection()
    chunks = chunk_blocks(blocks)
    chunks = await enrich_chunks(chunks)
    await vectorize_and_store(chunks, user_id, paper_id, folder_id, db)


__all__ = ["index_paper", "chunk_blocks", "enrich_chunks", "vectorize_and_store", "Chunk"]
