from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROMPT_VERSION = "page-ocr-v1"
PAGE_OCR_PROMPT = """You transcribe historical document page images for human review.
Return JSON only with this shape:
{
  "printed_page": null,
  "blocks": [
    {"order": 1, "type": "paragraph", "text": "...", "region": null}
  ],
  "uncertain_characters": [],
  "warnings": []
}
Transcribe only visible content. Do not summarize, translate, modernize, correct, or infer missing text.
Preserve natural reading order, paragraphs, headings, notes, headers, footers and page numbers as
separate blocks where possible. Join a word split only by a printed line break. Use 〔不清〕 for an
unreadable span. For vertical Chinese, follow the page's visible column order. Regions, when supplied,
use normalized x0, y0, x1, y1 coordinates between 0 and 1."""


@dataclass(frozen=True)
class OcrSettings:
    provider: str
    model: str
    base_url: str = ""
    api_key: str = ""
    timeout_seconds: float = 90.0
    mock_text: str = ""

    @classmethod
    def from_environment(cls) -> "OcrSettings":
        return cls(
            provider=os.environ.get("HRW_OCR_PROVIDER", "disabled").strip().lower(),
            model=os.environ.get("HRW_OCR_MODEL", "").strip(),
            base_url=os.environ.get("HRW_OCR_BASE_URL", "").strip(),
            api_key=os.environ.get("HRW_OCR_API_KEY", "").strip(),
            timeout_seconds=float(os.environ.get("HRW_OCR_TIMEOUT_SECONDS", "90")),
            mock_text=os.environ.get("HRW_OCR_MOCK_TEXT", "").strip(),
        )


def capability(settings: OcrSettings | None = None) -> dict[str, Any]:
    settings = settings or OcrSettings.from_environment()
    missing: list[str] = []
    if settings.provider not in {"openai_compatible", "ollama", "mock"}:
        missing.append("HRW_OCR_PROVIDER")
    if not settings.model:
        missing.append("HRW_OCR_MODEL")
    if settings.provider in {"openai_compatible", "ollama"} and not settings.base_url:
        missing.append("HRW_OCR_BASE_URL")
    if settings.provider == "openai_compatible" and not settings.api_key:
        missing.append("HRW_OCR_API_KEY")
    return {
        "role": "vision_ocr",
        "available": not missing,
        "provider": settings.provider,
        "model": settings.model,
        "missing": missing,
    }


def request_page_ocr(
    image_path: Path,
    settings: OcrSettings | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    settings = settings or OcrSettings.from_environment()
    state = capability(settings)
    if not state["available"]:
        raise ValueError(f"OCR capability is unavailable; missing: {', '.join(state['missing'])}")
    image_base64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    if settings.provider == "openai_compatible":
        raw = _request_openai_compatible(image_base64, settings)
        content = _openai_content(raw)
    elif settings.provider == "ollama":
        raw = _request_ollama(image_base64, settings)
        content = str(raw.get("message", {}).get("content", ""))
    else:
        content = settings.mock_text or "Mock OCR proposal for human review."
        raw = {
            "id": "mock-response",
            "model": settings.model,
            "choices": [{"message": {"content": content}}],
        }
    return raw, normalize_ocr_content(content)


def normalize_ocr_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if not text:
        raise ValueError("OCR provider returned empty content")
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    warnings: list[Any] = []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {"blocks": [{"order": 1, "type": "paragraph", "text": text}]}
        warnings.append("provider_response_was_not_json")
    if not isinstance(payload, dict):
        raise ValueError("OCR response JSON must be an object")
    raw_blocks = payload.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        fallback = str(payload.get("text", "")).strip()
        if not fallback:
            raise ValueError("OCR response must contain at least one text block")
        raw_blocks = [{"order": 1, "type": "paragraph", "text": fallback}]
    blocks: list[dict[str, Any]] = []
    allowed_types = {"paragraph", "heading", "footnote", "header", "footer", "page_number"}
    for index, block in enumerate(raw_blocks, start=1):
        if not isinstance(block, dict) or not str(block.get("text", "")).strip():
            raise ValueError("every OCR block must contain non-empty text")
        block_type = str(block.get("type", "paragraph"))
        region = _normalize_region(block.get("region"))
        blocks.append(
            {
                "order": index,
                "type": block_type if block_type in allowed_types else "paragraph",
                "text": str(block["text"]).strip(),
                "region": region,
            }
        )
    if any(block["region"] is None for block in blocks):
        warnings.append("block_regions_missing")
    payload_warnings = payload.get("warnings", [])
    if isinstance(payload_warnings, list):
        warnings.extend(payload_warnings)
    printed_page = payload.get("printed_page")
    if isinstance(printed_page, bool) or isinstance(printed_page, (dict, list)):
        warnings.append("invalid_printed_page")
        printed_page = None
    return {
        "printed_page": None if printed_page is None else str(printed_page),
        "blocks": blocks,
        "uncertain_characters": payload.get("uncertain_characters", [])
        if isinstance(payload.get("uncertain_characters", []), list) else [],
        "warnings": warnings,
    }


def _normalize_region(value: Any) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not all(key in value for key in ("x0", "y0", "x1", "y1")):
        return None
    region = {key: float(value[key]) for key in ("x0", "y0", "x1", "y1")}
    if not all(0 <= coordinate <= 1 for coordinate in region.values()):
        return None
    if region["x0"] >= region["x1"] or region["y0"] >= region["y1"]:
        return None
    return region


def _request_openai_compatible(image_base64: str, settings: OcrSettings) -> dict[str, Any]:
    endpoint = settings.base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    payload = {
        "model": settings.model,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PAGE_OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
            ],
        }],
    }
    return _post_json(
        endpoint,
        payload,
        {"Authorization": f"Bearer {settings.api_key}"},
        settings.timeout_seconds,
    )


def _request_ollama(image_base64: str, settings: OcrSettings) -> dict[str, Any]:
    endpoint = settings.base_url.rstrip("/")
    if not endpoint.endswith("/api/chat"):
        endpoint += "/api/chat"
    payload = {
        "model": settings.model,
        "stream": False,
        "format": "json",
        "messages": [{"role": "user", "content": PAGE_OCR_PROMPT, "images": [image_base64]}],
        "options": {"temperature": 0},
    }
    return _post_json(endpoint, payload, {}, settings.timeout_seconds)


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"OCR provider returned HTTP {error.code}") from error
    except URLError as error:
        raise RuntimeError("OCR provider could not be reached") from error
    if not isinstance(result, dict):
        raise RuntimeError("OCR provider response was not a JSON object")
    return result


def _openai_content(raw: dict[str, Any]) -> str:
    try:
        content = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("OCR provider response did not contain message content") from error
    if not isinstance(content, str):
        raise RuntimeError("OCR provider message content was not text")
    return content
