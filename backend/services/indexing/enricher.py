"""
enricher: fill content_zh for each Chunk.

text (English)  → LLM with enrich_zh_summary.md prompt
table           → LLM with table_summary.md prompt
figure          → reuse content_zh from parser VLM stage
formula         → copy content_en as-is
text (Chinese)  → copy content_en as-is
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from common.clients.llm import chat_complete, chat_complete_json
from common.logging import logger
from services.indexing.chunker import Chunk

_BATCH_SIZE = 8


def _load_prompt(name: str) -> str:
    path = Path(__file__).parents[3] / "prompts" / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    return match.group(1) if match else text


def _is_english(text: str) -> bool:
    if not text:
        return False
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return ascii_chars / len(text) > 0.6


async def _enrich_text(chunk: Chunk) -> None:
    if not _is_english(chunk.content_en):
        chunk.content_zh = chunk.content_en
        return
    try:
        template = _load_prompt("enrich_zh_summary")
        prompt = template.format(
            chunk_text=chunk.content_en[:3000],
            section=chunk.section or "Unknown",
        )
        result = await chat_complete_json(prompt, system="You are an academic Chinese summarizer.")
        if isinstance(result, dict):
            summary = result.get("summary_zh", "")
            keywords = result.get("keywords_zh", [])
            if isinstance(keywords, list):
                keywords_str = "、".join(str(k) for k in keywords)
            else:
                keywords_str = str(keywords)
            chunk.content_zh = f"{summary}\n关键词：{keywords_str}".strip()
        else:
            chunk.content_zh = chunk.content_en[:200]
    except Exception as e:
        logger.warning(f"[enricher] text enrich failed: {e}")
        chunk.content_zh = chunk.content_en[:200]


async def _enrich_table(chunk: Chunk) -> None:
    try:
        template = _load_prompt("table_summary")
        lines = chunk.content_en.split("\n", 2)
        caption = lines[0] if len(lines) > 1 and len(lines[0]) < 200 else ""
        prompt = template.format(
            table_html=chunk.content_en[:4000],
            caption=caption,
        )
        result = await chat_complete(
            prompt,
            system="You are an academic table summarizer. Reply in Chinese only.",
            max_tokens=256,
        )
        chunk.content_zh = result.strip() or chunk.content_en[:200]
    except Exception as e:
        logger.warning(f"[enricher] table enrich failed: {e}")
        chunk.content_zh = chunk.content_en[:200]


async def enrich_chunks(chunks: list[Chunk]) -> list[Chunk]:
    text_chunks = [c for c in chunks if c.block_type == "text"]
    table_chunks = [c for c in chunks if c.block_type == "table"]

    for c in chunks:
        if c.block_type == "formula":
            c.content_zh = c.content_en
        elif c.block_type == "figure":
            if not c.content_zh:
                c.content_zh = c.content_en

    for i in range(0, len(text_chunks), _BATCH_SIZE):
        batch = text_chunks[i : i + _BATCH_SIZE]
        await asyncio.gather(*[_enrich_text(c) for c in batch])

    for i in range(0, len(table_chunks), _BATCH_SIZE):
        batch = table_chunks[i : i + _BATCH_SIZE]
        await asyncio.gather(*[_enrich_table(c) for c in batch])

    return chunks
