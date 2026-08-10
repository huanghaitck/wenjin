from __future__ import annotations

import hashlib
import json
import os
import ssl
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi

from .db import connect, utc_now


Fetcher = Callable[[str, dict[str, str]], dict[str, Any]]


def _fetch(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "HistoricalResearchWorkbench/0.6", **headers})
    with urlopen(request, timeout=20, context=ssl.create_default_context(cafile=certifi.where())) as response:
        return json.loads(response.read().decode("utf-8"))


def connector_capabilities() -> list[dict[str, Any]]:
    return [
        {"provider": "crossref", "available": True, "mode": "public_api"},
        {"provider": "openalex", "available": bool(os.getenv("OPENALEX_API_KEY")),
         "mode": "public_api", "missing": [] if os.getenv("OPENALEX_API_KEY") else ["OPENALEX_API_KEY"]},
        {"provider": "zotero", "available": probe_zotero()["available"], "mode": "local_read_only"},
    ]


def probe_zotero(fetcher: Fetcher | None = None) -> dict[str, Any]:
    try:
        url = "http://127.0.0.1:23119/api/"
        if fetcher is None:
            request = Request(url, headers={"Zotero-API-Version": "3"})
            with urlopen(request, timeout=0.35) as response:
                value = json.loads(response.read().decode("utf-8"))
        else:
            value = fetcher(url, {"Zotero-API-Version": "3"})
        return {"available": True, "endpoint": "http://127.0.0.1:23119/api/", "response": value}
    except Exception:
        return {"available": False, "endpoint": "http://127.0.0.1:23119/api/"}


def search(project_root: Path, provider: str, query: str, limit: int = 10,
           fetcher: Fetcher = _fetch) -> dict[str, Any]:
    provider, query = provider.lower(), query.strip()
    if not query:
        raise ValueError("research query is required")
    limit = max(1, min(int(limit), 25))
    headers: dict[str, str] = {}
    if provider == "crossref":
        params = {"query.bibliographic": query, "rows": limit}
        if os.getenv("CROSSREF_MAILTO"):
            params["mailto"] = os.environ["CROSSREF_MAILTO"]
        request_url = "https://api.crossref.org/works?" + urlencode(params)
    elif provider == "openalex":
        key = os.getenv("OPENALEX_API_KEY")
        if not key:
            raise ValueError("OpenAlex requires OPENALEX_API_KEY; configure it in .env or the process environment")
        request_url = "https://api.openalex.org/works?" + urlencode(
            {"search": query, "per_page": limit, "api_key": key}
        )
    elif provider == "zotero":
        request_url = "http://127.0.0.1:23119/api/users/0/items?" + urlencode(
            {"q": query, "limit": limit, "format": "json"}
        )
        headers["Zotero-API-Version"] = "3"
    else:
        raise ValueError(f"unsupported research provider: {provider}")

    record_id = f"RET_{uuid.uuid4().hex}"
    safe_url = request_url.replace(os.getenv("OPENALEX_API_KEY", "__NO_KEY__"), "***")
    status, error, raw, results = "completed", "", {}, []
    try:
        raw = fetcher(request_url, headers)
        results = _normalize(provider, raw)[:limit]
        if not results:
            status = "zero_results"
    except HTTPError as exc:
        status, error = ("rate_limited" if exc.code == 429 else "failed"), f"HTTP {exc.code}"
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        status, error = "failed", str(exc)
    response_hash = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest() if raw else ""
    now = utc_now()
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO retrieval_records(record_id, provider, query, filters_json, status,
               result_count, request_url, response_hash, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record_id, provider, query, json.dumps({"limit": limit}), status, len(results), safe_url,
             response_hash, error or None, now),
        )
        for item in results:
            result_id = f"RER_{uuid.uuid4().hex}"
            connection.execute(
                """INSERT INTO retrieval_results(result_id, record_id, external_id, title, authors,
                   publication_year, container_title, doi, url, open_access_url, raw_json, qualification)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DISCOVERED')""",
                (result_id, record_id, item["external_id"], item["title"], item["authors"], item["year"],
                 item["container"], item["doi"], item["url"], item["open_access_url"],
                 json.dumps(item["raw"], ensure_ascii=False)),
            )
    return retrieval_record(project_root, record_id)


def _normalize(provider: str, raw: Any) -> list[dict[str, Any]]:
    if provider == "crossref":
        items = raw.get("message", {}).get("items", [])
        return [{
            "external_id": item.get("DOI") or item.get("URL") or str(index),
            "title": " ".join(item.get("title", [])),
            "authors": "; ".join(" ".join(filter(None, [a.get("family"), a.get("given")])) for a in item.get("author", [])),
            "year": str(next(iter(item.get("published", {}).get("date-parts", [[""]])), [""])[0]),
            "container": " ".join(item.get("container-title", [])), "doi": item.get("DOI", ""),
            "url": item.get("URL", ""), "open_access_url": item.get("link", [{}])[0].get("URL", "") if item.get("link") else "",
            "raw": item,
        } for index, item in enumerate(items)]
    if provider == "openalex":
        return [{
            "external_id": item.get("id", str(index)), "title": item.get("display_name", ""),
            "authors": "; ".join(a.get("author", {}).get("display_name", "") for a in item.get("authorships", [])),
            "year": str(item.get("publication_year") or ""),
            "container": item.get("primary_location", {}).get("source", {}).get("display_name", "") if item.get("primary_location") else "",
            "doi": item.get("doi", ""), "url": item.get("id", ""),
            "open_access_url": item.get("open_access", {}).get("oa_url") or "", "raw": item,
        } for index, item in enumerate(raw.get("results", []))]
    items = raw if isinstance(raw, list) else []
    return [{
        "external_id": item.get("key", str(index)), "title": item.get("data", {}).get("title", ""),
        "authors": "; ".join(c.get("lastName", "") for c in item.get("data", {}).get("creators", [])),
        "year": item.get("data", {}).get("date", ""), "container": item.get("data", {}).get("publicationTitle", ""),
        "doi": item.get("data", {}).get("DOI", ""), "url": item.get("data", {}).get("url", ""),
        "open_access_url": "", "raw": item,
    } for index, item in enumerate(items)]


def retrieval_record(project_root: Path, record_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute("SELECT * FROM retrieval_records WHERE record_id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown retrieval record: {record_id}")
        results = [dict(item) for item in connection.execute(
            "SELECT * FROM retrieval_results WHERE record_id = ? ORDER BY rowid", (record_id,)
        )]
    return {**dict(row), "filters": json.loads(row["filters_json"]), "results": results}


def list_retrievals(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM retrieval_records ORDER BY created_at DESC"
        )]
