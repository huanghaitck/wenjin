from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import median
from typing import Any

import pymupdf as fitz

from .db import append_audit, connect
from .service import import_structure


SENTENCE_ENDINGS = ("。", "！", "？", "；", "：", ".", "!", "?", ";", ":", "”", "’", '"', "'")
PRINTED_PAGE = re.compile(r"^(?:\d{1,4}|[ivxlcdmIVXLCDM]{1,12})$")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _source_record(project_root: Path, source_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute(
            """SELECT s.source_id, s.title, sv.project_path, sv.sha256
               FROM sources s JOIN source_versions sv ON sv.source_id = s.source_id
               WHERE s.source_id = ? ORDER BY sv.created_at DESC LIMIT 1""",
            (source_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"unknown source: {source_id}")
    return dict(row)


def _normalized_region(bbox: tuple[float, float, float, float], width: float, height: float) -> dict[str, float]:
    x0, y0, x1, y1 = bbox
    return {
        "x0": round(max(0.0, min(1.0, x0 / width)), 6),
        "y0": round(max(0.0, min(1.0, y0 / height)), 6),
        "x1": round(max(0.0, min(1.0, x1 / width)), 6),
        "y1": round(max(0.0, min(1.0, y1 / height)), 6),
    }


def _extract_raw_blocks(page: fitz.Page) -> list[dict[str, Any]]:
    page_dict = page.get_text("dict", sort=True)
    raw: list[dict[str, Any]] = []
    for item in page_dict.get("blocks", []):
        if item.get("type") != 0:
            continue
        lines: list[str] = []
        sizes: list[float] = []
        for line in item.get("lines", []):
            line_text = "".join(str(span.get("text", "")) for span in line.get("spans", []))
            if line_text.strip():
                lines.append(line_text.rstrip())
            sizes.extend(float(span.get("size", 0.0)) for span in line.get("spans", []) if span.get("text"))
        text = "\n".join(lines).strip()
        if not text:
            continue
        raw.append({
            "bbox": tuple(float(value) for value in item["bbox"]),
            "text": text,
            "font_size": median(sizes) if sizes else 0.0,
        })
    return raw


def _classify_blocks(raw: list[dict[str, Any]], width: float, height: float) -> list[dict[str, Any]]:
    page_font = median([block["font_size"] for block in raw if block["font_size"] > 0]) if raw else 0.0
    blocks: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        region = _normalized_region(item["bbox"], width, height)
        text = item["text"]
        if region["y1"] <= 0.09:
            block_type = "page_number" if PRINTED_PAGE.fullmatch(text.strip()) else "header"
        elif region["y0"] >= 0.91:
            block_type = "page_number" if PRINTED_PAGE.fullmatch(text.strip()) else "footer"
        elif page_font and item["font_size"] >= page_font * 1.3 and len(text) <= 160:
            block_type = "heading"
        elif page_font and region["y0"] >= 0.68 and item["font_size"] <= page_font * 0.86:
            block_type = "footnote"
        else:
            block_type = "paragraph"
        blocks.append({
            "id": f"B{index:03d}",
            "order": index,
            "type": block_type,
            "text": text,
            "region": region,
        })
    return blocks


def _printed_page(blocks: list[dict[str, Any]]) -> str | None:
    candidates = []
    for block in blocks:
        if block["type"] not in {"header", "footer", "page_number"}:
            continue
        candidates.extend(line.strip() for line in block["text"].splitlines() if PRINTED_PAGE.fullmatch(line.strip()))
    return candidates[0] if len(candidates) == 1 else None


def _corrupt_text(text: str) -> bool:
    return "�" in text or "\x00" in text


def _fragmented_layout(blocks: list[dict[str, Any]]) -> bool:
    regions = [block["region"] for block in blocks]
    for index, left in enumerate(regions):
        left_area = max(0.0, left["x1"] - left["x0"]) * max(0.0, left["y1"] - left["y0"])
        if not left_area:
            continue
        for right in regions[index + 1:]:
            right_area = max(0.0, right["x1"] - right["x0"]) * max(0.0, right["y1"] - right["y0"])
            overlap_width = max(0.0, min(left["x1"], right["x1"]) - max(left["x0"], right["x0"]))
            overlap_height = max(0.0, min(left["y1"], right["y1"]) - max(left["y0"], right["y0"]))
            if right_area and overlap_width * overlap_height / min(left_area, right_area) >= 0.15:
                return True
    return False


def _body_blocks(page: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        block for block in page["blocks"]
        if block["type"] not in {"header", "footer", "page_number"} and block["text"].strip()
    ]


def _page_markdown(page: dict[str, Any]) -> str:
    image_path = Path(page["image_path"])
    lines = [
        f'<!-- physical_page: {page["physical_page"]} -->',
        f'<!-- printed_page: {page.get("printed_page") or "unknown"} -->',
        f'<!-- verification_state: machine_parsed -->',
        "",
        f'![PDF physical page {page["physical_page"]}](../pages/{image_path.name})',
        "",
    ]
    if not page["blocks"]:
        lines.extend(["> [!warning] No usable PDF text layer was found on this page.", ""])
    for block in page["blocks"]:
        region = json.dumps(block["region"], ensure_ascii=False, sort_keys=True)
        lines.extend([
            f'<!-- block: {block["id"]}; type: {block["type"]}; region: {region} -->',
            block["text"],
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def _failed_packet(source_id: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "processor": {"name": "hrw-pymupdf", "version": "m2"},
        "source_id": source_id,
        "pages": [],
        "relations": [],
        "anomalies": [{
            "id": "A_SOURCE_PDF_READ_FAILED",
            "scope_type": "source",
            "target_id": source_id,
            "severity": "systemic",
            "category": "content",
            "message": message,
        }],
    }


def ingest_pdf(project_root: Path, source_id: str, render_scale: float = 1.5) -> dict[str, Any]:
    if render_scale <= 0:
        raise ValueError("render_scale must be positive")
    project_root = project_root.resolve()
    source = _source_record(project_root, source_id)
    pdf_path = project_root / source["project_path"]
    artifact_root = project_root / "sources" / source_id / "derived" / "m2"
    page_image_dir = artifact_root / "pages"
    page_markdown_dir = artifact_root / "markdown"
    packet_path = artifact_root / "structure.json"
    document_path = artifact_root / "document.md"
    page_image_dir.mkdir(parents=True, exist_ok=True)
    page_markdown_dir.mkdir(parents=True, exist_ok=True)

    try:
        document = fitz.open(pdf_path)
    except Exception as error:
        packet = _failed_packet(source_id, f"PDF could not be opened: {error}")
        _write_json(packet_path, packet)
        receipt = import_structure(project_root, source_id, packet_path)
        return {
            "source_id": source_id,
            "status": "blocked",
            "page_count": 0,
            "error": packet["anomalies"][0]["message"],
            "receipt": receipt,
            "structure_path": packet_path.relative_to(project_root).as_posix(),
        }

    pages: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    usable_text_pages = 0
    try:
        for page_index, pdf_page in enumerate(document):
            physical_page = page_index + 1
            width, height = float(pdf_page.rect.width), float(pdf_page.rect.height)
            page_local_id = f"P{physical_page:04d}"
            image_relative = Path("sources") / source_id / "derived" / "m2" / "pages" / f"page-{physical_page:04d}.png"
            image_path = project_root / image_relative
            pixmap = pdf_page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=False)
            pixmap.save(image_path)

            raw_blocks = _extract_raw_blocks(pdf_page)
            blocks = _classify_blocks(raw_blocks, width, height)
            for block in blocks:
                block["id"] = f"{page_local_id}_{block['id']}"
            text_length = sum(len(block["text"].strip()) for block in blocks)
            if text_length >= 20:
                usable_text_pages += 1
            page = {
                "id": page_local_id,
                "physical_page": physical_page,
                "printed_page": _printed_page(blocks),
                "page_type": "text" if blocks else "image_or_blank",
                "width_points": round(width, 3),
                "height_points": round(height, 3),
                "image_path": image_relative.as_posix(),
                "blocks": blocks,
            }
            pages.append(page)
            if not blocks:
                anomalies.append({
                    "id": f"A_{page_local_id}_NO_TEXT_LAYER",
                    "scope_type": "page",
                    "target_id": page_local_id,
                    "severity": "local",
                    "category": "content",
                    "message": "No usable PDF text layer was found; inspect the rendered page and transcribe or OCR it.",
                })
            elif _fragmented_layout(blocks):
                anomalies.append({
                    "id": f"A_{page_local_id}_FRAGMENTED_LAYOUT",
                    "scope_type": "page",
                    "target_id": page_local_id,
                    "severity": "local",
                    "category": "content",
                    "message": "PDF text blocks overlap in reading space; extracted body order is unsafe until the rendered page is reviewed.",
                })
            for block in blocks:
                if _corrupt_text(block["text"]):
                    anomalies.append({
                        "id": f"A_{block['id']}_CORRUPT_TEXT",
                        "scope_type": "block",
                        "target_id": block["id"],
                        "severity": "local",
                        "category": "content",
                        "message": "The extracted block contains invalid replacement or null characters.",
                    })
            markdown_relative = Path("sources") / source_id / "derived" / "m2" / "markdown" / f"page-{physical_page:04d}.md"
            page["markdown_path"] = markdown_relative.as_posix()
            _write_text(project_root / markdown_relative, _page_markdown(page))
    finally:
        document.close()

    for page_index in range(len(pages) - 1):
        left_body = _body_blocks(pages[page_index])
        right_body = _body_blocks(pages[page_index + 1])
        if not left_body or not right_body:
            continue
        left, right = left_body[-1], right_body[0]
        relation_id = f"R_CONT_{page_index + 1:04d}_{page_index + 2:04d}"
        possible = len(left["text"].strip()) >= 20 and not left["text"].rstrip().endswith(SENTENCE_ENDINGS)
        relations.append({
            "id": relation_id,
            "from_block": left["id"],
            "to_block": right["id"],
            "type": "continues_on_next_page",
            "value": {
                "continues": None if possible else False,
                "confidence": "requires_human" if possible else "high",
                "reason": "previous page lacks terminal punctuation" if possible else "previous page has terminal punctuation",
            },
        })
        if possible:
            anomalies.append({
                "id": f"A_{relation_id}_REVIEW",
                "scope_type": "relation",
                "target_id": relation_id,
                "severity": "local",
                "category": "location",
                "message": "Possible cross-page continuation must be confirmed against both rendered pages.",
            })

    if pages and usable_text_pages / len(pages) < 0.2:
        anomalies.append({
            "id": "A_SOURCE_TEXT_LAYER_SYSTEMIC",
            "scope_type": "source",
            "target_id": source_id,
            "severity": "systemic",
            "category": "content",
            "message": "Fewer than 20 percent of PDF pages contain a usable text layer; source text is blocked pending OCR or transcription.",
        })

    packet = {
        "schema_version": 1,
        "processor": {"name": "hrw-pymupdf", "version": "m2", "render_scale": render_scale},
        "source_id": source_id,
        "source_sha256": source["sha256"],
        "pages": pages,
        "relations": relations,
        "anomalies": anomalies,
    }
    _write_json(packet_path, packet)
    _write_text(
        document_path,
        "# Page-aware document\n\n"
        "> Pages remain separate artifacts. Cross-page text is never joined without a reviewed relation.\n\n"
        + "\n".join(
            f'- [Physical page {page["physical_page"]}](markdown/page-{page["physical_page"]:04d}.md)'
            for page in pages
        )
        + "\n",
    )
    receipt = import_structure(project_root, source_id, packet_path)
    with connect(project_root) as connection:
        append_audit(connection, "pdf_ingested", "source", source_id, {
            "pages": len(pages),
            "anomalies": len(anomalies),
            "structure_path": packet_path.relative_to(project_root).as_posix(),
        })
    return {
        "source_id": source_id,
        "status": "applied" if receipt["status"] in {"applied", "already_applied"} else receipt["status"],
        "page_count": len(pages),
        "anomaly_count": len(anomalies),
        "receipt": receipt,
        "structure_path": packet_path.relative_to(project_root).as_posix(),
        "document_path": document_path.relative_to(project_root).as_posix(),
    }
