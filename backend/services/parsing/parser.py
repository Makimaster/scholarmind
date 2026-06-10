"""
parse_paper: PDF → doc_blocks (MySQL) + citations (MySQL) + figures (MinIO).
"""
from __future__ import annotations

import asyncio
import base64
from collections import Counter
import html
import json
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from common.clients.llm import chat_complete_json, vlm_describe_image
from common.clients.minio import download_pdf, presigned_get_url, upload_figure
from common.config import settings
from common.logging import logger
from common.prompts import load_prompt


@dataclass
class Block:
    block_type: str
    content: str
    page_num: int | None = None
    bbox: list | None = None
    image_key: str | None = None
    image_bytes: bytes | None = None
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


def _object_to_dict(value: Any) -> dict[str, Any]:
    """Best-effort object-to-dict conversion for version-tolerant Docling adapters."""
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


def _value_from_any(value: Any, keys: tuple[str, ...], default: Any = None) -> Any:
    data = _object_to_dict(value)
    for key in keys:
        if isinstance(data, dict) and data.get(key) not in (None, ""):
            return data[key]
        attr = getattr(value, key, None)
        if attr not in (None, ""):
            return attr
    return default


def _first_prov(item: Any) -> Any:
    prov = _value_from_any(item, ("prov", "provenance", "provs"))
    if isinstance(prov, list) and prov:
        return prov[0]
    return prov


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_docling_page_num(item: Any) -> int | None:
    prov = _first_prov(item)
    return _to_int(
        _value_from_any(prov, ("page_no", "page_num", "page"))
        or _value_from_any(item, ("page_no", "page_num", "page"))
    )


def _bbox_values(raw_bbox: Any) -> list[float] | None:
    if raw_bbox is None:
        return None
    data = _object_to_dict(raw_bbox)
    if isinstance(raw_bbox, (list, tuple)):
        values = [_to_float(item) for item in raw_bbox]
        return [item for item in values if item is not None]
    if isinstance(data, dict):
        key_sets = (
            ("l", "t", "r", "b"),
            ("left", "top", "right", "bottom"),
            ("x0", "y0", "x1", "y1"),
        )
        for keys in key_sets:
            values = [_to_float(data.get(key)) for key in keys]
            if all(item is not None for item in values):
                return [item for item in values if item is not None]
    return None


def _extract_docling_bbox(item: Any, page_num: int | None) -> list | None:
    prov = _first_prov(item)
    raw_bbox = _value_from_any(prov, ("bbox", "box", "coordinates", "coord")) or _value_from_any(
        item, ("bbox", "box", "coordinates", "coord")
    )
    values = _bbox_values(raw_bbox)
    if not values:
        return None
    if len(values) == 5:
        return values
    if len(values) >= 4:
        return ([page_num] if page_num is not None else []) + values[:4]
    return None


def _docling_label(item: Any, fallback: str = "text") -> str:
    value = _value_from_any(item, ("label", "type", "category", "name"), fallback)
    return str(value or fallback).lower()


def _docling_block_type(item: Any, source_key: str = "") -> str:
    label = f"{source_key} {_docling_label(item)}".lower()
    if any(token in label for token in ("table", "tabular")):
        return "table"
    if any(token in label for token in ("picture", "figure", "image", "chart")):
        return "figure"
    if any(token in label for token in ("formula", "equation")):
        return "formula"
    return "text"


