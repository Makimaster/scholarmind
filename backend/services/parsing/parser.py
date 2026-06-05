"""
parse_paper: PDF → doc_blocks (MySQL) + citations (MySQL) + figures (MinIO).
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from common.clients.llm import chat_complete_json, vlm_describe_image
from common.clients.minio import download_pdf, presigned_get_url, upload_figure
from common.config import settings
from common.logging import logger


@dataclass
class Block:
    block_type: str
    content: str
    page_num: int | None = None
    bbox: list | None = None
    image_key: str | None = None
    content_zh: str = ""
    block_id: int | None = None


@dataclass
class ParseResult:
    paper_id: int
    user_id: int
    blocks: list[Block] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)
    title: str = ""
    abstract: str = ""


def _load_prompt(name: str) -> str:
    path = Path(__file__).parents[3] / "prompts" / f"{name}.md"
    text_content = path.read_text(encoding="utf-8")
    match = re.search(r"```\s*\n(.*?)\n```", text_content, re.DOTALL)
    return match.group(1) if match else text_content


def _first_value(data: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def _flatten_blocks(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("blocks", "content", "items", "layouts", "result", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _flatten_blocks(value)
            if nested:
                return nested
    pages = payload.get("pages")
    if isinstance(pages, list):
        blocks: list[dict[str, Any]] = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            page_num = _first_value(page, ("page_num", "page", "page_idx", "page_no"))
            for item in page.get("blocks") or page.get("items") or page.get("layouts") or []:
                if isinstance(item, dict):
                    copied = dict(item)
                    copied.setdefault("page_num", page_num)
                    blocks.append(copied)
        return blocks
    return []


def _normalize_block_type(raw_type: str) -> str:
    value = raw_type.lower()
    if value in {"table"}:
        return "table"
    if value in {"figure", "image", "fig", "picture"}:
        return "figure"
    if value in {"formula", "equation", "inline_formula", "interline_equation"}:
        return "formula"
    return "text"


async def _instantiate_mineru_client() -> Any:
    try:
        from mineru_kie_sdk import MineruKIEClient
    except ModuleNotFoundError as exc:
        try:
            from mineru import MineruKIEClient
        except ModuleNotFoundError:
            raise RuntimeError("mineru-kie-sdk is not installed in the current Python environment") from exc

    if not settings.MINERU_PIPELINE_ID:
        raise RuntimeError("MINERU_PIPELINE_ID is required for MineruKIEClient")

    return MineruKIEClient(
        base_url=settings.MINERU_BASE_URL,
        pipeline_id=settings.MINERU_PIPELINE_ID,
        timeout=30,
    )


async def _call_mineru(pdf_key: str, pdf_bytes: bytes | None = None) -> Any:
    data = pdf_bytes if pdf_bytes is not None else await download_pdf(pdf_key)
    client = await _instantiate_mineru_client()

    def _run_sdk() -> Any:
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(data)
                tmp.flush()
                tmp_path = Path(tmp.name)
            file_ids = client.upload_file(tmp_path)
            results = client.get_result(file_ids, timeout=300, poll_interval=5)
            return results.get("parse") or results.get("split") or results.get("extract") or results
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    return await asyncio.to_thread(_run_sdk)


async def _download_image_from_url(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


def _decode_image_bytes(raw_block: dict[str, Any]) -> bytes | None:
    value = _first_value(raw_block, ("image_bytes", "image", "image_base64", "base64"))
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        if value.startswith("data:image"):
            value = value.split(",", 1)[-1]
        try:
            return base64.b64decode(value, validate=False)
        except Exception:
            return None
    return None


async def _figure_image_key(raw_block: dict[str, Any], user_id: int, paper_id: int, index: int) -> str | None:
    existing_key = _first_value(raw_block, ("image_key", "minio_key"))
    if existing_key:
        return str(existing_key)

    image_bytes = _decode_image_bytes(raw_block)
    if image_bytes is None:
        image_url = _first_value(raw_block, ("image_url", "url"))
        if image_url:
            image_bytes = await _download_image_from_url(str(image_url))

    if image_bytes is None:
        return None

    image_name = str(_first_value(raw_block, ("image_id", "id", "name"), f"figure-{index}.png"))
    if not image_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        image_name = f"{image_name}.png"
    return await upload_figure(user_id, paper_id, image_name, image_bytes)


async def _mineru_to_blocks(raw_result: Any, user_id: int, paper_id: int) -> list[Block]:
    blocks: list[Block] = []
    for index, rb in enumerate(_flatten_blocks(raw_result), start=1):
        raw_type = str(_first_value(rb, ("type", "block_type", "category"), "text"))
        block_type = _normalize_block_type(raw_type)
        if block_type == "table":
            content = str(_first_value(rb, ("html", "content", "table_html", "text", "markdown"), ""))
        elif block_type == "formula":
            content = str(_first_value(rb, ("latex", "content", "text"), ""))
        elif block_type == "figure":
            content = str(_first_value(rb, ("caption", "content", "text"), ""))
        else:
            content = str(_first_value(rb, ("content", "text", "markdown"), ""))

        page_num = _first_value(rb, ("page_num", "page", "page_idx", "page_no"))
        bbox = _first_value(rb, ("bbox", "box", "coordinates", "coord"))
        image_key = await _figure_image_key(rb, user_id, paper_id, index) if block_type == "figure" else None
        if page_num is None or bbox is None:
            logger.warning(f"[parse] block missing page_num/bbox paper_id={paper_id} type={block_type}")
        blocks.append(
            Block(
                block_type=block_type,
                content=content,
                page_num=int(page_num) if isinstance(page_num, (int, float, str)) and str(page_num).isdigit() else None,
                bbox=bbox if isinstance(bbox, list) else None,
                image_key=image_key,
            )
        )
    return blocks


async def _describe_figures(blocks: list[Block]) -> None:
    figure_blocks = [b for b in blocks if b.block_type == "figure" and b.image_key]
    if not figure_blocks:
        return

    async def _describe(block: Block) -> None:
        try:
            image_url = await presigned_get_url(settings.MINIO_BUCKET_FIG, block.image_key or "")
            block.content_zh = await vlm_describe_image(image_url, caption=block.content)
            if block.content_zh:
                block.content = f"{block.content}\n\n中文图像描述：{block.content_zh}".strip()
        except Exception as e:
            logger.warning(f"VLM figure description failed for {block.image_key}: {e}")

    await asyncio.gather(*[_describe(b) for b in figure_blocks])


async def _extract_refs_llm(blocks: list[Block]) -> list[dict]:
    full_text = "\n".join(b.content for b in blocks if b.block_type == "text")
    ref_match = re.search(
        r"\b(?:References|Bibliography|参考文献)\b(.*)$",
        full_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not ref_match:
        logger.info("No references section found in document text")
        return []

    references_text = ref_match.group(1).strip()
    if len(references_text) < 50:
        return []

    prompt_template = _load_prompt("extract_references")
    prompt = prompt_template.format(references_text=references_text[:8000])

    try:
        result = await chat_complete_json(prompt, system="You are an academic reference parser.")
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if isinstance(result, dict):
            for value in result.values():
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
    except Exception as e:
        logger.warning(f"LLM reference extraction failed: {e}")

    return []


async def _extract_refs_grobid(pdf_bytes: bytes) -> list[dict]:
    url = f"{settings.GROBID_BASE_URL}/api/processFulltextDocument"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url,
            files={"input": ("paper.pdf", pdf_bytes, "application/pdf")},
            data={"consolidateReferences": "0"},
        )
        resp.raise_for_status()

    return _parse_tei_references(resp.text)


def _parse_tei_references(tei_xml: str) -> list[dict]:
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError as e:
        logger.warning(f"GROBID TEI parse error: {e}")
        return []

    refs = []
    for bibl in root.findall(".//tei:listBibl/tei:biblStruct", ns):
        title_el = bibl.find(".//tei:title[@level='a']", ns) or bibl.find(".//tei:title", ns)
        title = title_el.text if title_el is not None and title_el.text else ""

        authors = []
        for author in bibl.findall(".//tei:author/tei:persName", ns):
            forename = author.findtext("tei:forename", "", ns)
            surname = author.findtext("tei:surname", "", ns)
            name = f"{forename} {surname}".strip()
            if name:
                authors.append(name)

        year_el = bibl.find(".//tei:date[@type='published']", ns)
        year_text = year_el.get("when", "") if year_el is not None else ""
        year = int(year_text[:4]) if year_text and year_text[:4].isdigit() else None
        refs.append({"title": title, "authors": authors, "year": year, "raw_ref": ET.tostring(bibl, encoding="unicode")})

    return refs


def _metadata_from_result(raw_result: Any) -> dict[str, Any]:
    if not isinstance(raw_result, dict):
        return {}
    metadata = raw_result.get("metadata") if isinstance(raw_result.get("metadata"), dict) else raw_result
    return {
        "title": _first_value(metadata, ("title", "paper_title")),
        "abstract": _first_value(metadata, ("abstract",)),
        "authors": _first_value(metadata, ("authors",)),
        "year": _first_value(metadata, ("year",)),
        "doi": _first_value(metadata, ("doi",)),
        "num_pages": _first_value(metadata, ("num_pages", "page_count", "pages")),
        "lang": _first_value(metadata, ("lang", "language")),
    }


async def parse_paper(
    user_id: int,
    paper_id: int,
    pdf_key: str,
    db: AsyncSession,
    *,
    pdf_bytes: bytes | None = None,
) -> ParseResult:
    logger.info(f"[parse] paper_id={paper_id} user_id={user_id} provider={settings.REFERENCE_PARSER_PROVIDER}")

    if pdf_bytes is None:
        pdf_bytes = await download_pdf(pdf_key)
    raw_result = await _call_mineru(pdf_key, pdf_bytes)
    blocks = await _mineru_to_blocks(raw_result, user_id, paper_id)
    logger.info(f"[parse] MinerU returned {len(blocks)} blocks")

    vlm_task = asyncio.create_task(_describe_figures(blocks))

    if settings.REFERENCE_PARSER_PROVIDER == "grobid":
        references = await _extract_refs_grobid(pdf_bytes)
    else:
        references = await _extract_refs_llm(blocks)

    await vlm_task
    logger.info(f"[parse] extracted {len(references)} references")

    metadata = _metadata_from_result(raw_result)
    await _write_blocks(user_id, paper_id, blocks, db)
    await _write_citations(user_id, paper_id, references, db)
    await _update_paper_metadata(user_id, paper_id, metadata, db)
    await db.commit()

    return ParseResult(
        paper_id=paper_id,
        user_id=user_id,
        blocks=blocks,
        references=references,
        title=str(metadata.get("title") or ""),
        abstract=str(metadata.get("abstract") or ""),
    )


async def _write_blocks(user_id: int, paper_id: int, blocks: list[Block], db: AsyncSession) -> None:
    await db.execute(
        text("DELETE FROM doc_blocks WHERE user_id = :user_id AND paper_id = :paper_id"),
        {"user_id": user_id, "paper_id": paper_id},
    )
    for block in blocks:
        result = await db.execute(
            text("""
                INSERT INTO doc_blocks (paper_id, user_id, block_type, content, page_num, bbox, image_key)
                VALUES (:paper_id, :user_id, :block_type, :content, :page_num, :bbox, :image_key)
            """),
            {
                "paper_id": paper_id,
                "user_id": user_id,
                "block_type": block.block_type,
                "content": block.content,
                "page_num": block.page_num,
                "bbox": json.dumps(block.bbox) if block.bbox is not None else None,
                "image_key": block.image_key,
            },
        )
        block.block_id = int(result.lastrowid)


async def _write_citations(user_id: int, paper_id: int, references: list[dict], db: AsyncSession) -> None:
    await db.execute(
        text("""
            DELETE c FROM citations c
            JOIN papers p ON p.id = c.src_paper_id
            WHERE p.user_id = :user_id AND c.src_paper_id = :paper_id
        """),
        {"user_id": user_id, "paper_id": paper_id},
    )
    for ref in references:
        title = str(ref.get("title") or "")[:512]
        match_result = await db.execute(
            text("""
                SELECT id FROM papers
                WHERE user_id = :user_id AND title = :title
                LIMIT 1
            """),
            {"user_id": user_id, "title": title},
        )
        dst_paper_id = match_result.scalar_one_or_none() if title else None
        await db.execute(
            text("""
                INSERT INTO citations (src_paper_id, dst_paper_id, dst_title, raw_ref)
                VALUES (:src_paper_id, :dst_paper_id, :dst_title, :raw_ref)
            """),
            {
                "src_paper_id": paper_id,
                "dst_paper_id": dst_paper_id,
                "dst_title": title,
                "raw_ref": str(ref.get("raw_ref") or "")[:65535],
            },
        )


async def _update_paper_metadata(user_id: int, paper_id: int, metadata: dict[str, Any], db: AsyncSession) -> None:
    if not any(metadata.values()):
        return
    await db.execute(
        text("""
            UPDATE papers
            SET
                title = COALESCE(:title, title),
                abstract = COALESCE(:abstract, abstract),
                authors = COALESCE(:authors, authors),
                year = COALESCE(:year, year),
                doi = COALESCE(:doi, doi),
                num_pages = COALESCE(:num_pages, num_pages),
                lang = COALESCE(:lang, lang)
            WHERE id = :paper_id AND user_id = :user_id
        """),
        {
            "paper_id": paper_id,
            "user_id": user_id,
            "title": metadata.get("title"),
            "abstract": metadata.get("abstract"),
            "authors": json.dumps(metadata.get("authors"), ensure_ascii=False) if metadata.get("authors") else None,
            "year": metadata.get("year") if isinstance(metadata.get("year"), int) else None,
            "doi": metadata.get("doi"),
            "num_pages": metadata.get("num_pages") if isinstance(metadata.get("num_pages"), int) else None,
            "lang": metadata.get("lang"),
        },
    )
