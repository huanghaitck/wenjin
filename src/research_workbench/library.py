from __future__ import annotations

import hashlib
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

import fitz

from .db import connect, project_id, utc_now
from .library_store import connect_library, initialize_library, resolve_library_root
from .skill_registry import discover_skills, get_skill


SUPPORTED_SUFFIXES = {".pdf", ".md", ".txt", ".docx"}
CANDIDATE_SUFFIXES = SUPPORTED_SUFFIXES | {".doc", ".docx", ".epub", ".caj", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}
HISTORY_TERMS = (
    "历史", "史料", "档案", "地方志", "编年", "朝代", "帝国", "革命", "战争", "考察",
    "history", "historical", "archive", "chronicle", "century", "empire", "revolution", "war",
)
LIBRARY_SHELVES = {
    "primary_sources": "原始史料", "academic_articles": "学术论文",
    "monographs": "学术专著", "personal_manuscripts": "个人论文与稿件",
    "reference_works": "工具书与目录", "unclassified": "待分类",
}
SUGGESTED_SHELVES = {
    "archival_source": "primary_sources",
    "article": "academic_articles",
    "thesis": "academic_articles",
    "monograph": "monographs",
    "personal_manuscript": "personal_manuscripts",
    "reference_work": "reference_works",
}
SCAN_PAGE_SIZE = 50
SCAN_MAX_PAGE_SIZE = 50
SCAN_WRITE_BATCH_SIZE = 50


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _graph_node(connection: Any, node_type: str, label: str, normalized: str | None = None) -> str:
    normalized_label = (normalized or label).strip().casefold()
    node_id = "KGN_" + hashlib.sha256(f"{node_type}\0{normalized_label}".encode("utf-8")).hexdigest()[:24]
    connection.execute(
        """INSERT INTO knowledge_nodes(node_id, node_type, label, normalized_label, origin, created_at)
           VALUES (?, ?, ?, ?, 'bibliographic_metadata', ?)
           ON CONFLICT(node_type, normalized_label) DO UPDATE SET label = excluded.label""",
        (node_id, node_type, label.strip(), normalized_label, utc_now()),
    )
    return node_id


def _sync_work_graph(connection: Any, work_id: str) -> None:
    work = connection.execute("SELECT * FROM works WHERE work_id = ?", (work_id,)).fetchone()
    if work is None:
        return
    edition = connection.execute(
        "SELECT publisher, publication_year FROM editions WHERE work_id = ? ORDER BY created_at LIMIT 1", (work_id,)
    ).fetchone()
    tags = [row[0] for row in connection.execute(
        "SELECT t.name FROM tags t JOIN work_tags wt ON wt.tag_id = t.tag_id WHERE wt.work_id = ?", (work_id,)
    )]
    source = _graph_node(connection, "work", work["canonical_title"], work_id)
    connection.execute("DELETE FROM knowledge_edges WHERE work_id = ? AND origin = 'bibliographic_metadata'", (work_id,))
    relations: list[tuple[str, str, str]] = []
    if work["author"].strip():
        relations.append((source, "authored_by", _graph_node(connection, "person", work["author"])))
    if edition and edition["publication_year"].strip():
        relations.append((source, "published_in_year", _graph_node(connection, "year", edition["publication_year"])))
    if edition and edition["publisher"].strip():
        relations.append((source, "published_by", _graph_node(connection, "organization", edition["publisher"])))
    relations.append((source, "material_type", _graph_node(connection, "material_type", work["material_type"])))
    for tag in tags:
        relation = "shelved_as" if tag.startswith("shelf:") else "tagged_as"
        relations.append((source, relation, _graph_node(connection, "tag", tag)))
    for source_id, relation, target_id in relations:
        edge_id = "KGE_" + hashlib.sha256(f"{source_id}\0{relation}\0{target_id}\0{work_id}".encode("utf-8")).hexdigest()[:24]
        connection.execute(
            """INSERT OR IGNORE INTO knowledge_edges(
                   edge_id, source_node_id, relation, target_node_id, work_id, origin, created_at
               ) VALUES (?, ?, ?, ?, ?, 'bibliographic_metadata', ?)""",
            (edge_id, source_id, relation, target_id, work_id, utc_now()),
        )


def _clean_title(value: str, fallback: str) -> str:
    title = " ".join(value.replace("\x00", " ").split()).strip(" -_")
    return title[:300] or fallback


def _year(text: str) -> str:
    match = re.search(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)", text)
    return match.group(1) if match else ""


