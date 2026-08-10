from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from .db import append_audit, connect, utc_now
from .scholarship import freeze_detail


Writer = Callable[[str], str]
OPERATIONS = {"polish", "section_draft"}

BUILTIN_JOURNAL_TEMPLATES = (
    {
        "template_id": "builtin-history-research",
        "revision_id": "JTR_history_research_public_reference",
        "name": "《历史研究》",
        "citation_style": "页下注；①②③；每页单独编号；序号置于相关标点之后",
        "section_rules": ["中文题目", "摘要", "关键词", "正文", "页下注释"],
        "version_label": "公开规范参考版（2026-08-10 核验）",
        "effective_date": "公开版本日期未能从期刊官网确认",
        "source_url": "https://www.ynu.edu.cn/__local/3/C4/E8/48C0EFB258EA4A95C7F446EC740_06110F24_37381.pdf?e=.pdf",
        "verification_status": "REFERENCE_NEEDS_PRE_SUBMISSION_RECHECK",
        "requirements": {
            "note_placement": "footnote", "number_restart": "each_page", "marker": "circled_arabic",
            "anchor_position": "after_punctuation", "warning": "公开镜像未证明仍是期刊当前最新版，投稿前必须复核",
        },
    },
    {
        "template_id": "builtin-chinese-social-sciences-2026",
        "revision_id": "JTR_chinese_social_sciences_2026",
        "name": "《中国社会科学》",
        "citation_style": "页下注；①②；每页单独编号；2026 年修订引文注释规定",
        "section_rules": ["中英文题目", "中英文摘要（各 300 字以内）", "中英文关键词（3—5 个）", "正文", "页下注释"],
        "version_label": "2026 年修订版",
        "effective_date": "2026",
        "source_url": "https://sscp.cssn.cn/tsgpt/202510/W020260609553247288896.pdf",
        "verification_status": "OFFICIAL_CURRENT_CHECKED_2026_08_10",
        "requirements": {
            "max_words": 20000, "paper": "A4", "body_font": "宋体", "body_size_pt": 12,
            "body_grid": "36字×35行", "note_placement": "footnote", "number_restart": "each_page",
            "marker": "circled_arabic", "note_font": "仿宋", "note_size_pt": 10.5,
            "anchor_position": "after_punctuation", "warning": "投稿前仍须核对期刊最新公告",
            "submission_guide_url": "https://sscp.cssn.cn/tzgg/202502/t20250227_5849425.shtml",
            "citation_rules_url": "https://sscp.cssn.cn/tsgpt/202510/W020260609553247288896.pdf",
        },
    },
)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _sections(markdown: str) -> list[tuple[str, str]]:
    parts: list[tuple[str, list[str]]] = []
    heading, body = "正文", []
    for line in markdown.replace("\r\n", "\n").splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            if body or parts:
                parts.append((heading, body))
            heading, body = match.group(1), []
        else:
            body.append(line)
    parts.append((heading, body))
    return [(title, "\n".join(lines).strip()) for title, lines in parts if title or any(line.strip() for line in lines)]


def import_manuscript(project_root: Path, title: str, markdown: str) -> dict[str, Any]:
    title, markdown = title.strip(), markdown.strip()
    if not title or not markdown:
        raise ValueError("manuscript title and Markdown content are required")
    manuscript_id, now = _id("MAN"), utc_now()
    parsed = _sections(markdown)
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO manuscripts(manuscript_id, title, source_format, status, created_at, updated_at) VALUES (?, ?, 'markdown', 'active', ?, ?)",
            (manuscript_id, title, now, now),
        )
        for order, (heading, content) in enumerate(parsed, start=1):
            section_id, version_id = _id("SEC"), _id("SEV")
            connection.execute(
                "INSERT INTO manuscript_sections(section_id, manuscript_id, section_order, heading, current_version_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (section_id, manuscript_id, order, heading, version_id, now),
            )
            connection.execute(
                """INSERT INTO section_versions(version_id, section_id, operation, content,
                   evidence_refs_json, model_snapshot_json, status, created_at, approved_at)
                   VALUES (?, ?, 'import', ?, '[]', '{"provider":"human_import"}', 'approved', ?, ?)""",
                (version_id, section_id, content, now, now),
            )
        append_audit(connection, "manuscript_imported", "manuscript", manuscript_id,
                     {"section_count": len(parsed)})
    return manuscript_detail(project_root, manuscript_id)


