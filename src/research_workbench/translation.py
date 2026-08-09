from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from .db import connect, utc_now


Translator = Callable[[str, str], str]


def capability() -> dict[str, Any]:
    provider = os.getenv("HRW_TRANSLATION_PROVIDER", "").strip().lower()
    model = os.getenv("HRW_TRANSLATION_MODEL", "").strip()
    endpoint = os.getenv("HRW_TRANSLATION_BASE_URL", "").strip()
    missing = [name for name, value in (
        ("HRW_TRANSLATION_PROVIDER", provider), ("HRW_TRANSLATION_MODEL", model),
        ("HRW_TRANSLATION_BASE_URL", endpoint),
    ) if not value]
    if provider == "openai_compatible" and not os.getenv("HRW_TRANSLATION_API_KEY"):
        missing.append("HRW_TRANSLATION_API_KEY")
    return {"role": "translation_helper", "available": not missing and provider in {"openai_compatible", "ollama"},
            "provider": provider or "unconfigured", "model": model or "unconfigured", "missing": missing}


def _request(text: str, target_language: str) -> str:
    settings = capability()
    if not settings["available"]:
        raise ValueError("translation helper is not configured")
    provider, model = settings["provider"], settings["model"]
    base = os.environ["HRW_TRANSLATION_BASE_URL"].rstrip("/")
    prompt = f"Translate the following verified quotation into {target_language}. Preserve names, dates and uncertainty. Return translation only.\n\n{text}"
    if provider == "ollama":
        url = base if base.endswith("/api/chat") else base + "/api/chat"
        payload = {"model": model, "stream": False, "messages": [{"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json"}
    else:
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        payload = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['HRW_TRANSLATION_API_KEY']}"}
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=90) as response:
        raw = json.loads(response.read().decode())
    return (raw.get("message", {}).get("content", "") if provider == "ollama"
            else raw["choices"][0]["message"]["content"])


def translate_evidence(project_root: Path, evidence_id: str, target_language: str,
                       translator: Translator | None = None) -> dict[str, Any]:
    with connect(project_root) as connection:
        evidence = connection.execute("SELECT * FROM evidence_items WHERE evidence_id = ?", (evidence_id,)).fetchone()
    if evidence is None:
        raise KeyError(f"unknown evidence: {evidence_id}")
    target_language = target_language.strip()
    if not target_language:
        raise ValueError("target language is required")
    translated = (translator or _request)(evidence["quote"], target_language).strip()
    if not translated:
        raise ValueError("translation helper returned empty text")
    artifact_id, version_id, now = f"ART_{uuid.uuid4().hex}", f"ARV_{uuid.uuid4().hex}", utc_now()
    snapshot = capability() if translator is None else {"role": "translation_helper", "provider": "test"}
    content = f"原文：{evidence['quote']}\n\n译文（{target_language}）：{translated}\n"
    refs = [{"evidence_id": evidence_id, "page_id": evidence["page_id"],
             "source_version_id": evidence["source_version_id"]}]
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO artifacts(artifact_id, artifact_type, title, status, created_at, updated_at) VALUES (?, 'evidence_translation', ?, 'draft', ?, ?)",
            (artifact_id, f"Evidence {evidence_id} translation", now, now),
        )
        connection.execute(
            "INSERT INTO artifact_versions(version_id, artifact_id, content, source_refs_json, model_snapshot_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (version_id, artifact_id, content, json.dumps(refs, ensure_ascii=False),
             json.dumps(snapshot, ensure_ascii=False), now),
        )
    from .scholarship import artifact_detail
    return artifact_detail(project_root, artifact_id)