def _language(text: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    return "und"


def _material_type(title: str, sample: str, path: str = "") -> str:
    combined = f"{path}\n{title}\n{sample[:5000]}".lower()
    identity = f"{path}\n{title}".lower()
    if any(term in identity for term in (
        "个人论文与稿件", "我的文章", "我的论文", "手稿", "草稿", "返修稿", "投稿稿", "未刊稿",
    )):
        return "personal_manuscript"
    if any(term in combined for term in (
        "档案", "奏折", "公文", "日记", "书信", "地方志", "史料汇编", "archive", "diary",
    )):
        return "archival_source"
    if any(term in combined for term in (
        "工具书", "目录", "索引", "年鉴", "辞典", "百科", "手册", "bibliography", "catalog", "encyclopedia", "handbook",
    )):
        return "reference_work"
    if any(term in combined for term in ("博士学位", "硕士学位", "学位论文", "dissertation", "thesis")):
        return "thesis"
    if any(term in combined for term in ("journal", "doi", "期刊", "学报", "研究论文", "学术论文")):
        return "article"
    if any(term in combined for term in ("isbn", "cip", "出版社", "学术专著", "monograph")):
        return "monograph"
    return "book_or_document"


def _pdf_bibliography(
    sample: str,
    fallback_title: str,
    author: str,
    publisher: str,
    year: str,
) -> tuple[str, str, str, str]:
    title = fallback_title
    named = re.search(r"书\s*名\s*[:：]?\s*([^\n]{2,60})", sample[:8000])
    if named:
        title = named.group(1).strip()
    if not author:
        authored = re.search(r"^([^\n]{2,40}(?:著|撰|编|校点))\s*$", sample[:4000], re.MULTILINE)
        author = authored.group(1).strip() if authored else ""
    if not publisher:
        published = re.search(r"^([^\n]{2,60}出版社[^\n]{0,20})$", sample[:8000], re.MULTILINE)
        publisher = published.group(1).strip() if published else ""
    if not year:
        dated = re.search(r"(?:出版|版次|CIP)[^\n]{0,80}(1[0-9]{3}|20[0-9]{2})", sample[:10000])
        year = dated.group(1) if dated else ""
    return title, author, publisher, year


def _triage_state(sample: str, supported: bool, text_layer: str, page_count: int | None) -> tuple[str, str]:
    if not supported:
        return "unsupported", "当前版本暂不解析此格式；文件仍保留在盘点清单中。CAJ 应保留原件并另生成带转换回执的 PDF/逐页 Markdown。"
    if page_count and text_layer == "absent":
        return "needs_visual_triage", "前十页没有可用文本层，需要原页或视觉模型进一步判断。"
    normalized = sample.lower()
    score = sum(1 for term in HISTORY_TERMS if term in normalized)
    if score >= 2:
        return "likely_historical", f"前段文本命中 {score} 个历史材料线索，仅作为整理建议。"
    if len(sample.strip()) < 100:
        return "uncertain", "可读取文本过少，不能可靠判断材料类型。"
    if score == 0 and len(sample) >= 500:
        return "not_obviously_historical", "前段文本未出现明显历史材料线索，不代表不可用于研究。"
    return "uncertain", "有少量线索但不足以稳定判断，建议人工确认。"


def _inspect_file(path: Path) -> dict[str, Any]:
    stat = path.stat()
    suffix = path.suffix.lower()
    supported = suffix in SUPPORTED_SUFFIXES
    title = path.stem
    author = ""
    publisher = ""
    year = ""
    page_count: int | None = None
    inspected_pages = 0
    text_layer = "not_applicable"
    sample = ""

    if suffix == ".pdf":
        with fitz.open(path) as document:
            page_count = document.page_count
            metadata = document.metadata or {}
            title = metadata.get("title") or title
            author = metadata.get("author") or ""
            publisher = metadata.get("producer") or ""
            year = _year(" ".join(str(value) for value in metadata.values()))
            chunks: list[str] = []
            for index in range(min(10, page_count)):
                chunks.append(document.load_page(index).get_text("text"))
                inspected_pages += 1
            sample = "\n".join(chunks).strip()[:50000]
            text_layer = "present" if sample else "absent"
            title, author, publisher, year = _pdf_bibliography(
                sample, title, author, publisher, year
            )
    elif suffix in {".md", ".txt"}:
        sample = path.read_text(encoding="utf-8", errors="replace")[:50000]
        first_line = next((line.strip(" #\t") for line in sample.splitlines() if line.strip()), "")
        title = first_line or title
        inspected_pages = 1
        text_layer = "present" if sample.strip() else "absent"
    elif suffix == ".docx":
        from docx import Document

        document = Document(path)
        chunks = [" ".join(paragraph.text.split()) for paragraph in document.paragraphs if paragraph.text.strip()]
        sample = "\n".join(chunks)[:50000]
        first_line = next((line for line in chunks if line), "")
        title = first_line or title
        inspected_pages = 1
        text_layer = "present" if sample.strip() else "absent"

    title = _clean_title(title, path.stem)
    year = year or _year(f"{path.stem} {title}")
    state, reason = _triage_state(sample, supported, text_layer, page_count)
    return {
        "path": str(path.resolve()),
        "format": suffix.lstrip(".") or "unknown",
        "byte_count": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
        "sha256": _file_hash(path),
        "suggested_title": title,
        "suggested_author": _clean_title(author, "") if author else "",
        "suggested_year": year,
        "suggested_publisher": _clean_title(publisher, "") if publisher else "",
        "suggested_language": _language(f"{title}\n{sample[:4000]}"),
        "suggested_material_type": _material_type(title, sample, str(path)),
        "page_count": page_count,
        "text_layer": text_layer,
        "triage_state": state,
        "triage_reason": reason,
        "inspected_pages": inspected_pages,
        "sample_text": sample,
    }


def library_root_for(project_root: Path, library_root: Path | None = None) -> Path:
    root = resolve_library_root(project_root, library_root)
    initialize_library(root)
    return root


def library_status(project_root: Path, library_root: Path | None = None) -> dict[str, Any]:
    root = library_root_for(project_root, library_root)
    with connect_library(root) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("works", "editions", "library_files", "file_versions", "scan_sessions")
        }
    return {"library_root": str(root), "counts": counts, "skills": discover_skills()}