def _build_docling_ref_lookup(exported: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for value in exported.values():
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            ref = item.get("self_ref") or item.get("ref") or item.get("id")
            if ref:
                lookup[str(ref)] = item
    return lookup


def _caption_from_refs(item: Any, ref_lookup: dict[str, dict[str, Any]]) -> str:
    captions = _value_from_any(item, ("captions", "caption_refs"))
    if not isinstance(captions, list):
        direct = _value_from_any(item, ("caption",))
        return str(direct or "")
    parts: list[str] = []
    for caption in captions:
        ref = caption.get("$ref") if isinstance(caption, dict) else caption
        referenced = ref_lookup.get(str(ref)) if ref is not None else None
        text_value = _value_from_any(referenced or caption, ("text", "orig", "content", "caption"))
        if text_value:
            parts.append(str(text_value))
    return "\n".join(parts)


def _table_cells_to_html(data: Any) -> str:
    table_data = _object_to_dict(data)
    cells = table_data.get("table_cells") or table_data.get("cells")
    if not isinstance(cells, list):
        return ""
    rows: dict[int, dict[int, str]] = {}
    for cell in cells:
        cell_data = _object_to_dict(cell)
        row = _to_int(cell_data.get("start_row_offset_idx") or cell_data.get("row") or cell_data.get("row_idx"))
        col = _to_int(cell_data.get("start_col_offset_idx") or cell_data.get("col") or cell_data.get("col_idx"))
        if row is None or col is None:
            continue
        text_value = str(cell_data.get("text") or cell_data.get("content") or "")
        rows.setdefault(row, {})[col] = text_value
    if not rows:
        return ""
    lines = ["<table>"]
    for row_index in sorted(rows):
        lines.append("  <tr>")
        for col_index in sorted(rows[row_index]):
            lines.append(f"    <td>{html.escape(rows[row_index][col_index])}</td>")
        lines.append("  </tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _docling_image_bytes(item: Any) -> bytes | None:
    for key in ("image_bytes", "image", "picture", "data"):
        value = _value_from_any(item, (key,))
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            if value.startswith("data:image"):
                value = value.split(",", 1)[-1]
            try:
                return base64.b64decode(value, validate=False)
            except Exception:
                pass

    for method_name in ("get_image", "get_pil_image", "image"):
        method = getattr(item, method_name, None)
        if not callable(method):
            continue
        try:
            image = method()
            save = getattr(image, "save", None)
            if callable(save):
                buffer = BytesIO()
                save(buffer, format="PNG")
                return buffer.getvalue()
        except Exception:
            pass
    return None


def _crop_figure_from_pdf(pdf_bytes: bytes, page_num: int | None, bbox: list | None) -> bytes | None:
    """Crop a figure region from PDF using PyMuPDF; returns PNG bytes or None."""
    if not pdf_bytes or page_num is None or not bbox:
        return None
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_index = int(page_num) - 1  # page_num is 1-based
        if page_index < 0 or page_index >= len(doc):
            return None
        page = doc[page_index]
        # bbox may be [x0, y0, x1, y1] or a string like "x0,y0,x1,y1"
        if isinstance(bbox, str):
            parts = [float(v) for v in bbox.replace(",", " ").split()]
        else:
            parts = [float(v) for v in bbox]
        if len(parts) < 4:
            return None
        rect = fitz.Rect(*parts[:4])
        if rect.is_empty or rect.is_infinite:
            return None
        clip = page.get_pixmap(clip=rect, dpi=150)
        return clip.tobytes("png")
    except Exception as exc:
        logger.warning(f"[parse] PDF bbox crop failed page={page_num} bbox={bbox}: {exc}")
        return None


def _docling_content_for_item(item: Any, block_type: str, ref_lookup: dict[str, dict[str, Any]]) -> str:
    if block_type == "table":
        for method_name in ("export_to_html", "export_to_markdown"):
            method = getattr(item, method_name, None)
            if callable(method):
                try:
                    rendered = method()
                    if rendered:
                        return str(rendered)
                except Exception:
                    pass
        direct = _value_from_any(item, ("html", "markdown", "text", "orig", "content"))
        if direct:
            return str(direct)
        table_data = _value_from_any(item, ("data", "table_data"))
        return _table_cells_to_html(table_data)
    if block_type == "figure":
        caption = _caption_from_refs(item, ref_lookup)
        if caption:
            return caption
        return str(_value_from_any(item, ("caption", "text", "orig", "content"), ""))
    if block_type == "formula":
        return str(_value_from_any(item, ("latex", "text", "orig", "content"), ""))
    return str(_value_from_any(item, ("text", "orig", "content", "markdown"), ""))


def _docling_top_level_items(exported: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for key in ("texts", "tables", "pictures", "figures", "formulas", "equations"):
        value = exported.get(key)
        if isinstance(value, list):
            candidates.extend((key, item) for item in value if isinstance(item, dict))
    return candidates


def _docling_recursive_items(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(payload, dict):
        has_content = any(key in payload for key in ("text", "orig", "content", "html", "markdown", "data"))
        has_type = any(key in payload for key in ("label", "type", "category"))
        if has_content and has_type:
            found.append((str(payload.get("label") or payload.get("type") or "item"), payload))
        for value in payload.values():
            found.extend(_docling_recursive_items(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_docling_recursive_items(item))
    return found


def _docling_to_blocks(document: Any, exported: dict[str, Any], user_id: int, paper_id: int) -> list[Block]:
    ref_lookup = _build_docling_ref_lookup(exported)
    raw_items = _docling_top_level_items(exported) or _docling_recursive_items(exported)
    blocks: list[Block] = []
    seen: set[str] = set()
    for index, (source_key, item) in enumerate(raw_items, start=1):
        ref = str(item.get("self_ref") or item.get("id") or f"{source_key}:{index}")
        if ref in seen:
            continue
        seen.add(ref)
        block_type = _docling_block_type(item, source_key)
        content = _docling_content_for_item(item, block_type, ref_lookup).strip()
        if not content and block_type != "figure":
            continue
        page_num = _extract_docling_page_num(item)
        bbox = _extract_docling_bbox(item, page_num)
        if page_num is None or bbox is None:
            logger.warning(f"[parse] Docling block missing page_num/bbox paper_id={paper_id} type={block_type}")
        image_bytes = _docling_image_bytes(item) if block_type == "figure" else None
        blocks.append(Block(block_type=block_type, content=content, page_num=page_num, bbox=bbox, image_bytes=image_bytes))

    blocks.sort(key=lambda block: (
        block.page_num or 10**9,
        # bbox format: [page, left, top, right, bottom] (index 1=left, 2=top)
        # Two-column layout: left column (left < 0.5 page_width) before right column.
        # Within a column, sort top-to-bottom (ascending top).
        round((block.bbox[1] if block.bbox and len(block.bbox) >= 5 else 0) / 300) if block.bbox else 1,
        block.bbox[2] if block.bbox and len(block.bbox) >= 5 else 10**9,
    ))
    return blocks


def _extract_docling_metadata(document: Any, exported: dict[str, Any]) -> dict[str, Any]:
    metadata = exported.get("metadata") if isinstance(exported.get("metadata"), dict) else {}
    title = metadata.get("title") or _value_from_any(document, ("title", "name"))
    if not title:
        for text_item in exported.get("texts", []) if isinstance(exported.get("texts"), list) else []:
            if _docling_label(text_item) in {"title", "document_title"}:
                title = _value_from_any(text_item, ("text", "orig", "content"))
                break
    return {
        "title": title,
        "abstract": metadata.get("abstract"),
        "authors": metadata.get("authors"),
        "year": metadata.get("year"),
        "doi": metadata.get("doi"),
        "num_pages": metadata.get("num_pages") or metadata.get("page_count") or metadata.get("pages"),
        "lang": metadata.get("lang") or metadata.get("language"),
    }


async def _parse_with_docling(pdf_bytes: bytes, user_id: int, paper_id: int) -> tuple[list[Block], dict[str, Any]]:
    os.environ.setdefault("DOCLING_ARTIFACTS_PATH", settings.DOCLING_ARTIFACTS_PATH)
    started = time.perf_counter()

    def _run_docling() -> tuple[list[Block], dict[str, Any]]:
        try:
            from docling.document_converter import DocumentConverter
        except ModuleNotFoundError as exc:
            raise RuntimeError("docling is not installed in the current Python environment") from exc

        def _build_converter() -> Any:
            try:
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import PdfPipelineOptions
                from docling.document_converter import PdfFormatOption

                pipeline_options = PdfPipelineOptions()
                pipeline_options.do_ocr = settings.DOCLING_ENABLE_OCR
                pipeline_options.do_table_structure = settings.DOCLING_ENABLE_TABLE_STRUCTURE
                return DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - Docling option APIs vary across versions.
                logger.warning(f"[parse] Docling option setup failed, using default converter: {exc}")
                return DocumentConverter()

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp.flush()
                tmp_path = Path(tmp.name)

            converter = _build_converter()
            result = converter.convert(str(tmp_path))
            document = result.document
            if hasattr(document, "export_to_dict"):
                exported = document.export_to_dict()
            else:
                exported = _object_to_dict(document)
            if not isinstance(exported, dict):
                exported = {}
            blocks = _docling_to_blocks(document, exported, user_id, paper_id)
            metadata = _extract_docling_metadata(document, exported)
            return blocks, metadata
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    blocks, metadata = await asyncio.to_thread(_run_docling)
    counts = Counter(block.block_type for block in blocks)
    missing_page = sum(1 for block in blocks if block.page_num is None)
    missing_bbox = sum(1 for block in blocks if block.bbox is None)
    logger.info(
        f"[parse] Docling returned {len(blocks)} blocks paper_id={paper_id} "
        f"types={dict(counts)} missing_page={missing_page} missing_bbox={missing_bbox} "
        f"elapsed_ms={int((time.perf_counter() - started) * 1000)}"
    )
    return blocks, metadata


async def _parse_document(
    pdf_key: str,
    pdf_bytes: bytes,
    user_id: int,
    paper_id: int,
) -> tuple[list[Block], dict[str, Any]]:
    provider = settings.DOCUMENT_PARSER_PROVIDER.lower().strip()
    fallback_provider = settings.DOCUMENT_PARSER_FALLBACK_PROVIDER.lower().strip()

    async def _run_provider(selected_provider: str) -> tuple[list[Block], dict[str, Any]]:
        if selected_provider == "docling":
            return await _parse_with_docling(pdf_bytes, user_id, paper_id)
        if selected_provider == "mineru":
            raw_result = await _call_mineru(pdf_key, pdf_bytes)
            blocks = await _mineru_to_blocks(raw_result, user_id, paper_id)
            logger.info(f"[parse] MinerU returned {len(blocks)} blocks paper_id={paper_id}")
            return blocks, _metadata_from_result(raw_result)
        raise RuntimeError(f"Unsupported document parser provider: {selected_provider}")

    try:
        blocks, metadata = await _run_provider(provider)
        if not blocks:
            raise RuntimeError(f"document parser returned no blocks provider={provider}")
        return blocks, metadata
    except Exception as exc:
        if fallback_provider == "mineru" and provider != "mineru":
            logger.warning(f"[parse] provider={provider} failed, falling back to MinerU paper_id={paper_id}: {exc}")
            blocks, metadata = await _run_provider("mineru")
            if not blocks:
                raise RuntimeError("MinerU fallback returned no blocks") from exc
            return blocks, metadata
        raise


async def _upload_docling_figures(blocks: list[Block], user_id: int, paper_id: int, pdf_bytes: bytes | None = None) -> None:
    for index, block in enumerate(blocks, start=1):
        if block.block_type != "figure" or block.image_key:
            continue
        image_bytes = block.image_bytes
        if not image_bytes and pdf_bytes:
            image_bytes = _crop_figure_from_pdf(pdf_bytes, block.page_num, block.bbox)
        if not image_bytes:
            continue
        try:
            block.image_key = await upload_figure(user_id, paper_id, f"docling-figure-{index}.png", image_bytes)
        except Exception as exc:  # noqa: BLE001 - figure upload should not drop parsed text.
            logger.warning(f"[parse] Docling figure upload failed paper_id={paper_id} index={index}: {exc}")


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

    prompt_template = load_prompt("extract_references")
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


async def _extract_grobid_metadata_and_refs(pdf_bytes: bytes) -> tuple[dict[str, Any], list[dict]]:
    url = f"{settings.GROBID_BASE_URL}/api/processFulltextDocument"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url,
            files={"input": ("paper.pdf", pdf_bytes, "application/pdf")},
            data={"consolidateReferences": "0", "teiCoordinates": "ref"},
        )
        resp.raise_for_status()

    return _parse_tei_metadata(resp.text), _parse_tei_references(resp.text)


async def _extract_refs_grobid(pdf_bytes: bytes) -> list[dict]:
    _, references = await _extract_grobid_metadata_and_refs(pdf_bytes)
    return references


def _find_first_text(root: ET.Element, paths: tuple[str, ...], ns: dict[str, str]) -> str:
    for path in paths:
        element = root.find(path, ns)
        if element is not None and element.text:
            return element.text.strip()
    return ""


def _tei_author_names(root: ET.Element, ns: dict[str, str]) -> list[str]:
    authors: list[str] = []
    for author in root.findall(".//tei:fileDesc/tei:sourceDesc//tei:analytic/tei:author", ns):
        pers_name = author.find("tei:persName", ns)
        if pers_name is None:
            continue
        forename = " ".join(item.text.strip() for item in pers_name.findall("tei:forename", ns) if item.text)
        surname = pers_name.findtext("tei:surname", "", ns).strip()
        name = f"{forename} {surname}".strip()
        if name:
            authors.append(name)
    return authors


def _parse_tei_metadata(tei_xml: str) -> dict[str, Any]:
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError as e:
        logger.warning(f"GROBID TEI metadata parse error: {e}")
        return {}

    title = _find_first_text(
        root,
        (
            ".//tei:fileDesc/tei:titleStmt/tei:title[@type='main']",
            ".//tei:fileDesc/tei:titleStmt/tei:title",
            ".//tei:analytic/tei:title[@level='a']",
            ".//tei:analytic/tei:title",
        ),
        ns,
    )
    abstract_parts = ["".join(element.itertext()).strip() for element in root.findall(".//tei:profileDesc/tei:abstract", ns)]
    abstract = "\n".join(part for part in abstract_parts if part)
    doi = _find_first_text(root, (".//tei:idno[@type='DOI']", ".//tei:idno[@type='doi']"), ns)
    year_text = ""
    date_el = root.find(".//tei:publicationStmt/tei:date", ns)
    if date_el is None:
        date_el = root.find(".//tei:monogr//tei:date", ns)
    if date_el is not None:
        year_text = date_el.get("when", "") or (date_el.text or "")
    year = int(year_text[:4]) if year_text[:4].isdigit() else None
    page_numbers = {
        int(element.get("n"))
        for element in root.findall(".//tei:pb", ns)
        if element.get("n") and element.get("n", "").isdigit()
    }
    lang = root.get("{http://www.w3.org/XML/1998/namespace}lang")
    return {
        "title": title or None,
        "abstract": abstract or None,
        "authors": _tei_author_names(root, ns) or None,
        "year": year,
        "doi": doi or None,
        "num_pages": max(page_numbers) if page_numbers else None,
        "lang": lang,
    }


def _parse_tei_references(tei_xml: str) -> list[dict]:
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError as e:
        logger.warning(f"GROBID TEI parse error: {e}")
        return []

    refs = []
    for bibl in root.findall(".//tei:listBibl/tei:biblStruct", ns):
        title_el = bibl.find(".//tei:title[@level='a']", ns)
        if title_el is None:
            title_el = bibl.find(".//tei:title", ns)
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
    logger.info(
        f"[parse] paper_id={paper_id} user_id={user_id} "
        f"document_provider={settings.DOCUMENT_PARSER_PROVIDER} reference_provider={settings.REFERENCE_PARSER_PROVIDER}"
    )

    if pdf_bytes is None:
        pdf_bytes = await download_pdf(pdf_key)
    blocks, metadata = await _parse_document(pdf_key, pdf_bytes, user_id, paper_id)
    await _upload_docling_figures(blocks, user_id, paper_id, pdf_bytes=pdf_bytes)

    vlm_task = asyncio.create_task(_describe_figures(blocks))

    if settings.REFERENCE_PARSER_PROVIDER == "grobid":
        try:
            grobid_metadata, references = await _extract_grobid_metadata_and_refs(pdf_bytes)
            metadata = {**metadata, **{key: value for key, value in grobid_metadata.items() if value not in (None, "", [])}}
        except Exception as exc:  # noqa: BLE001 - reference parsing should not block document ingestion.
            logger.warning(f"[parse] GROBID extraction failed, falling back to LLM references paper_id={paper_id}: {exc}")
            references = await _extract_refs_llm(blocks)
    else:
        references = await _extract_refs_llm(blocks)

    await vlm_task
    logger.info(f"[parse] extracted {len(references)} references")

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
                INSERT INTO doc_blocks (paper_id, user_id, block_type, content, content_zh, page_num, bbox, image_key)
                VALUES (:paper_id, :user_id, :block_type, :content, :content_zh, :page_num, :bbox, :image_key)
            """),
            {
                "paper_id": paper_id,
                "user_id": user_id,
                "block_type": block.block_type,
                "content": block.content,
                "content_zh": block.content_zh or None,
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
