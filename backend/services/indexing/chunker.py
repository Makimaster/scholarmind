"""
chunker: split Block list into Chunk list.

table/figure/formula → preserved whole (no split).
text → SentenceSplitter(512 tokens, 80 overlap).
Section headers propagate to child chunks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.parsing.parser import Block


@dataclass
class Chunk:
    content_en: str
    content_zh: str = ""
    block_type: str = "text"
    page_num: int | None = None
    bbox: list | None = None
    block_id: int | None = None
    image_key: str | None = None
    section: str = ""


def _is_section_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("##"):
        return True
    if len(stripped) > 3 and stripped == stripped.upper() and re.search(r"[A-Z]", stripped):
        return True
    return False


def _get_splitter():
    from llama_index.core.node_parser import SentenceSplitter
    return SentenceSplitter(chunk_size=512, chunk_overlap=80)


def chunk_blocks(blocks: list) -> list[Chunk]:
    splitter = _get_splitter()
    chunks: list[Chunk] = []
    current_section = ""

    for block in blocks:
        block_type: str = block.block_type
        content: str = block.content or ""
        page_num = block.page_num
        bbox = block.bbox
        block_id = block.block_id
        image_key = block.image_key
        content_zh: str = getattr(block, "content_zh", "") or ""

        if block_type in ("table", "figure", "formula"):
            chunks.append(
                Chunk(
                    content_en=content,
                    content_zh=content_zh,
                    block_type=block_type,
                    page_num=page_num,
                    bbox=bbox,
                    block_id=block_id,
                    image_key=image_key,
                    section=current_section,
                )
            )
            continue

        if not content.strip():
            continue

        first_line = content.split("\n", 1)[0]
        if _is_section_header(first_line):
            current_section = first_line.strip().lstrip("#").strip()
            if len(content.strip()) < 200:
                chunks.append(
                    Chunk(
                        content_en=content,
                        block_type="text",
                        page_num=page_num,
                        bbox=bbox,
                        block_id=block_id,
                        image_key=image_key,
                        section=current_section,
                    )
                )
                continue

        try:
            from llama_index.core.schema import Document
            doc = Document(text=content)
            nodes = splitter.get_nodes_from_documents([doc])
            sub_texts = [n.get_content() for n in nodes if n.get_content().strip()]
        except Exception:
            sub_texts = [content]

        for sub in sub_texts:
            chunks.append(
                Chunk(
                    content_en=sub,
                    block_type="text",
                    page_num=page_num,
                    bbox=bbox,
                    block_id=block_id,
                    image_key=image_key,
                    section=current_section,
                )
            )

    return chunks