def _candidate_action(connection: Any, item: dict[str, Any]) -> dict[str, Any]:
    existing_file = connection.execute(
        "SELECT file_id, work_id, edition_id FROM library_files WHERE path = ?",
        (item["path"],),
    ).fetchone()
    if existing_file is not None:
        current = connection.execute(
            "SELECT sha256 FROM file_versions WHERE file_id = ? AND is_current = 1",
            (existing_file["file_id"],),
        ).fetchone()
        action = "unchanged" if current and current["sha256"] == item["sha256"] else "new_version"
        return {"proposed_action": action, **dict(existing_file)}
    duplicate = connection.execute(
        """SELECT f.file_id, f.work_id, f.edition_id
           FROM file_versions v JOIN library_files f ON f.file_id = v.file_id
           WHERE v.sha256 = ? LIMIT 1""",
        (item["sha256"],),
    ).fetchone()
    if duplicate is not None:
        return {"proposed_action": "exact_duplicate", **dict(duplicate)}
    return {
        "proposed_action": "register_new",
        "file_id": None,
        "work_id": None,
        "edition_id": None,
    }


def create_scan_session(
    project_root: Path,
    source_root: Path,
    library_root: Path | None = None,
    skill_name: str = "historical-material-intake",
) -> dict[str, Any]:
    source_root = source_root.expanduser().resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"scan directory does not exist: {source_root}")
    skill = get_skill(skill_name)
    if "library_intake" not in skill["compatible_actions"]:
        raise ValueError(f"skill is not compatible with library intake: {skill_name}")
    root = library_root_for(project_root, library_root)
    session_id = f"SCN_{uuid.uuid4().hex}"
    now = utc_now()
    with connect_library(root) as connection:
        connection.execute(
            """INSERT INTO scan_sessions(
                   session_id, root_path, skill_name, skill_sha256, status, created_at
               ) VALUES (?, ?, ?, ?, 'scanning', ?)""",
            (session_id, str(source_root), skill["name"], skill["sha256"], now),
        )
    return scan_session(project_root, session_id, root)