def _markers(text: str) -> list[str]:
    patterns = [r"“[^”]+”", r"\[\^[^\]]+\]", r"\b\d+(?:[.,:]\d+)*\b", r"(?:SRC|EVI|CLM|FRZ)_[A-Za-z0-9_]+"]
    found: list[str] = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text))
    return list(dict.fromkeys(found))


def _validate_markers(content: str, markers: list[str]) -> dict[str, Any]:
    missing = [marker for marker in markers if marker not in content]
    return {"valid": not missing, "missing_markers": missing}


def _model_capability() -> dict[str, Any]:
    provider = os.getenv("HRW_AGENT_PROVIDER", "").strip().lower()
    model = os.getenv("HRW_AGENT_MODEL", "").strip()
    endpoint = os.getenv("HRW_AGENT_BASE_URL", "").strip()
    available = provider in {"openai_compatible", "ollama"} and bool(model and endpoint)
    if provider == "openai_compatible" and not os.getenv("HRW_AGENT_API_KEY"):
        available = False
    return {"provider": provider or "deterministic_demo", "model": model or "rule_based", "available": available}


def _model_write(prompt: str) -> str:
    profile = _model_capability()
    if not profile["available"]:
        raise ValueError("a real writing model is not configured")
    provider, model = profile["provider"], profile["model"]
    base = os.environ["HRW_AGENT_BASE_URL"].rstrip("/")
    if provider == "ollama":
        url = base if base.endswith("/api/chat") else base + "/api/chat"
        payload = {"model": model, "stream": False, "messages": [{"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json"}
    else:
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        payload = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['HRW_AGENT_API_KEY']}"}
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=120) as response:
        raw = json.loads(response.read().decode())
    return (raw.get("message", {}).get("content", "") if provider == "ollama"
            else raw["choices"][0]["message"]["content"])


