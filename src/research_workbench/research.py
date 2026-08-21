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

from .db import append_audit, connect, utc_now


Fetcher = Callable[[str, dict[str, str]], dict[str, Any]]

RETRIEVAL_ROUTES = {
    "project_candidate": "拟纳入项目",
    "fulltext_queue": "待读全文",
    "metadata_only": "仅题录",
    "duplicate": "重复版本",
    "inaccessible": "无权访问",
    "excluded": "排除",
}

AUTHENTICATED_DATABASES = {
    "CNKI": "https://kns.cnki.net/kns8s/",
    "读秀": "https://www.duxiu.com/",
    "国家哲学社会科学文献中心": "https://www.ncpssd.cn/",
    "学校发现系统": "",
    "其他已登录数据库": "",
}


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
        {"provider": "authenticated_browser", "available": True, "mode": "user_visible_session",
         "databases": ["CNKI", "读秀", "学校发现系统", "其他已登录数据库"],
         "boundary": "只操作用户可见会话；验证码、授权和下载确认交还用户"},
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


def create_authenticated_search_task(project_root: Path, database: str, query: str,
                                     start_url: str = "") -> dict[str, Any]:
    database, query, start_url = database.strip(), query.strip(), start_url.strip()
    if database not in AUTHENTICATED_DATABASES:
        raise ValueError(f"unsupported authenticated database: {database}")
    if not query:
        raise ValueError("research query is required")
    start_url = start_url or AUTHENTICATED_DATABASES[database]
    if not start_url.startswith(("https://", "http://")):
        raise ValueError("authenticated database task requires an http(s) start URL")
    record_id, now = f"RET_{uuid.uuid4().hex}", utc_now()
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO retrieval_records(record_id, provider, query, filters_json, status,
               result_count, request_url, response_hash, error, created_at)
               VALUES (?, 'authenticated_browser', ?, ?, 'awaiting_user_session', 0, ?, '', NULL, ?)""",
            (record_id, query, json.dumps({"database": database}, ensure_ascii=False), start_url, now),
        )
        append_audit(connection, "authenticated_search_task_created", "retrieval_record", record_id, {
            "database": database, "query": query, "start_url": start_url,
        })
    return retrieval_record(project_root, record_id)


def add_authenticated_results(project_root: Path, record_id: str,
                              items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        raise ValueError("at least one retrieval result is required")
    with connect(project_root) as connection:
        record = connection.execute(
            "SELECT provider FROM retrieval_records WHERE record_id = ?", (record_id,)
        ).fetchone()
        if record is None or record["provider"] != "authenticated_browser":
            raise ValueError("results can only be added to an authenticated browser task")
        added = 0
        for index, raw in enumerate(items):
            title = str(raw.get("title", "")).strip()
            if not title:
                continue
            url = str(raw.get("url", "")).strip()
            external_id = str(raw.get("external_id", "")).strip() or hashlib.sha256(
                f"{title}\n{url}".encode("utf-8")
            ).hexdigest()[:24]
            cursor = connection.execute(
                """INSERT OR IGNORE INTO retrieval_results(
                   result_id, record_id, external_id, title, authors, publication_year,
                   container_title, doi, url, open_access_url, raw_json, qualification)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 'DISCOVERED')""",
                (f"RER_{uuid.uuid4().hex}", record_id, external_id, title,
                 str(raw.get("authors", "")).strip(), str(raw.get("year", "")).strip(),
                 str(raw.get("container", "")).strip(), str(raw.get("doi", "")).strip(), url,
                 json.dumps(raw, ensure_ascii=False)),
            )
            added += cursor.rowcount
        count = connection.execute(
            "SELECT COUNT(*) FROM retrieval_results WHERE record_id = ?", (record_id,)
        ).fetchone()[0]
        connection.execute(
            "UPDATE retrieval_records SET status = 'captured', result_count = ? WHERE record_id = ?",
            (count, record_id),
        )
        append_audit(connection, "authenticated_results_captured", "retrieval_record", record_id, {
            "submitted": len(items), "added": added, "result_count": count,
        })
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
            """SELECT r.*, d.route, d.reason AS route_reason, d.decided_by AS route_decided_by,
                      d.decided_at AS route_decided_at
               FROM retrieval_results r
               LEFT JOIN retrieval_result_decisions d ON d.decision_id = (
                   SELECT d2.decision_id FROM retrieval_result_decisions d2
                   WHERE d2.result_id = r.result_id
                   ORDER BY d2.decided_at DESC, d2.rowid DESC LIMIT 1
               )
               WHERE r.record_id = ? ORDER BY r.rowid""", (record_id,)
        )]
    return {**dict(row), "filters": json.loads(row["filters_json"]), "results": results}


def route_retrieval_result(project_root: Path, result_id: str, route: str,
                           reason: str, decided_by: str) -> dict[str, Any]:
    route, reason, decided_by = route.strip(), reason.strip(), decided_by.strip()
    if route not in RETRIEVAL_ROUTES:
        raise ValueError(f"unsupported retrieval route: {route}")
    if not reason or not decided_by:
        raise ValueError("routing reason and decision maker are required")
    decision_id, decided_at = f"RRD_{uuid.uuid4().hex}", utc_now()
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT record_id FROM retrieval_results WHERE result_id = ?", (result_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown retrieval result: {result_id}")
        connection.execute(
            """INSERT INTO retrieval_result_decisions(
                   decision_id, result_id, route, reason, decided_by, decided_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (decision_id, result_id, route, reason, decided_by, decided_at),
        )
        append_audit(connection, "retrieval_result_routed", "retrieval_result", result_id, {
            "decision_id": decision_id, "route": route, "reason": reason, "decided_by": decided_by,
        })
    return retrieval_record(project_root, str(row["record_id"]))


def list_retrievals(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM retrieval_records ORDER BY created_at DESC"
        )]