def run_scan_session(
    project_root: Path,
    session_id: str,
    library_root: Path | None = None,
) -> None:
    root = library_root_for(project_root, library_root)
    with connect_library(root) as connection:
        session = connection.execute(
            "SELECT * FROM scan_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if session is None:
            raise KeyError(f"unknown scan session: {session_id}")
        source_root = Path(session["root_path"])
    processed = 0
    pending: list[tuple[str, dict[str, Any], str, str, dict[str, Any]]] = []

    def flush_pending() -> None:
        nonlocal processed
        if not pending:
            return
        with connect_library(root) as connection:
            for candidate_id, item, status, error, fallback_identity in pending:
                identity = (
                    _candidate_action(connection, item) if status != "error" else fallback_identity
                )
                connection.execute(
                    """INSERT INTO scan_candidates(
                           candidate_id, session_id, path, format, byte_count, modified_ns, sha256,
                           suggested_title, suggested_author, suggested_year, suggested_publisher,
                           suggested_language, suggested_material_type, page_count, text_layer,
                           triage_state, triage_reason, inspected_pages, sample_text, proposed_action,
                           existing_work_id, existing_edition_id, existing_file_id, status, error
                       ) VALUES (
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                       )""",
                    (
                        candidate_id, session_id, item["path"], item["format"], item["byte_count"],
                        item["modified_ns"], item["sha256"], item["suggested_title"],
                        item["suggested_author"], item["suggested_year"], item["suggested_publisher"],
                        item["suggested_language"], item["suggested_material_type"], item["page_count"],
                        item["text_layer"], item["triage_state"], item["triage_reason"],
                        item["inspected_pages"], item["sample_text"], identity["proposed_action"],
                        identity.get("work_id"), identity.get("edition_id"), identity.get("file_id"),
                        status, error,
                    ),
                )
            processed += len(pending)
            connection.execute(
                "UPDATE scan_sessions SET processed_count = ? WHERE session_id = ?",
                (processed, session_id),
            )
        pending.clear()

    try:
        for directory, _, filenames in os.walk(source_root, followlinks=False):
            for filename in sorted(filenames):
                path = Path(directory) / filename
                if path.suffix.lower() not in CANDIDATE_SUFFIXES:
                    continue
                candidate_id = f"CND_{uuid.uuid4().hex}"
                try:
                    item = _inspect_file(path)
                    identity = {"proposed_action": "", "work_id": None, "edition_id": None, "file_id": None}
                    status = "preview"
                    error = ""
                except Exception as exc:
                    stat = path.stat()
                    item = {
                        "path": str(path.resolve()), "format": path.suffix.lower().lstrip("."),
                        "byte_count": stat.st_size, "modified_ns": stat.st_mtime_ns, "sha256": "",
                        "suggested_title": path.stem, "suggested_author": "", "suggested_year": "",
                        "suggested_publisher": "", "suggested_language": "und",
                        "suggested_material_type": "unknown", "page_count": None,
                        "text_layer": "unknown", "triage_state": "error",
                        "triage_reason": "文件无法完成只读盘点。", "inspected_pages": 0, "sample_text": "",
                    }
                    identity = {"proposed_action": "error", "work_id": None, "edition_id": None, "file_id": None}
                    status = "error"
                    error = str(exc)
                pending.append((candidate_id, item, status, error, identity))
                if len(pending) >= SCAN_WRITE_BATCH_SIZE:
                    flush_pending()
        flush_pending()
        with connect_library(root) as connection:
            connection.execute(
                """UPDATE scan_sessions
                   SET status = 'preview_ready', processed_count = ?, completed_at = ?
                   WHERE session_id = ?""",
                (processed, utc_now(), session_id),
            )
    except Exception as exc:
        pending.clear()
        with connect_library(root) as connection:
            connection.execute(
                """UPDATE scan_sessions
                   SET status = 'failed', error = ?, processed_count = ?, completed_at = ?
                   WHERE session_id = ?""",
                (str(exc), processed, utc_now(), session_id),
            )


def start_scan_session(
    project_root: Path,
    source_root: Path,
    library_root: Path | None = None,
    skill_name: str = "historical-material-intake",
    compatibility_wait: float = 0.0,
) -> dict[str, Any]:
    session = create_scan_session(project_root, source_root, library_root, skill_name)
    root = library_root_for(project_root, library_root)
    worker = threading.Thread(
        target=run_scan_session,
        args=(project_root, session["session_id"], root),
        name=f"library-scan-{session['session_id']}",
        daemon=True,
    )
    worker.start()
    # Optional only for callers that explicitly want a brief compatibility wait; the
    # HTTP endpoint uses the non-blocking default.
    if compatibility_wait > 0:
        worker.join(timeout=compatibility_wait)
        return scan_session(project_root, session["session_id"], root)
    # The session row was durably committed before the worker started. Returning
    # that receipt avoids contending with the worker's first SQLite transaction
    # and keeps the HTTP start endpoint genuinely non-blocking.
    return session


def scan_directory(
    project_root: Path,
    source_root: Path,
    library_root: Path | None = None,
    skill_name: str = "historical-material-intake",
) -> dict[str, Any]:
    """Synchronous compatibility helper used by the CLI and existing small-directory callers."""
    session = create_scan_session(project_root, source_root, library_root, skill_name)
    run_scan_session(project_root, session["session_id"], library_root)
    return scan_session(project_root, session["session_id"], library_root)


def scan_session(
    project_root: Path,
    session_id: str = "",
    library_root: Path | None = None,
    page: int = 1,
    page_size: int = SCAN_PAGE_SIZE,
) -> dict[str, Any]:
    root = library_root_for(project_root, library_root)
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), SCAN_MAX_PAGE_SIZE))
    with connect_library(root) as connection:
        if session_id:
            session = connection.execute(
                "SELECT * FROM scan_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        else:
            session = connection.execute(
                "SELECT * FROM scan_sessions ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if session is None:
            raise KeyError(f"unknown scan session: {session_id}")
        total_count = connection.execute(
            "SELECT COUNT(*) FROM scan_candidates WHERE session_id = ?", (session["session_id"],)
        ).fetchone()[0]
        eligible_remaining_count = connection.execute(
            """SELECT COUNT(*) FROM scan_candidates
               WHERE session_id = ? AND status = 'preview'
                 AND triage_state NOT IN ('unsupported', 'error')
                 AND proposed_action != 'unchanged'""",
            (session["session_id"],),
        ).fetchone()[0]
        offset = (page - 1) * page_size
        candidates = connection.execute(
            """SELECT candidate_id, session_id, path, format, byte_count, modified_ns, sha256,
                      suggested_title, suggested_author, suggested_year, suggested_publisher,
                      suggested_language, suggested_material_type, page_count, text_layer,
                      triage_state, triage_reason, inspected_pages, proposed_action,
                      existing_work_id, existing_edition_id, existing_file_id, status, error
               FROM scan_candidates WHERE session_id = ? ORDER BY path LIMIT ? OFFSET ?""",
            (session["session_id"], page_size, offset),
        ).fetchall()
    candidate_items = []
    for row in candidates:
        item = dict(row)
        item["suggested_shelf"] = SUGGESTED_SHELVES.get(item["suggested_material_type"], "unclassified")
        item["suggested_shelf_label"] = LIBRARY_SHELVES[item["suggested_shelf"]]
        candidate_items.append(item)
    return {
        **dict(session),
        "total_count": total_count,
        "eligible_remaining_count": eligible_remaining_count,
        "page": page,
        "page_size": page_size,
        "page_count": (total_count + page_size - 1) // page_size,
        "has_more": offset + len(candidates) < total_count,
        "candidates": candidate_items,
    }


def _add_tag(connection: Any, work_id: str, name: str, origin: str) -> None:
    name = name.strip()
    if not name:
        return
    connection.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (name,))
    tag_id = connection.execute("SELECT tag_id FROM tags WHERE name = ?", (name,)).fetchone()[0]
    connection.execute(
        "INSERT OR IGNORE INTO work_tags(work_id, tag_id, origin) VALUES (?, ?, ?)",
        (work_id, tag_id, origin),
    )


def _refresh_search(connection: Any, work_id: str) -> None:
    work = connection.execute("SELECT * FROM works WHERE work_id = ?", (work_id,)).fetchone()
    publishers = connection.execute(
        "SELECT GROUP_CONCAT(publisher, ' ') FROM editions WHERE work_id = ?", (work_id,)
    ).fetchone()[0] or ""
    tags = connection.execute(
        """SELECT GROUP_CONCAT(t.name, ' ') FROM tags t
           JOIN work_tags wt ON wt.tag_id = t.tag_id WHERE wt.work_id = ?""", (work_id,)
    ).fetchone()[0] or ""
    samples = connection.execute(
        """SELECT GROUP_CONCAT(substr(v.sample_text, 1, 5000), ' ') FROM file_versions v
           JOIN library_files f ON f.file_id = v.file_id WHERE f.work_id = ? AND v.is_current = 1""",
        (work_id,),
    ).fetchone()[0] or ""
    connection.execute("DELETE FROM work_search WHERE work_id = ?", (work_id,))
    connection.execute(
        "INSERT INTO work_search(work_id, title, author, publisher, tags, sample_text) VALUES (?, ?, ?, ?, ?, ?)",
        (work_id, work["canonical_title"], work["author"], publishers, tags, samples),
    )


def _insert_version(connection: Any, candidate: Any, file_id: str, skill: Any) -> str:
    version_id = f"FV_{uuid.uuid4().hex}"
    connection.execute("UPDATE file_versions SET is_current = 0 WHERE file_id = ?", (file_id,))
    connection.execute(
        """INSERT INTO file_versions(
               version_id, file_id, sha256, byte_count, modified_ns, format, page_count,
               text_layer, triage_state, triage_reason, inspected_pages, sample_text,
               qualification, skill_name, skill_sha256, discovered_at, is_current
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FILE_VERIFIED', ?, ?, ?, 1)""",
        (
            version_id, file_id, candidate["sha256"], candidate["byte_count"], candidate["modified_ns"],
            candidate["format"], candidate["page_count"], candidate["text_layer"],
            candidate["triage_state"], candidate["triage_reason"], candidate["inspected_pages"],
            candidate["sample_text"], skill["name"], skill["sha256"], utc_now(),
        ),
    )
    return version_id


def approve_candidates(
    project_root: Path,
    session_id: str,
    candidate_ids: list[str] | None = None,
    library_root: Path | None = None,
) -> dict[str, Any]:
    root = library_root_for(project_root, library_root)
    with connect_library(root) as connection:
        session = connection.execute(
            "SELECT * FROM scan_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if session is None:
            raise KeyError(f"unknown scan session: {session_id}")
        if session["status"] not in {"preview_ready", "partially_approved", "approved"}:
            raise ValueError("scan candidates may only be approved after the scan preview is ready")
        skill = {"name": session["skill_name"], "sha256": session["skill_sha256"]}
        parameters: list[Any] = [session_id]
        clause = ""
        if candidate_ids:
            clause = f" AND candidate_id IN ({','.join('?' for _ in candidate_ids)})"
            parameters.extend(candidate_ids)
        candidates = connection.execute(
            f"SELECT * FROM scan_candidates WHERE session_id = ?{clause} ORDER BY path", parameters
        ).fetchall()
        approved: list[dict[str, str]] = []
        for candidate in candidates:
            if candidate["status"] != "preview" or candidate["triage_state"] in {"error", "unsupported"}:
                continue
            action = candidate["proposed_action"]
            if action == "unchanged":
                connection.execute(
                    "UPDATE library_files SET last_seen_at = ? WHERE file_id = ?",
                    (utc_now(), candidate["existing_file_id"]),
                )
                work_id = candidate["existing_work_id"]
                version_id = ""
            elif action == "new_version":
                file_id = candidate["existing_file_id"]
                work_id = candidate["existing_work_id"]
                version_id = _insert_version(connection, candidate, file_id, skill)
                connection.execute("UPDATE library_files SET last_seen_at = ? WHERE file_id = ?", (utc_now(), file_id))
            else:
                now = utc_now()
                if action == "exact_duplicate":
                    work_id = candidate["existing_work_id"]
                    edition_id = candidate["existing_edition_id"]
                else:
                    work_id = f"WRK_{uuid.uuid4().hex}"
                    edition_id = f"ED_{uuid.uuid4().hex}"
                    connection.execute(
                        """INSERT INTO works(
                               work_id, canonical_title, author, language, material_type, created_at, updated_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            work_id, candidate["suggested_title"], candidate["suggested_author"],
                            candidate["suggested_language"], candidate["suggested_material_type"], now, now,
                        ),
                    )
                    connection.execute(
                        """INSERT INTO editions(
                               edition_id, work_id, edition_label, publisher, publication_year, isbn, created_at
                           ) VALUES (?, ?, '待核版本', ?, ?, '', ?)""",
                        (edition_id, work_id, candidate["suggested_publisher"], candidate["suggested_year"], now),
                    )
                file_id = f"FIL_{uuid.uuid4().hex}"
                connection.execute(
                    """INSERT INTO library_files(
                           file_id, work_id, edition_id, path, first_seen_at, last_seen_at
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (file_id, work_id, edition_id, candidate["path"], now, now),
                )
                version_id = _insert_version(connection, candidate, file_id, skill)
                if action == "register_new":
                    _add_tag(connection, work_id, f"material:{candidate['suggested_material_type']}", "system")
                    _add_tag(connection, work_id, f"triage:{candidate['triage_state']}", "system")
                    shelf = SUGGESTED_SHELVES.get(candidate["suggested_material_type"], "unclassified")
                    _add_tag(connection, work_id, f"shelf:{shelf}", "system")
            connection.execute(
                "UPDATE scan_candidates SET status = 'approved' WHERE candidate_id = ?",
                (candidate["candidate_id"],),
            )
            _refresh_search(connection, work_id)
            _sync_work_graph(connection, work_id)
            approved.append({"candidate_id": candidate["candidate_id"], "work_id": work_id, "version_id": version_id})
        remaining = connection.execute(
            "SELECT COUNT(*) FROM scan_candidates WHERE session_id = ? AND status = 'preview'", (session_id,)
        ).fetchone()[0]
        connection.execute(
            "UPDATE scan_sessions SET status = ?, approved_at = ? WHERE session_id = ?",
            ("partially_approved" if remaining else "approved", utc_now(), session_id),
        )
    return {"session_id": session_id, "approved": approved, "remaining": remaining}


def _work_summary(connection: Any, work_id: str) -> dict[str, Any]:
    work = connection.execute("SELECT * FROM works WHERE work_id = ?", (work_id,)).fetchone()
    if work is None:
        raise KeyError(f"unknown work: {work_id}")
    tags = connection.execute(
        """SELECT t.name, wt.origin FROM tags t JOIN work_tags wt ON wt.tag_id = t.tag_id
           WHERE wt.work_id = ? ORDER BY t.name""", (work_id,)
    ).fetchall()
    counts = connection.execute(
        """SELECT COUNT(DISTINCT f.file_id), COUNT(v.version_id) FROM library_files f
           LEFT JOIN file_versions v ON v.file_id = f.file_id WHERE f.work_id = ?""", (work_id,)
    ).fetchone()
    tag_items = [dict(row) for row in tags]
    shelf_tag = next((item["name"] for item in tag_items if item["name"].startswith("shelf:")), "")
    shelf = shelf_tag.removeprefix("shelf:") if shelf_tag else "unclassified"
    return {**dict(work), "tags": tag_items, "shelf": shelf,
            "shelf_label": LIBRARY_SHELVES.get(shelf, shelf),
            "file_count": counts[0], "version_count": counts[1]}


def move_work_to_shelf(project_root: Path, work_id: str, shelf: str,
                       library_root: Path | None = None) -> dict[str, Any]:
    if shelf not in LIBRARY_SHELVES:
        raise ValueError(f"unknown library shelf: {shelf}")
    root = library_root_for(project_root, library_root)
    with connect_library(root) as connection:
        if connection.execute("SELECT 1 FROM works WHERE work_id = ?", (work_id,)).fetchone() is None:
            raise KeyError(f"unknown work: {work_id}")
        connection.execute(
            """DELETE FROM work_tags WHERE work_id = ? AND tag_id IN
               (SELECT tag_id FROM tags WHERE name LIKE 'shelf:%')""", (work_id,),
        )
        _add_tag(connection, work_id, f"shelf:{shelf}", "user")
        _refresh_search(connection, work_id)
        _sync_work_graph(connection, work_id)
    return work_detail(project_root, work_id, root)


def search_library(
    project_root: Path,
    query: str = "",
    tags: list[str] | None = None,
    library_root: Path | None = None,
) -> list[dict[str, Any]]:
    root = library_root_for(project_root, library_root)
    with connect_library(root) as connection:
        if query.strip():
            phrase = '"' + query.strip().replace('"', '""') + '"'
            rows = connection.execute(
                "SELECT work_id FROM work_search WHERE work_search MATCH ? ORDER BY rank", (phrase,)
            ).fetchall()
            work_ids = [row["work_id"] for row in rows]
            contains = f"%{query.strip()}%"
            fallback = connection.execute(
                """SELECT DISTINCT w.work_id FROM works w
                   LEFT JOIN editions e ON e.work_id = w.work_id
                   LEFT JOIN library_files f ON f.work_id = w.work_id
                   LEFT JOIN file_versions v ON v.file_id = f.file_id AND v.is_current = 1
                   LEFT JOIN work_tags wt ON wt.work_id = w.work_id
                   LEFT JOIN tags t ON t.tag_id = wt.tag_id
                   WHERE w.canonical_title LIKE ? OR w.author LIKE ? OR e.publisher LIKE ?
                      OR t.name LIKE ? OR v.sample_text LIKE ?""",
                (contains, contains, contains, contains, contains),
            ).fetchall()
            work_ids.extend(row["work_id"] for row in fallback if row["work_id"] not in work_ids)
        else:
            work_ids = [row["work_id"] for row in connection.execute("SELECT work_id FROM works ORDER BY updated_at DESC")]
        required_tags = set(tags or [])
        results = [_work_summary(connection, work_id) for work_id in work_ids]
    if required_tags:
        results = [item for item in results if required_tags <= {tag["name"] for tag in item["tags"]}]
    return results


def work_detail(project_root: Path, work_id: str, library_root: Path | None = None) -> dict[str, Any]:
    root = library_root_for(project_root, library_root)
    with connect_library(root) as connection:
        result = _work_summary(connection, work_id)
        editions = connection.execute(
            "SELECT * FROM editions WHERE work_id = ? ORDER BY created_at", (work_id,)
        ).fetchall()
        files = connection.execute(
            "SELECT * FROM library_files WHERE work_id = ? ORDER BY path", (work_id,)
        ).fetchall()
        file_items = []
        for file in files:
            path = Path(file["path"])
            current_hash = _file_hash(path) if path.is_file() else ""
            versions = connection.execute(
                "SELECT * FROM file_versions WHERE file_id = ? ORDER BY discovered_at DESC", (file["file_id"],)
            ).fetchall()
            registered_current = next((row for row in versions if row["is_current"]), None)
            file_items.append({
                **dict(file),
                "exists_now": path.is_file(),
                "file_state": (
                    "matches_registered_version"
                    if registered_current and registered_current["sha256"] == current_hash
                    else ("changed_since_last_scan" if path.is_file() else "missing")
                ),
                "versions": [
                    {**dict(row), "bytes_available": bool(row["sha256"] == current_hash)}
                    for row in versions
                ],
            })
        links = connection.execute(
            "SELECT * FROM library_project_links WHERE work_id = ? ORDER BY linked_at", (work_id,)
        ).fetchall()
    return {**result, "editions": [dict(row) for row in editions], "files": file_items, "project_links": [dict(row) for row in links]}


def update_work(
    project_root: Path,
    work_id: str,
    fields: dict[str, str],
    tags: list[str],
    library_root: Path | None = None,
) -> dict[str, Any]:
    root = library_root_for(project_root, library_root)
    work_fields = ("canonical_title", "author", "language", "material_type")
    edition_fields = ("edition_label", "publisher", "publication_year", "isbn")
    updates = {key: str(fields[key]).strip() for key in work_fields if key in fields}
    edition_updates = {key: str(fields[key]).strip() for key in edition_fields if key in fields}
    if "canonical_title" in updates and not updates["canonical_title"]:
        raise ValueError("canonical_title cannot be empty")
    with connect_library(root) as connection:
        if connection.execute("SELECT 1 FROM works WHERE work_id = ?", (work_id,)).fetchone() is None:
            raise KeyError(f"unknown work: {work_id}")
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            connection.execute(
                f"UPDATE works SET {assignments}, updated_at = ? WHERE work_id = ?",
                [*updates.values(), utc_now(), work_id],
            )
        if edition_updates:
            edition_id = str(fields.get("edition_id", ""))
            if not edition_id:
                edition = connection.execute(
                    "SELECT edition_id FROM editions WHERE work_id = ? ORDER BY created_at LIMIT 1", (work_id,)
                ).fetchone()
                edition_id = edition["edition_id"]
            assignments = ", ".join(f"{key} = ?" for key in edition_updates)
            connection.execute(
                f"UPDATE editions SET {assignments} WHERE edition_id = ? AND work_id = ?",
                [*edition_updates.values(), edition_id, work_id],
            )
        connection.execute(
            """DELETE FROM work_tags WHERE work_id = ? AND origin = 'user'
               AND tag_id NOT IN (SELECT tag_id FROM tags WHERE name LIKE 'shelf:%')""", (work_id,)
        )
        for tag in tags:
            _add_tag(connection, work_id, tag, "user")
        _refresh_search(connection, work_id)
        _sync_work_graph(connection, work_id)
    return work_detail(project_root, work_id, root)


def library_graph(project_root: Path, query: str = "", limit: int = 200,
                  library_root: Path | None = None) -> dict[str, Any]:
    root = library_root_for(project_root, library_root)
    limit = max(1, min(int(limit), 500))
    with connect_library(root) as connection:
        missing_work_ids = [
            row["work_id"]
            for row in connection.execute(
                """SELECT w.work_id FROM works w
                   LEFT JOIN knowledge_nodes n
                     ON n.node_type = 'work' AND n.normalized_label = lower(w.work_id)
                   WHERE n.node_id IS NULL"""
            ).fetchall()
        ]
        for work_id in missing_work_ids:
            _sync_work_graph(connection, work_id)
        if query.strip():
            phrase = '"' + query.strip().replace('"', '""') + '"'
            work_ids = [row["work_id"] for row in connection.execute(
                "SELECT work_id FROM work_search WHERE work_search MATCH ? LIMIT ?", (phrase, limit)
            ).fetchall()]
            contains = f"%{query.strip()}%"
            fallback = connection.execute(
                """SELECT DISTINCT w.work_id FROM works w
                   LEFT JOIN editions e ON e.work_id = w.work_id
                   LEFT JOIN library_files f ON f.work_id = w.work_id
                   LEFT JOIN file_versions v ON v.file_id = f.file_id AND v.is_current = 1
                   LEFT JOIN work_tags wt ON wt.work_id = w.work_id
                   LEFT JOIN tags t ON t.tag_id = wt.tag_id
                   WHERE w.canonical_title LIKE ? OR w.author LIKE ? OR e.publisher LIKE ?
                      OR t.name LIKE ? OR v.sample_text LIKE ? LIMIT ?""",
                (contains, contains, contains, contains, contains, limit),
            ).fetchall()
            work_ids.extend(row["work_id"] for row in fallback if row["work_id"] not in work_ids)
            work_ids = work_ids[:limit]
        else:
            work_ids = [row["work_id"] for row in connection.execute(
                "SELECT work_id FROM works ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()]
        if not work_ids:
            return {
                "nodes": [], "edges": [], "work_cards": [], "node_count": 0, "edge_count": 0,
                "backfilled_work_count": len(missing_work_ids), "query": query.strip(),
            }
        normalized_ids = [work_id.casefold() for work_id in work_ids]
        placeholders = ",".join("?" for _ in normalized_ids)
        if query.strip():
            order = {work_id.casefold(): index for index, work_id in enumerate(work_ids)}
        else:
            order = {work_id.casefold(): index for index, work_id in enumerate(work_ids)}
        nodes = [dict(row) for row in connection.execute(
            f"""SELECT node_id, node_type, label, normalized_label, origin FROM knowledge_nodes
                WHERE node_type = 'work' AND normalized_label IN ({placeholders})""",
            tuple(normalized_ids),
        )]
        nodes.sort(key=lambda item: order.get(item["normalized_label"], limit))
        node_ids = {row["node_id"] for row in nodes}
        placeholders = ",".join("?" for _ in node_ids)
        edges = [dict(row) for row in connection.execute(
            f"""SELECT edge_id, source_node_id, relation, target_node_id, work_id, origin
                FROM knowledge_edges WHERE source_node_id IN ({placeholders})
                   OR target_node_id IN ({placeholders}) ORDER BY relation""",
            (*node_ids, *node_ids),
        )]
        connected_ids = node_ids | {row["source_node_id"] for row in edges} | {row["target_node_id"] for row in edges}
        placeholders = ",".join("?" for _ in connected_ids)
        nodes = [dict(row) for row in connection.execute(
            f"SELECT node_id, node_type, label, normalized_label, origin FROM knowledge_nodes WHERE node_id IN ({placeholders}) ORDER BY node_type, label",
            tuple(connected_ids),
        )]
        work_lookup = {work_id.casefold(): work_id for work_id in work_ids}
        for node in nodes:
            node["work_id"] = work_lookup.get(node["normalized_label"], "") if node["node_type"] == "work" else ""
            node.pop("normalized_label", None)
        work_cards = []
        for work_id in work_ids:
            work = _work_summary(connection, work_id)
            edition = connection.execute(
                """SELECT edition_label, publisher, publication_year FROM editions
                   WHERE work_id = ? ORDER BY created_at LIMIT 1""", (work_id,),
            ).fetchone()
            current = connection.execute(
                """SELECT v.sample_text, v.inspected_pages, v.page_count, v.format, v.text_layer,
                          v.triage_state, v.qualification, f.file_id, f.path
                   FROM file_versions v JOIN library_files f ON f.file_id = v.file_id
                   WHERE f.work_id = ? AND v.is_current = 1 ORDER BY v.discovered_at DESC LIMIT 1""",
                (work_id,),
            ).fetchone()
            project_link_count = connection.execute(
                "SELECT COUNT(*) FROM library_project_links WHERE work_id = ?", (work_id,)
            ).fetchone()[0]
            excerpt = " ".join(str(current["sample_text"] if current else "").split())[:900]
            work_cards.append({
                "work_id": work_id, "title": work["canonical_title"], "author": work["author"],
                "material_type": work["material_type"], "shelf": work["shelf"],
                "shelf_label": work["shelf_label"], "edition": dict(edition) if edition else {},
                "content_excerpt": excerpt, "preview_pages": int(current["inspected_pages"] or 0) if current else 0,
                "page_count": current["page_count"] if current else None,
                "format": current["format"] if current else "", "text_layer": current["text_layer"] if current else "",
                "triage_state": current["triage_state"] if current else "",
                "qualification": current["qualification"] if current else "",
                "current_file_id": current["file_id"] if current else "",
                "file_available": bool(current and Path(current["path"]).is_file()),
                "project_link_count": project_link_count,
            })
    project_sources: dict[str, dict[str, Any]] = {}
    if work_ids:
        placeholders = ",".join("?" for _ in work_ids)
        with connect(project_root) as connection:
            for row in connection.execute(
                f"""SELECT l.library_work_id, s.source_id, s.title, s.processing_state, s.use_state
                    FROM source_library_links l JOIN sources s ON s.source_id = l.source_id
                    WHERE l.library_work_id IN ({placeholders})""",
                tuple(work_ids),
            ).fetchall():
                project_sources[row["library_work_id"]] = dict(row)
    for card in work_cards:
        card["project_source"] = project_sources.get(card["work_id"])
    return {
        "nodes": nodes,
        "edges": edges,
        "work_cards": work_cards,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "backfilled_work_count": len(missing_work_ids),
        "query": query.strip(),
        "preview_boundary": "bounded_intake_sample_not_evidence",
    }


def library_file_path(project_root: Path, file_id: str, library_root: Path | None = None) -> Path:
    root = library_root_for(project_root, library_root)
    with connect_library(root) as connection:
        row = connection.execute("SELECT path FROM library_files WHERE file_id = ?", (file_id,)).fetchone()
    if row is None:
        raise KeyError(f"unknown library file: {file_id}")
    path = Path(row["path"])
    if not path.is_file():
        raise FileNotFoundError(f"library file is no longer available: {path}")
    return path


def link_work_to_project(
    project_root: Path,
    work_id: str,
    library_root: Path | None = None,
) -> dict[str, Any]:
    root = library_root_for(project_root, library_root)
    with connect(project_root) as project_connection:
        current_project_id = project_id(project_connection)
    with connect_library(root) as connection:
        if connection.execute("SELECT 1 FROM works WHERE work_id = ?", (work_id,)).fetchone() is None:
            raise KeyError(f"unknown work: {work_id}")
        connection.execute(
            """INSERT OR IGNORE INTO library_project_links(work_id, project_id, project_root, linked_at)
               VALUES (?, ?, ?, ?)""",
            (work_id, current_project_id, str(project_root.resolve()), utc_now()),
        )
    return work_detail(project_root, work_id, root)