def create_writing_proposal(project_root: Path, section_id: str, operation: str,
                            instruction: str, freeze_id: str = "", writer: Writer | None = None) -> dict[str, Any]:
    operation, instruction = operation.strip(), instruction.strip()
    if operation not in OPERATIONS:
        raise ValueError(f"unsupported writing operation: {operation}")
    with connect(project_root) as connection:
        row = connection.execute(
            """SELECT s.*, v.content FROM manuscript_sections s
               JOIN section_versions v ON v.version_id = s.current_version_id WHERE s.section_id = ?""",
            (section_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"unknown manuscript section: {section_id}")
    base_content, evidence_refs = row["content"], []
    markers = _markers(base_content) if operation == "polish" else []
    if operation == "section_draft":
        freeze = freeze_detail(project_root, freeze_id)
        if freeze["status"] != "approved":
            raise ValueError("section drafting requires an approved evidence freeze")
        evidence_refs = [
            {"claim_id": claim["claim_id"], "evidence_id": evidence["evidence_id"],
             "page_id": evidence["page_id"], "source_version_id": evidence["source_version_id"]}
            for claim in freeze["payload"]["claims"] for evidence in claim["evidence"]
        ]
        evidence_text = "\n".join(
            f"主张：{claim['text']}\n" + "\n".join(
                f"- {e['relation']}｜物理页 {e['physical_page']}｜{e['quote']}" for e in claim["evidence"]
            ) for claim in freeze["payload"]["claims"]
        )
        prompt = f"依据以下已冻结证据撰写章节《{row['heading']}》。不得新增事实；保留证据边界。要求：{instruction}\n\n{evidence_text}"
        fallback = "\n\n".join(
            f"{claim['text']}\n\n" + "".join(
                f"材料记载：“{e['quote']}”（物理页 {e['physical_page']}）。" for e in claim["evidence"]
            ) for claim in freeze["payload"]["claims"]
        )
    else:
        prompt = (
            "润色以下中文历史学论文段落。不得新增、删除或强化事实，不得改变引文、数字、脚注标记和来源标识。"
            f"只返回修改后正文。具体要求：{instruction}\n\n{base_content}"
        )
        fallback = re.sub(r"[ \t]+", " ", base_content).replace(" ,", "，").replace(" .", "。")
    proposed = (writer(prompt) if writer else (_model_write(prompt) if _model_capability()["available"] else fallback)).strip()
    validation = _validate_markers(proposed, markers)
    proposal_id, now = _id("WPR"), utc_now()
    snapshot = {**_model_capability(), "mode": "injected" if writer else "runtime", "freeze_id": freeze_id}
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO writing_proposals(proposal_id, section_id, base_version_id, operation,
               instruction, proposed_content, evidence_refs_json, model_snapshot_json,
               protected_markers_json, validation_json, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (proposal_id, section_id, row["current_version_id"], operation, instruction, proposed,
             _json(evidence_refs), _json(snapshot), _json(markers), _json(validation), now),
        )
    return proposal_detail(project_root, proposal_id)


def decide_writing_proposal(project_root: Path, proposal_id: str, approved: bool,
                            reviewer: str, edited_content: str | None = None) -> dict[str, Any]:
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer is required")
    proposal = proposal_detail(project_root, proposal_id)
    if proposal["status"] != "pending":
        raise ValueError(f"writing proposal is already {proposal['status']}")
    final_content = (edited_content if edited_content is not None else proposal["proposed_content"]).strip()
    validation = _validate_markers(final_content, proposal["protected_markers"])
    if approved and not validation["valid"]:
        raise ValueError("writing proposal removed protected markers: " + ", ".join(validation["missing_markers"]))
    now = utc_now()
    with connect(project_root) as connection:
        if approved:
            version_id = _id("SEV")
            connection.execute(
                """INSERT INTO section_versions(version_id, section_id, base_version_id, operation,
                   content, evidence_refs_json, model_snapshot_json, status, created_at, approved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)""",
                (version_id, proposal["section_id"], proposal["base_version_id"], proposal["operation"],
                 final_content, _json(proposal["evidence_refs"]), _json(proposal["model_snapshot"]), now, now),
            )
            connection.execute(
                "UPDATE manuscript_sections SET current_version_id = ? WHERE section_id = ?",
                (version_id, proposal["section_id"]),
            )
            connection.execute(
                """UPDATE manuscripts SET updated_at = ? WHERE manuscript_id = (
                       SELECT manuscript_id FROM manuscript_sections WHERE section_id = ?
                   )""",
                (now, proposal["section_id"]),
            )
            status = "approved"
        else:
            version_id, status = "", "rejected"
        connection.execute(
            "UPDATE writing_proposals SET status = ?, validation_json = ?, decided_at = ?, reviewer = ? WHERE proposal_id = ?",
            (status, _json(validation), now, reviewer, proposal_id),
        )
        append_audit(connection, "writing_proposal_decided", "writing_proposal", proposal_id,
                     {"approved": approved, "version_id": version_id})
    return {"proposal_id": proposal_id, "status": status, "version_id": version_id,
            "validation": validation}


def proposal_detail(project_root: Path, proposal_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute("SELECT * FROM writing_proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise KeyError(f"unknown writing proposal: {proposal_id}")
    result = dict(row)
    for key, target in (("evidence_refs_json", "evidence_refs"), ("model_snapshot_json", "model_snapshot"),
                        ("protected_markers_json", "protected_markers"), ("validation_json", "validation")):
        result[target] = json.loads(result[key])
    return result


def manuscript_detail(project_root: Path, manuscript_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        manuscript = connection.execute("SELECT * FROM manuscripts WHERE manuscript_id = ?", (manuscript_id,)).fetchone()
        if manuscript is None:
            raise KeyError(f"unknown manuscript: {manuscript_id}")
        sections = [dict(row) for row in connection.execute(
            """SELECT s.*, v.content, v.operation, v.created_at AS version_created_at
               FROM manuscript_sections s JOIN section_versions v ON v.version_id = s.current_version_id
               WHERE s.manuscript_id = ? ORDER BY s.section_order""", (manuscript_id,)
        )]
        for section in sections:
            section["versions"] = [dict(row) for row in connection.execute(
                "SELECT * FROM section_versions WHERE section_id = ? ORDER BY created_at DESC", (section["section_id"],)
            )]
            section["proposals"] = [proposal_detail(project_root, row[0]) for row in connection.execute(
                "SELECT proposal_id FROM writing_proposals WHERE section_id = ? ORDER BY created_at DESC",
                (section["section_id"],),
            )]
    return {**dict(manuscript), "sections": sections}


def list_manuscripts(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        ids = [row[0] for row in connection.execute("SELECT manuscript_id FROM manuscripts ORDER BY updated_at DESC")]
    return [manuscript_detail(project_root, manuscript_id) for manuscript_id in ids]


def create_reading_job(project_root: Path, title: str, question: str, mode: str,
                       source_ids: list[str], stop_condition: str) -> dict[str, Any]:
    if mode not in {"metadata", "targeted", "full"}:
        raise ValueError("reading mode must be metadata, targeted or full")
    if not title.strip() or not question.strip() or not source_ids or not stop_condition.strip():
        raise ValueError("reading job requires title, question, sources and stop condition")
    job_id, now = _id("RDJ"), utc_now()
    notes = []
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO reading_jobs(job_id, title, question, mode, source_ids_json, stop_condition, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)",
            (job_id, title.strip(), question.strip(), mode, _json(source_ids), stop_condition.strip(), now),
        )
        block_limit = 5 if mode == "metadata" else (30 if mode == "targeted" else 120)
        for source_id in source_ids:
            rows = connection.execute(
                """SELECT p.page_id, p.physical_page, b.block_id,
                          COALESCE(b.human_text, b.machine_text) AS text
                   FROM blocks b JOIN pages p ON p.page_id = b.page_id
                   WHERE p.source_id = ? AND p.use_state = 'research_usable'
                     AND b.use_state = 'research_usable'
                   ORDER BY p.physical_page, b.block_order LIMIT ?""", (source_id, block_limit),
            ).fetchall()
            if not rows:
                continue
            refs = [{"page_id": row["page_id"], "physical_page": row["physical_page"],
                     "block_id": row["block_id"]} for row in rows]
            content = "\n\n".join(f"[物理页 {row['physical_page']}] {row['text']}" for row in rows)
            note_id = _id("RDN")
            connection.execute(
                "INSERT INTO reading_notes(note_id, job_id, source_id, page_refs_json, content, qualification, created_at) VALUES (?, ?, ?, ?, ?, 'READING_NOTE_NOT_EVIDENCE', ?)",
                (note_id, job_id, source_id, _json(refs), content, utc_now()),
            )
            notes.append({"note_id": note_id, "source_id": source_id, "page_refs": refs,
                          "content": content, "qualification": "READING_NOTE_NOT_EVIDENCE"})
        connection.execute("UPDATE reading_jobs SET status = 'completed', completed_at = ? WHERE job_id = ?", (utc_now(), job_id))
    return {"job_id": job_id, "title": title, "question": question, "mode": mode,
            "stop_condition": stop_condition, "status": "completed", "notes": notes}


def list_reading_jobs(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        jobs = [dict(row) for row in connection.execute("SELECT * FROM reading_jobs ORDER BY created_at DESC")]
        for job in jobs:
            job["source_ids"] = json.loads(job["source_ids_json"])
            job["notes"] = [dict(row) for row in connection.execute(
                "SELECT * FROM reading_notes WHERE job_id = ? ORDER BY created_at", (job["job_id"],)
            )]
            for note in job["notes"]:
                note["page_refs"] = json.loads(note["page_refs_json"])
    return jobs


def create_historiography_entry(project_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    required = ("work_title", "position", "contribution", "limitation", "relevance")
    if any(not str(payload.get(key, "")).strip() for key in required) or not payload.get("source_refs"):
        raise ValueError("historiography entry requires all fields and source references")
    entry_id, now = _id("HIS"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO historiography_entries(entry_id, work_title, position, contribution,
               limitation, relevance, source_refs_json, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?)""",
            (entry_id, *(str(payload[key]).strip() for key in required), _json(payload["source_refs"]), now),
        )
    return {"entry_id": entry_id, **{key: str(payload[key]).strip() for key in required},
            "source_refs": payload["source_refs"], "status": "candidate", "created_at": now}


def list_historiography(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        rows = [dict(row) for row in connection.execute("SELECT * FROM historiography_entries ORDER BY created_at DESC")]
    for row in rows:
        row["source_refs"] = json.loads(row["source_refs_json"])
    return rows


def ensure_journal_templates(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        now = utc_now()
        for item in BUILTIN_JOURNAL_TEMPLATES:
            connection.execute(
                """INSERT OR IGNORE INTO journal_templates(template_id, name, citation_style,
                   section_rules_json, format_rules_json, origin, created_at)
                   VALUES (?, ?, ?, ?, ?, 'builtin', ?)""",
                (item["template_id"], item["name"], item["citation_style"], _json(item["section_rules"]),
                 _json(item["requirements"]), now),
            )
            connection.execute(
                """INSERT OR IGNORE INTO journal_template_revisions(template_revision_id, template_id,
                   version_label, effective_date, source_url, verified_at, requirements_json,
                   verification_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item["revision_id"], item["template_id"], item["version_label"], item["effective_date"],
                 item["source_url"], "2026-08-10", _json(item["requirements"]),
                 item["verification_status"], now),
            )
        rows = [dict(row) for row in connection.execute(
            """SELECT t.*, r.template_revision_id, r.version_label, r.effective_date, r.source_url,
                      r.verified_at, r.requirements_json, r.verification_status
               FROM journal_templates t
               LEFT JOIN journal_template_revisions r ON r.template_revision_id = (
                   SELECT r2.template_revision_id FROM journal_template_revisions r2
                   WHERE r2.template_id = t.template_id ORDER BY r2.created_at DESC LIMIT 1
               )
               WHERE t.origin = 'user' OR r.template_revision_id IS NOT NULL
               ORDER BY t.origin, t.name"""
        )]
    for row in rows:
        row["section_rules"] = json.loads(row["section_rules_json"])
        row["format_rules"] = json.loads(row["format_rules_json"])
        row["requirements"] = json.loads(row["requirements_json"]) if row.get("requirements_json") else row["format_rules"]
    return rows


def create_journal_template(project_root: Path, name: str, citation_style: str,
                            section_rules: list[str]) -> dict[str, Any]:
    if not name.strip() or not citation_style.strip() or not section_rules:
        raise ValueError("journal template requires name, citation style and section rules")
    template_id, now = _id("JTP"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO journal_templates(template_id, name, citation_style, section_rules_json, format_rules_json, origin, created_at) VALUES (?, ?, ?, ?, '{}', 'user', ?)",
            (template_id, name.strip(), citation_style.strip(), _json(section_rules), now),
        )
    return next(item for item in ensure_journal_templates(project_root) if item["template_id"] == template_id)


def export_manuscript(project_root: Path, manuscript_id: str, template_id: str) -> dict[str, Any]:
    manuscript = manuscript_detail(project_root, manuscript_id)
    template = next((item for item in ensure_journal_templates(project_root) if item["template_id"] == template_id), None)
    if template is None:
        raise KeyError(f"unknown journal template: {template_id}")
    content = [f"# {manuscript['title']}", "", f"> 模板：{template['name']}",
               f"> 注释规则：{template['citation_style']}", ""]
    for section in manuscript["sections"]:
        content.extend([f"## {section['heading']}", "", section["content"], ""])
    path = project_root / "exports" / f"{manuscript_id}-{template_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text("\n".join(content).rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)
    return {"manuscript_id": manuscript_id, "template_id": template_id,
            "project_path": path.relative_to(project_root).as_posix()}


def authoring_state(project_root: Path) -> dict[str, Any]:
    return {"manuscripts": list_manuscripts(project_root), "reading_jobs": list_reading_jobs(project_root),
            "historiography": list_historiography(project_root),
            "journal_templates": ensure_journal_templates(project_root), "writing_model": _model_capability()}
