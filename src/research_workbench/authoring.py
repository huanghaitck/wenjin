from __future__ import annotations

import json
import hashlib
import os
import re
import ssl
import statistics
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

import certifi

from .db import append_audit, connect, utc_now
from .research_design import current_shared_design
from .readiness import formal_research_readiness
from .scholarship import freeze_detail, research_state
from .skill_registry import get_skill


Writer = Callable[[str], str]
OPERATIONS = {"polish", "historical_humanize", "section_draft", "metadata_draft"}
HISTORICAL_QUALIFIERS = (
    "可能", "尚不足以", "不能据此", "只能说明", "未见", "尚无", "仅限于",
    "最有把握", "再进一步", "有些", "在此个案中",
)
REVIEW_ROLES = {
    "argument_reviewer": "检查问题意识、比较结构、章节任务、因果强度和竞争解释；不要替作者重写正文。",
    "source_critic": "检查每项事实是否由已登记证据支持、是否把同一见证的译本当作独立证据，并标出过度解释。",
    "citation_editor": "检查引文锚点、注释缺口、来源资格和所选期刊模板的硬性要求；不替不存在的书目信息补值。",
    "adversarial_reviewer": "独立挑战前三份评审的共同盲点，优先寻找反证、替代解释、证据不独立和无法投稿的阻断项。",
}

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
        "template_id": "builtin-tangdu-current",
        "revision_id": "JTR_tangdu_published_notice_2026",
        "name": "《唐都学刊》（最新版）",
        "citation_style": (
            "参考文献置于文后并按正文首次出现顺序连续编号；正文以上标[序号]具体页码标识，"
            "同一文献复引沿用同一序号。说明性、解释性文字另用①②③当页脚注"
        ),
        "section_rules": [
            "中文题名（一般不超过20字）", "作者与单位", "中文摘要（约300字）",
            "关键词（3—8个）", "正文", "参考文献",
            "英文题名/作者/单位/摘要/关键词", "作者简介/项目来源/联系方式",
        ],
        "version_label": "最新刊发投稿须知（GB/T 7714—2025）＋2026年第2期历史论文刊例",
        "effective_date": "2026",
        "source_url": "https://xbbjb.xawl.edu.cn/info/1353/5409.htm",
        "verification_status": "USER_SUPPLIED_PUBLISHED_NOTICE_AND_SAMPLE_CHECKED_2026_08_12",
        "requirements": {
            "citation_system": "sequential_reference", "reference_placement": "end",
            "reference_marker": "square_brackets_with_original_page", "reference_marker_position": "superscript",
            "same_source_reuses_number": True, "note_role": "explanatory_only",
            "note_placement": "footnote", "number_restart": "each_page", "marker": "circled_arabic",
            "anchor_position": "after_punctuation", "paper": "A4", "body_font": "宋体", "body_size_pt": 10.5,
            "academic_paper_standard": "GB/T 7713.2-2022",
            "bibliographic_standard": "GB/T 7714-2025",
            "compliance_scope": "落实期刊明确要求及已核刊例所需子集，不声称覆盖国家标准全部条款",
            "minimum_length": "约10000字，欢迎10000字以上",
            "heading_levels": ["一、", "（一）"], "tables_supported": True,
            "published_sample_url": "https://m.fx361.com/news/2024/0815/25735683.html",
            "superseded_web_notice": "官网2023-12-27页面仍写GB/T 7714-2015；最新刊发须知已改为GB/T 7714-2025",
            "warning": "一手史料、直接研究、背景与学术史材料均按实际引用进入文后表；禁止只列三组核心材料",
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


def _historical_markers(text: str) -> list[str]:
    found = _markers(text)
    for pattern in (r"《[^》]+》", r"https?://\S+", r"\b10\.\d{4,9}/\S+", r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-.'’ ]{2,}"):
        found.extend(value.strip() for value in re.findall(pattern, text) if value.strip())
    found.extend(value for value in HISTORICAL_QUALIFIERS if value in text)
    return list(dict.fromkeys(found))


def _style_features(text: str) -> dict[str, Any]:
    paragraphs = [value.strip() for value in re.split(r"\n\s*\n", text) if value.strip()]
    sentences = [value.strip() for value in re.split(r"(?<=[。！？；])", text) if value.strip()]
    paragraph_lengths = [len(value) for value in paragraphs] or [0]
    sentence_lengths = [len(value) for value in sentences] or [0]
    factual_openings = sum(
        bool(re.search(r"(?:\d{3,4}年|材料|日记|书信|档案|记载|据|在[^，。]{0,18}(?:年|月|日|地|县|府))", value[:48]))
        for value in paragraphs
    )
    return {
        "sample_scope": "HIGH_LEVEL_ONLY",
        "character_count": len(text),
        "paragraph_count": len(paragraphs),
        "median_paragraph_chars": int(statistics.median(paragraph_lengths)),
        "median_sentence_chars": int(statistics.median(sentence_lengths)),
        "factual_opening_ratio": round(factual_openings / max(1, len(paragraphs)), 2),
        "direct_quote_count": len(re.findall(r"“[^”]+”", text)),
        "observed_qualifiers": [value for value in HISTORICAL_QUALIFIERS if value in text],
        "rules": ["材料先于概念", "叙事与分析交替", "限定紧贴推论", "不模仿可识别个人声腔"],
    }


def _manuscript_style_sample(project_root: Path, manuscript_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        rows = connection.execute(
            """SELECT s.current_version_id, v.content
               FROM manuscript_sections s JOIN section_versions v ON v.version_id = s.current_version_id
               WHERE s.manuscript_id = ? ORDER BY s.section_order""", (manuscript_id,),
        ).fetchall()
    if not rows:
        raise KeyError(f"unknown manuscript: {manuscript_id}")
    content = "\n\n".join(row["content"].strip() for row in rows if row["content"].strip())
    if len(content) < 800:
        raise ValueError("style sample is too short; use a complete approved manuscript with at least 800 characters")
    return {
        "manuscript_id": manuscript_id,
        "content": content,
        "source_version_ids": [row["current_version_id"] for row in rows],
        "sample_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "features": _style_features(content),
    }


def _aggregate_style_features(samples: list[dict[str, Any]]) -> dict[str, Any]:
    features = [sample["features"] for sample in samples]
    qualifiers = set(features[0]["observed_qualifiers"]) if features else set()
    for item in features[1:]:
        qualifiers &= set(item["observed_qualifiers"])
    return {
        "sample_scope": "HIGH_LEVEL_ONLY",
        "sample_count": len(samples),
        "total_characters": sum(sample["character_count"] for sample in samples),
        "median_paragraph_chars": int(statistics.median(item["median_paragraph_chars"] for item in features)),
        "median_sentence_chars": int(statistics.median(item["median_sentence_chars"] for item in features)),
        "factual_opening_ratio": round(statistics.mean(item["factual_opening_ratio"] for item in features), 2),
        "recurring_qualifiers": sorted(qualifiers),
        "rules": ["材料先于概念", "叙事与分析交替", "限定紧贴推论", "不模仿可识别个人声腔"],
    }


def create_style_profile(project_root: Path, manuscript_id: str, name: str,
                         owner_label: str = "", scope: str = "historical_articles") -> dict[str, Any]:
    name, owner_label, scope = name.strip(), owner_label.strip(), scope.strip()
    if not name:
        raise ValueError("style profile name is required")
    sample = _manuscript_style_sample(project_root, manuscript_id)
    with connect(project_root) as connection:
        profile_id, sample_id, now = _id("STY"), _id("STS"), utc_now()
        first_section = connection.execute(
            "SELECT section_id FROM manuscript_sections WHERE manuscript_id = ? ORDER BY section_order LIMIT 1",
            (manuscript_id,),
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO style_profiles(profile_id, name, owner_label, scope, manuscript_id, section_id,
               source_version_id, sample_sha256, features_json, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OBSERVED_ONCE', ?)""",
            (profile_id, name, owner_label or name, scope or "historical_articles", manuscript_id,
             first_section, sample["source_version_ids"][0], sample["sample_sha256"],
             _json(sample["features"]), now),
        )
        connection.execute(
            """INSERT INTO style_profile_samples(sample_id, profile_id, manuscript_id,
               source_version_ids_json, sample_sha256, character_count, features_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (sample_id, profile_id, manuscript_id, _json(sample["source_version_ids"]),
             sample["sample_sha256"], len(sample["content"]), _json(sample["features"]), now),
        )
        append_audit(connection, "style_profile_created", "style_profile", profile_id,
                     {"manuscript_id": manuscript_id, "sample_id": sample_id})
    return style_profile_detail(project_root, profile_id)


def add_style_profile_sample(project_root: Path, profile_id: str, manuscript_id: str) -> dict[str, Any]:
    profile = style_profile_detail(project_root, profile_id)
    if profile["status"] == "REJECTED":
        raise ValueError("cannot add samples to a rejected style profile")
    sample, sample_id, now = _manuscript_style_sample(project_root, manuscript_id), _id("STS"), utc_now()
    if any(item["sample_sha256"] == sample["sample_sha256"] for item in profile["samples"]):
        raise ValueError("this manuscript version is already part of the style profile")
    samples = profile["samples"] + [{
        "sample_id": sample_id, "manuscript_id": manuscript_id,
        "source_version_ids": sample["source_version_ids"], "sample_sha256": sample["sample_sha256"],
        "character_count": len(sample["content"]), "features": sample["features"], "created_at": now,
    }]
    aggregate = _aggregate_style_features(samples)
    status = "RECURRING" if len(samples) >= 2 else "OBSERVED_ONCE"
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO style_profile_samples(sample_id, profile_id, manuscript_id,
               source_version_ids_json, sample_sha256, character_count, features_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (sample_id, profile_id, manuscript_id, _json(sample["source_version_ids"]),
             sample["sample_sha256"], len(sample["content"]), _json(sample["features"]), now),
        )
        connection.execute(
            """UPDATE style_profiles SET features_json = ?, status = ?, decided_by = NULL,
               decision_reason = NULL, decided_at = NULL WHERE profile_id = ?""",
            (_json(aggregate), status, profile_id),
        )
        append_audit(connection, "style_profile_sample_added", "style_profile", profile_id,
                     {"manuscript_id": manuscript_id, "sample_id": sample_id, "sample_count": len(samples)})
    return style_profile_detail(project_root, profile_id)


def decide_style_profile(project_root: Path, profile_id: str, approved: bool,
                         reviewer: str, reason: str) -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("reviewer and decision reason are required")
    profile = style_profile_detail(project_root, profile_id)
    if profile["status"] not in {"OBSERVED_ONCE", "RECURRING", "AUTHOR_APPROVED"}:
        raise ValueError(f"style profile is already {profile['status']}")
    status = ("STABLE_PROFILE" if len(profile["samples"]) >= 3 else "AUTHOR_APPROVED") if approved else "REJECTED"
    now = utc_now()
    with connect(project_root) as connection:
        connection.execute(
            "UPDATE style_profiles SET status = ?, decided_by = ?, decision_reason = ?, decided_at = ? WHERE profile_id = ?",
            (status, reviewer, reason, now, profile_id),
        )
        append_audit(connection, "style_profile_decided", "style_profile", profile_id,
                     {"approved": approved, "reviewer": reviewer, "reason": reason})
    return style_profile_detail(project_root, profile_id)


def style_profile_detail(project_root: Path, profile_id: str) -> dict[str, Any]:
    with connect(project_root) as connection:
        row = connection.execute("SELECT * FROM style_profiles WHERE profile_id = ?", (profile_id,)).fetchone()
        sample_rows = connection.execute(
            "SELECT * FROM style_profile_samples WHERE profile_id = ? ORDER BY created_at", (profile_id,),
        ).fetchall()
    if row is None:
        raise KeyError(f"unknown style profile: {profile_id}")
    result = dict(row)
    result["features"] = json.loads(result.pop("features_json"))
    result["samples"] = []
    for sample_row in sample_rows:
        sample = dict(sample_row)
        sample["source_version_ids"] = json.loads(sample.pop("source_version_ids_json"))
        sample["features"] = json.loads(sample.pop("features_json"))
        result["samples"].append(sample)
    return result


def list_style_profiles(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        ids = [row[0] for row in connection.execute("SELECT profile_id FROM style_profiles ORDER BY created_at DESC")]
    return [style_profile_detail(project_root, value) for value in ids]


def _validate_markers(content: str, markers: list[str], evidence_contract: dict[str, Any] | None = None) -> dict[str, Any]:
    missing = [marker for marker in markers if marker not in content]
    result: dict[str, Any] = {"valid": not missing, "missing_markers": missing}
    if evidence_contract:
        allowed_ids = set(evidence_contract["evidence_ids"])
        marker_tokens = re.findall(r"\[EVID:([^\]\r\n]*)\]", content)
        malformed_markers = [token for token in marker_tokens if not re.fullmatch(r"[A-Za-z0-9_]+", token)]
        cited_ids = [token for token in marker_tokens if re.fullmatch(r"[A-Za-z0-9_]+", token)]
        invalid_ids = [evidence_id for evidence_id in cited_ids if evidence_id not in allowed_ids]
        def normalize_quote(value: str) -> str:
            return re.sub(r"\s+", " ", re.sub("\u00ad\\s*", "\u00ad", value)).strip()
        allowed_quotes = {normalize_quote(quote) for quote in evidence_contract["quotes"]}
        direct_quotes: list[str] = []
        for pattern in (r"“([^”]{12,})”", r"„([^“”\"]{12,})[“”\"]", r"«([^»]{12,})»", r'"([^"\n]{12,})"'):
            direct_quotes.extend(re.findall(pattern, content))
        altered_quotes = [
            quote for quote in direct_quotes
            if normalize_quote(quote) not in allowed_quotes
        ]
        result.update({
            "evidence_linked": bool(cited_ids),
            "cited_evidence_ids": list(dict.fromkeys(cited_ids)),
            "invalid_evidence_ids": list(dict.fromkeys(invalid_ids)),
            "malformed_evidence_markers": list(dict.fromkeys(malformed_markers)),
            "altered_quotes": list(dict.fromkeys(altered_quotes)),
        })
        result["valid"] = bool(
            result["valid"] and cited_ids and not invalid_ids and not malformed_markers and not altered_quotes
        )
    return result


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
        payload = {
            "model": model,
            "stream": False,
            "options": {"num_predict": int(os.getenv("HRW_AGENT_WRITE_MAX_TOKENS", "8192"))},
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Content-Type": "application/json"}
    else:
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": int(os.getenv("HRW_AGENT_WRITE_MAX_TOKENS", "8192")),
            "messages": [{"role": "user", "content": prompt}],
        }
        if "api.deepseek.com" in base or model.startswith("deepseek-"):
            payload["thinking"] = {"type": "disabled"}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['HRW_AGENT_API_KEY']}"}
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST")
    timeout = int(os.getenv("HRW_AGENT_TIMEOUT_SECONDS", "120"))
    with urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where())) as response:
        raw = json.loads(response.read().decode())
    content = (raw.get("message", {}).get("content", "") if provider == "ollama"
               else raw["choices"][0]["message"].get("content", ""))
    if not content.strip():
        raise ValueError("writing model returned an empty response")
    return content


def _secondary_review_capability() -> dict[str, Any]:
    provider = os.getenv("HRW_REVIEW_PROVIDER", "").strip().lower()
    model = os.getenv("HRW_REVIEW_MODEL", "").strip()
    endpoint = os.getenv("HRW_REVIEW_BASE_URL", "").strip()
    available = provider in {"openai_compatible", "ollama"} and bool(model and endpoint)
    if provider == "openai_compatible" and not os.getenv("HRW_REVIEW_API_KEY"):
        available = False
    return {"provider": provider or "disabled", "model": model, "available": available}


def _review_model_write(prompt: str, prefix: str) -> str:
    provider = os.environ[f"{prefix}_PROVIDER"].strip().lower()
    model = os.environ[f"{prefix}_MODEL"].strip()
    base = os.environ[f"{prefix}_BASE_URL"].rstrip("/")
    output_budget = int(os.getenv(f"{prefix}_REVIEW_MAX_TOKENS", "8192"))
    if provider == "ollama":
        url = base if base.endswith("/api/chat") else base + "/api/chat"
        payload = {"model": model, "stream": False, "options": {"num_predict": output_budget},
                   "messages": [{"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json"}
    else:
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        payload = {"model": model, "temperature": 0, "max_tokens": output_budget,
                   "messages": [{"role": "user", "content": prompt}]}
        if "api.deepseek.com" in base or model.startswith("deepseek-"):
            payload["thinking"] = {"type": "disabled"}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {os.environ[f'{prefix}_API_KEY']}"}
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST")
    timeout = int(os.getenv(f"{prefix}_TIMEOUT_SECONDS", "120"))
    with urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where())) as response:
        raw = json.loads(response.read().decode())
    if provider == "ollama":
        content = raw.get("message", {}).get("content", "")
        finish_reason = raw.get("done_reason", "unknown")
        message = raw.get("message", {})
    else:
        choice = raw["choices"][0]
        message = choice.get("message", {})
        content = message.get("content") or ""
        finish_reason = choice.get("finish_reason", "unknown")
    if not content.strip():
        reasoning_chars = len(message.get("reasoning_content") or "")
        fields = ",".join(sorted(key for key in message if key not in {"reasoning_content", "content"}))
        raise ValueError(
            "review model returned no final content "
            f"(finish_reason={finish_reason}, reasoning_chars={reasoning_chars}, fields={fields or 'none'})"
        )
    return content


def _primary_review_write(prompt: str) -> str:
    return _review_model_write(prompt, "HRW_AGENT")


def _secondary_review_write(prompt: str) -> str:
    return _review_model_write(prompt, "HRW_REVIEW")


def create_writing_proposal(project_root: Path, section_id: str, operation: str,
                            instruction: str, freeze_id: str = "", writer: Writer | None = None,
                            evidence_ids: list[str] | None = None, skill_name: str = "",
                            style_profile_id: str = "") -> dict[str, Any]:
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
    if operation == "polish" and base_content.strip() in {"", "待写", "（待写）", "(待写)"}:
        raise ValueError("placeholder sections require metadata_draft instead of polish")
    markers = (_historical_markers(base_content) if operation == "historical_humanize"
               else (_markers(base_content) if operation == "polish" else []))
    if operation == "section_draft":
        freeze = freeze_detail(project_root, freeze_id)
        if freeze["status"] != "approved":
            raise ValueError("section drafting requires an approved evidence freeze")
        frozen_ids = {
            evidence["evidence_id"]
            for claim in freeze["payload"]["claims"] for evidence in claim["evidence"]
        }
        if evidence_ids is not None:
            selected_ids = list(dict.fromkeys(value.strip() for value in evidence_ids if value.strip()))
            if not selected_ids:
                raise ValueError("section drafting requires at least one selected frozen evidence item")
            unknown = [value for value in selected_ids if value not in frozen_ids]
            if unknown:
                raise ValueError(f"evidence is not part of the approved freeze: {unknown[0]}")
            selected = set(selected_ids)
        else:
            selected = frozen_ids
        scoped_claims = []
        for claim in freeze["payload"]["claims"]:
            scoped_evidence = [evidence for evidence in claim["evidence"] if evidence["evidence_id"] in selected]
            if scoped_evidence:
                scoped_claims.append({**claim, "evidence": scoped_evidence})
        evidence_by_id: dict[str, dict[str, Any]] = {}
        claim_ids_by_evidence: dict[str, list[str]] = {}
        for claim in scoped_claims:
            for evidence in claim["evidence"]:
                evidence_by_id.setdefault(evidence["evidence_id"], evidence)
                claim_ids_by_evidence.setdefault(evidence["evidence_id"], []).append(claim["claim_id"])
        evidence_refs = [
            {"claim_ids": claim_ids_by_evidence[evidence_id], "evidence_id": evidence_id,
             "page_id": evidence["page_id"], "source_version_id": evidence["source_version_id"]}
            for evidence_id, evidence in evidence_by_id.items()
        ]
        evidence_contract = {
            "evidence_ids": list(evidence_by_id),
            "quotes": [evidence["quote"] for evidence in evidence_by_id.values()],
        }
        claim_text = "\n".join(
            f"- {claim['claim_id']}：{claim['text']}" for claim in scoped_claims
        )
        evidence_text = "\n".join(
            f"- [EVID:{evidence_id}]｜支持主张 {','.join(claim_ids_by_evidence[evidence_id])}"
            f"｜关系 {evidence['relation']}｜物理页 "
            f"{'–'.join(str(page) for page in evidence.get('physical_pages', [evidence['physical_page']]))}"
            f"｜原文：{evidence['quote']}"
            for evidence_id, evidence in evidence_by_id.items()
        )
        boundary = freeze["payload"].get("boundary", "")
        approval_reason = freeze["payload"].get("approval", {}).get("reason", "")
        prompt = (
            f"依据以下已冻结证据撰写章节《{row['heading']}》。\n"
            "写作契约：\n"
            "1. 只能陈述原文直接支持的事实；人工批准的主张是待论证解释，不能冒充原文记载。\n"
            "2. 每个事实性段落至少附一个 [EVID:证据编号]；只能使用下列证据编号。\n"
            "3. 直接引文必须逐字复制下列原文并紧跟 [EVID:证据编号]，不得翻译、改写或拼接原文；若不直接引用则用审慎转述。\n"
            "4. counterevidence 与限制条件必须保留；证据不足处写成问题、假设或明确的待补证项。\n"
            "5. 只返回章节正文，不写工作说明，不补造学术史。\n"
            f"冻结边界：{boundary}\n人工批准依据：{approval_reason}\n具体要求：{instruction}\n\n"
            f"人工批准的解释性主张（不能替代原文证据）：\n{claim_text}\n\n"
            f"冻结证据（同一证据只列一次）：\n{evidence_text}"
        )
        fallback = "\n\n".join(
            f"{claim['text']}\n\n" + "".join(
                f"材料记载：“{e['quote']}”[EVID:{e['evidence_id']}]（物理页 {e['physical_page']}）。"
                for e in claim["evidence"]
            ) for claim in scoped_claims
        )
    elif operation == "metadata_draft":
        evidence_contract = None
        with connect(project_root) as connection:
            manuscript = connection.execute(
                "SELECT title FROM manuscripts WHERE manuscript_id = ?", (row["manuscript_id"],)
            ).fetchone()
            approved_sections = connection.execute(
                """SELECT s.heading, v.content FROM manuscript_sections s
                   JOIN section_versions v ON v.version_id = s.current_version_id
                   WHERE s.manuscript_id = ? AND s.section_id != ?
                   ORDER BY s.section_order""",
                (row["manuscript_id"], section_id),
            ).fetchall()
        excluded = ("摘要", "关键词", "英文", "作者", "投稿", "参考文献")
        body = "\n\n".join(
            f"## {item['heading']}\n{item['content']}" for item in approved_sections
            if not any(label in item["heading"] for label in excluded)
            and item["content"].strip() not in {"", "待写", "（待写）", "(待写)"}
        )
        if len(body) < 500:
            raise ValueError("metadata drafting requires an approved manuscript body")
        prompt = (
            f"只依据下列已批准论文正文，为《{manuscript['title']}》生成“{row['heading']}”。\n"
            "硬约束：不得引入正文没有的人物、年代、地点、材料或结论；不得输出证据编号、参考文献、"
            "脚注或工作说明；不得把方法上的限定改成强结论。只返回可直接放入稿件的内容。\n"
            f"具体要求：{instruction}\n\n已批准正文：\n{body}"
        )
        fallback = base_content
    elif operation == "historical_humanize":
        evidence_contract = None
        selected_skill = get_skill(skill_name or "historical-humanizer-zh")
        profile = None
        if style_profile_id:
            profile = style_profile_detail(project_root, style_profile_id)
            if profile["status"] not in {"AUTHOR_APPROVED", "STABLE_PROFILE"}:
                raise ValueError("style profile must be author approved before use")
        style_context = _json(profile["features"]) if profile else "未选择作者画像；只使用通用史学表达规则"
        prompt = (
            "对以下中文历史学段落制作证据保真的语言修订副本。只返回修订正文。\n"
            "硬约束：不得改变事实、归因、因果、时间顺序、论证范围、限定词、阴性结果；不得改变引文、译文、"
            "脚注、页码、档号、专名、数字、术语、URL；不得增加第一人称、情绪、反问或模仿具体学者。\n"
            "表达操作：让材料和行动者先于抽象概念，叙事与分析交替，删除内部流程语言和重复总结；"
            "无法确定为纯语言变化时保留原句。\n"
            f"技能：{selected_skill['name']} / SHA-256 {selected_skill['sha256']}。\n"
            f"经批准的高层文风画像：{style_context}\n具体要求：{instruction}\n\n{base_content}"
        )
        fallback = base_content
    else:
        evidence_contract = None
        prompt = (
            "润色以下中文历史学论文段落。不得新增、删除或强化事实，不得改变引文、数字、脚注标记和来源标识。"
            f"只返回修改后正文。具体要求：{instruction}\n\n{base_content}"
        )
        fallback = re.sub(r"[ \t]+", " ", base_content).replace(" ,", "，").replace(" .", "。")
    proposed = (writer(prompt) if writer else (_model_write(prompt) if _model_capability()["available"] else fallback)).strip()
    validation = _validate_markers(proposed, markers, evidence_contract)
    if operation == "historical_humanize":
        before = [value.strip() for value in re.split(r"\n\s*\n", base_content) if value.strip()]
        after = [value.strip() for value in re.split(r"\n\s*\n", proposed) if value.strip()]
        validation.update({
            "semantic_review_required": True,
            "guard_status": "PASS_EXACT_GUARD_NEEDS_MANUAL_REVIEW" if validation["valid"] else "BLOCKED_PROTECTED_CHANGE",
            "paragraph_decisions": [
                {"paragraph": index + 1, "decision": "KEEP" if old == new else "MANUAL_REVIEW"}
                for index, (old, new) in enumerate(zip(before, after))
            ],
        })
    proposal_id, now = _id("WPR"), utc_now()
    snapshot = {
        **_model_capability(), "mode": "injected" if writer else "runtime", "freeze_id": freeze_id,
        "evidence_contract": evidence_contract,
        "skill": ({"name": selected_skill["name"], "sha256": selected_skill["sha256"]}
                  if operation == "historical_humanize" else None),
        "style_profile_id": style_profile_id,
    }
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
                            reviewer: str, edited_content: str | None = None,
                            reason: str = "") -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("reviewer and decision reason are required")
    proposal = proposal_detail(project_root, proposal_id)
    if proposal["status"] != "pending":
        raise ValueError(f"writing proposal is already {proposal['status']}")
    final_content = (edited_content if edited_content is not None else proposal["proposed_content"]).strip()
    contract = proposal["model_snapshot"].get("evidence_contract")
    validation = _validate_markers(final_content, proposal["protected_markers"], contract)
    validation["decision_reason"] = reason
    if approved and not validation["valid"]:
        if validation["missing_markers"]:
            raise ValueError("writing proposal removed protected markers: " + ", ".join(validation["missing_markers"]))
        raise ValueError("writing proposal violates its evidence contract")
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
                     {"approved": approved, "version_id": version_id, "reviewer": reviewer, "reason": reason})
    if approved:
        from .document_model import sync_approved_section
        with connect(project_root) as connection:
            manuscript_id = connection.execute(
                "SELECT manuscript_id FROM manuscript_sections WHERE section_id = ?", (proposal["section_id"],)
            ).fetchone()[0]
        document = sync_approved_section(
            project_root, str(manuscript_id), proposal["section_id"], final_content, version_id,
        )
    else:
        document = None
    return {"proposal_id": proposal_id, "status": status, "version_id": version_id,
            "validation": validation,
            "document_revision_id": document["current_revision_id"] if document else ""}


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
        reviews = [dict(row) for row in connection.execute(
            """SELECT * FROM manuscript_reviews WHERE manuscript_id = ?
               ORDER BY created_at DESC, reviewer_role""",
            (manuscript_id,),
        )]
    current_versions = [section["current_version_id"] for section in sections]
    for review in reviews:
        review["model_snapshot"] = json.loads(review["model_snapshot_json"])
        review["section_versions"] = json.loads(review["section_versions_json"])
        review["is_current"] = review["section_versions"] == current_versions
    groups: list[dict[str, Any]] = []
    for review in reviews:
        group = next((item for item in groups if item["review_group_id"] == review["review_group_id"]), None)
        if group is None:
            group = {
                "review_group_id": review["review_group_id"], "created_at": review["created_at"],
                "template_id": review["template_id"], "is_current": review["is_current"], "reports": [],
            }
            groups.append(group)
        group["reports"].append(review)
        group["is_current"] = bool(group["is_current"] and review["is_current"])
    return {**dict(manuscript), "sections": sections, "review_groups": groups}


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
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO reading_jobs(job_id, title, question, mode, source_ids_json, stop_condition, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)",
            (job_id, title.strip(), question.strip(), mode, _json(source_ids), stop_condition.strip(), now),
        )
    return {"job_id": job_id, "title": title, "question": question, "mode": mode,
            "stop_condition": stop_condition, "status": "running", "notes": []}


def reading_job_batch(project_root: Path, job_id: str, source_id: str,
                      after_physical_page: int = 0, page_limit: int = 5) -> dict[str, Any]:
    if not 1 <= page_limit <= 10:
        raise ValueError("reading page_limit must be between 1 and 10")
    with connect(project_root) as connection:
        job = connection.execute("SELECT * FROM reading_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if job is None:
            raise KeyError(f"unknown reading job: {job_id}")
        if source_id not in json.loads(job["source_ids_json"]):
            raise ValueError("source is not assigned to this reading job")
        selected_pages = connection.execute(
            """SELECT page_id, physical_page, printed_page, verification_state, use_state
               FROM pages WHERE source_id = ? AND physical_page > ?
                 AND use_state = 'research_usable'
               ORDER BY physical_page LIMIT ?""",
            (source_id, after_physical_page, page_limit),
        ).fetchall()
        pages = []
        for page in selected_pages:
            blocks = connection.execute(
                """SELECT block_id, block_order, block_type,
                          COALESCE(human_text, machine_text) AS text,
                          verification_state, use_state
                   FROM blocks WHERE page_id = ? AND use_state = 'research_usable'
                   ORDER BY block_order""",
                (page["page_id"],),
            ).fetchall()
            pages.append({**dict(page), "blocks": [dict(block) for block in blocks]})
        total_pages = connection.execute(
            "SELECT COUNT(*) FROM pages WHERE source_id = ?", (source_id,)
        ).fetchone()[0]
        usable_pages = connection.execute(
            "SELECT COUNT(*) FROM pages WHERE source_id = ? AND use_state = 'research_usable'", (source_id,)
        ).fetchone()[0]
        last_page = pages[-1]["physical_page"] if pages else after_physical_page
        has_more = connection.execute(
            """SELECT 1 FROM pages WHERE source_id = ? AND physical_page > ?
               AND use_state = 'research_usable' LIMIT 1""", (source_id, last_page),
        ).fetchone() is not None
    return {
        "job_id": job_id, "source_id": source_id, "mode": job["mode"],
        "question": job["question"], "stop_condition": job["stop_condition"],
        "pages": pages, "next_after_physical_page": last_page, "has_more": has_more,
        "total_pages": total_pages, "usable_pages": usable_pages,
        "blocked_or_unusable_pages": total_pages - usable_pages,
    }


def save_reading_note(project_root: Path, job_id: str, source_id: str,
                      physical_pages: list[int], content: str,
                      complete: bool = False) -> dict[str, Any]:
    pages = sorted({int(value) for value in physical_pages})
    if not pages or not content.strip():
        raise ValueError("reading note requires physical pages and content")
    with connect(project_root) as connection:
        job = connection.execute("SELECT * FROM reading_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if job is None:
            raise KeyError(f"unknown reading job: {job_id}")
        source_ids = json.loads(job["source_ids_json"])
        if source_id not in source_ids:
            raise ValueError("source is not assigned to this reading job")
        placeholders = ",".join("?" for _ in pages)
        page_rows = connection.execute(
            f"""SELECT page_id, physical_page FROM pages
                WHERE source_id = ? AND physical_page IN ({placeholders})
                  AND use_state = 'research_usable' ORDER BY physical_page""",
            (source_id, *pages),
        ).fetchall()
        if [row["physical_page"] for row in page_rows] != pages:
            raise ValueError("reading note pages must all be research usable")
        refs = []
        for page in page_rows:
            blocks = connection.execute(
                """SELECT block_id FROM blocks WHERE page_id = ? AND use_state = 'research_usable'
                   ORDER BY block_order""", (page["page_id"],),
            ).fetchall()
            refs.extend({"page_id": page["page_id"], "physical_page": page["physical_page"],
                         "block_id": block["block_id"]} for block in blocks)
        note_id, now = _id("RDN"), utc_now()
        connection.execute(
            """INSERT INTO reading_notes(note_id, job_id, source_id, page_refs_json, content,
               qualification, created_at) VALUES (?, ?, ?, ?, ?, 'READING_NOTE_NOT_EVIDENCE', ?)""",
            (note_id, job_id, source_id, _json(refs), content.strip(), now),
        )
        status = str(job["status"])
        if complete:
            if job["mode"] == "full":
                incomplete = False
                needs_repair = False
                for assigned_source_id in source_ids:
                    covered = {
                        int(ref["physical_page"])
                        for row in connection.execute(
                            "SELECT page_refs_json FROM reading_notes WHERE job_id = ? AND source_id = ?",
                            (job_id, assigned_source_id),
                        )
                        for ref in json.loads(row["page_refs_json"])
                    }
                    usable = connection.execute(
                        "SELECT COUNT(*) FROM pages WHERE source_id = ? AND use_state = 'research_usable'",
                        (assigned_source_id,),
                    ).fetchone()[0]
                    total = connection.execute(
                        "SELECT COUNT(*) FROM pages WHERE source_id = ?", (assigned_source_id,)
                    ).fetchone()[0]
                    incomplete = incomplete or len(covered) < usable
                    needs_repair = needs_repair or usable < total
                status = "running" if incomplete else ("needs_repair" if needs_repair else "completed")
            else:
                noted_sources = {
                    row["source_id"] for row in connection.execute(
                        "SELECT DISTINCT source_id FROM reading_notes WHERE job_id = ?", (job_id,)
                    )
                }
                status = "completed" if set(source_ids) <= noted_sources else "running"
            connection.execute(
                "UPDATE reading_jobs SET status = ?, completed_at = ? WHERE job_id = ?",
                (status, now, job_id),
            )
    return {"note_id": note_id, "job_id": job_id, "source_id": source_id,
            "physical_pages": pages, "qualification": "READING_NOTE_NOT_EVIDENCE",
            "status": status}


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
                """UPDATE journal_templates SET name = ?, citation_style = ?, section_rules_json = ?,
                   format_rules_json = ? WHERE template_id = ? AND origin = 'builtin'""",
                (item["name"], item["citation_style"], _json(item["section_rules"]),
                 _json(item["requirements"]), item["template_id"]),
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
                            section_rules: list[str], version_label: str = "",
                            effective_date: str = "", source_url: str = "",
                            verified_at: str = "", verification_status: str = "USER_DEFINED",
                            requirements: dict[str, Any] | None = None) -> dict[str, Any]:
    if not name.strip() or not citation_style.strip() or not section_rules:
        raise ValueError("journal template requires name, citation style and section rules")
    template_id, now = _id("JTP"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            "INSERT INTO journal_templates(template_id, name, citation_style, section_rules_json, format_rules_json, origin, created_at) VALUES (?, ?, ?, ?, ?, 'user', ?)",
            (template_id, name.strip(), citation_style.strip(), _json(section_rules), _json(requirements or {}), now),
        )
        if version_label.strip() or source_url.strip():
            connection.execute(
                """INSERT INTO journal_template_revisions(template_revision_id, template_id,
                   version_label, effective_date, source_url, verified_at, requirements_json,
                   verification_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_id("JTR"), template_id, version_label.strip() or "人工核验版",
                 effective_date.strip(), source_url.strip(), verified_at.strip(),
                 _json(requirements or {}), verification_status.strip() or "USER_DEFINED", now),
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


def run_manuscript_review(project_root: Path, manuscript_id: str, template_id: str,
                          use_secondary: bool = False, reviewer: Writer | None = None) -> dict[str, Any]:
    manuscript = manuscript_detail(project_root, manuscript_id)
    template = next((item for item in ensure_journal_templates(project_root)
                     if item["template_id"] == template_id), None)
    if template is None:
        raise KeyError(f"unknown journal template: {template_id}")
    roles = ["adversarial_reviewer"] if use_secondary else [
        "argument_reviewer", "source_critic", "citation_editor",
    ]
    capability = ({"provider": "injected", "model": "test-reviewer", "available": True}
                  if reviewer else (_secondary_review_capability() if use_secondary else _model_capability()))
    if not capability["available"]:
        role_name = "交叉评审模型" if use_secondary else "主推理模型"
        raise ValueError(f"{role_name}尚未配置")
    section_versions = [section["current_version_id"] for section in manuscript["sections"]]
    internal_manuscript_text = "\n\n".join(
        f"## {section['heading']}\n{section['content']}" for section in manuscript["sections"]
    )
    from .document_model import preview_document_export
    export_preview = preview_document_export(project_root, manuscript_id, template_id)
    manuscript_text = export_preview["markdown"]
    research = research_state(project_root)
    shared_design = current_shared_design(project_root)
    cited_evidence_ids = set(re.findall(r"\[EVID:([A-Za-z0-9_]+)\]", internal_manuscript_text))
    approved_freezes = [freeze for freeze in research["freezes"] if freeze["status"] == "approved"]
    relevant_freezes = [
        freeze for freeze in approved_freezes
        if any(
            evidence["evidence_id"] in cited_evidence_ids
            for claim in freeze["payload"]["claims"] for evidence in claim["evidence"]
        )
    ] or approved_freezes
    with connect(project_root) as connection:
        page_printed = {
            row["page_id"]: str(row["printed_page"] or "").strip()
            for row in connection.execute("SELECT page_id, printed_page FROM pages")
        }
    evidence_lines, seen_evidence = [], set()
    for freeze in relevant_freezes:
        evidence_lines.append(f"批准冻结包 {freeze['freeze_id']}：{freeze['title']}")
        for claim in freeze["payload"]["claims"]:
            evidence_lines.append(f"主张 {claim['claim_id']}：{claim['text']}")
            for evidence in claim["evidence"]:
                if evidence["evidence_id"] in seen_evidence:
                    continue
                seen_evidence.add(evidence["evidence_id"])
                pages = "–".join(str(value) for value in evidence.get("physical_pages", [evidence["physical_page"]]))
                printed_values = evidence.get("printed_pages", []) or [
                    page_printed.get(str(page_id), "") for page_id in evidence.get("page_ids", [])
                ]
                printed = "–".join(str(value) for value in printed_values if value)
                locator = f"原书页 {printed}｜物理页 {pages}" if printed else f"物理页 {pages}"
                evidence_lines.append(
                    f"- {evidence['evidence_id']}｜{evidence['relation']}｜{evidence['source_id']}｜{locator}"
                    f"｜FROZEN_APPROVED｜{evidence['qualification']}｜{evidence['quote']}"
                )
    previous_reports = ""
    if use_secondary and manuscript["review_groups"]:
        latest = next((group for group in manuscript["review_groups"] if group["is_current"]), None)
        if latest:
            previous_reports = "\n\n前三份评审：\n" + "\n\n".join(
                f"### {report['reviewer_role']}\n{report['report']}" for report in latest["reports"]
            )
    group_id, now = _id("MRG"), utc_now()
    def generate(role: str) -> dict[str, Any]:
        prompt = (
            "你是历史学论文的独立评审者。只评审，不重写正文，不补造事实或书目信息。"
            "正文是按所选期刊模板生成的导出预览；内部 [EVID:...] 已转换为读者可见的引文。"
            "请结合证据台账核对正文引文，不把模型记忆当作来源。\n"
            "引文必须使用原书印刷页；物理页只用于在 PDF 中回查，不得用物理页替换原书页。"
            "参考文献表通常不要求补写卷册总页数，不得因书目条目没有总页数而否定已核原书页。\n"
            "证据台账中的 CANDIDATE_NOT_FROZEN 只能作为有界回退线索，不能当作当前正文已经获准使用的证据；"
            "只有 FROZEN_APPROVED 且实际进入稿件的证据才能支撑当前论断。\n"
            f"本轮角色：{role}\n职责：{REVIEW_ROLES[role]}\n"
            "请用中文依次输出：阻断问题、主要问题、次要问题、可保留之处、建议的有界回退步骤。"
            "每个问题指出具体章节或证据编号；没有证据就明确说没有。不要展示推理过程，"
            "直接给出 600—900 字的正式评审报告。\n\n"
            f"稿件题名：{manuscript['title']}\n当前字符数：{len(manuscript_text)}\n"
            f"投稿模板：{template['name']}｜{template['version_label']}｜{template['citation_style']}\n"
            f"模板组成：{'；'.join(template['section_rules'])}\n\n"
            f"导出门禁：{export_preview['citation_status']}｜"
            f"{'；'.join(export_preview['warnings']) or '当前未发现导出门禁'}\n\n"
            "人工批准研究设计（这是作者的范围与方法决定，不是史料事实；不要因其缺少史料引文而否定，"
            "但可以检查正文是否越出或误用这一边界）：\n"
            f"{shared_design['title'] + chr(10) + shared_design['content'] if shared_design else '当前没有人工批准的共同计划。'}\n\n"
            f"证据台账：\n{chr(10).join(evidence_lines) or '当前没有已登记证据。'}\n\n"
            f"期刊导出预览：\n{manuscript_text}{previous_reports}"
        )
        report = (reviewer(prompt) if reviewer else
                  (_secondary_review_write(prompt) if use_secondary else _primary_review_write(prompt))).strip()
        if len(report) < 20:
            raise ValueError(f"{role} returned an empty or unusably short review")
        review_id = _id("MRV")
        model_snapshot = {**capability, "model_role": "review_secondary" if use_secondary else "main_reasoning"}
        return {"review_id": review_id, "reviewer_role": role, "report": report,
                "model_snapshot": model_snapshot, "status": "completed"}
    if reviewer is None and len(roles) > 1:
        with ThreadPoolExecutor(max_workers=len(roles)) as pool:
            reports = list(pool.map(generate, roles))
    else:
        reports = [generate(role) for role in roles]
    with connect(project_root) as connection:
        for report in reports:
            connection.execute(
                """INSERT INTO manuscript_reviews(
                       review_id, review_group_id, manuscript_id, reviewer_role, model_role,
                       model_snapshot_json, section_versions_json, template_id, report, status, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?)""",
                (report["review_id"], group_id, manuscript_id, report["reviewer_role"],
                 report["model_snapshot"]["model_role"], _json(report["model_snapshot"]),
                 _json(section_versions), template_id, report["report"], now),
            )
            append_audit(connection, "manuscript_review_completed", "manuscript", manuscript_id,
                         {"review_group_id": group_id, "reviewer_role": report["reviewer_role"],
                          "model_role": report["model_snapshot"]["model_role"]})
    return {"review_group_id": group_id, "manuscript_id": manuscript_id, "template_id": template_id,
            "is_current": True, "reports": reports, "created_at": now}


def authoring_state(project_root: Path) -> dict[str, Any]:
    return {"manuscripts": list_manuscripts(project_root), "reading_jobs": list_reading_jobs(project_root),
            "historiography": list_historiography(project_root),
            "journal_templates": ensure_journal_templates(project_root), "writing_model": _model_capability(),
            "style_profiles": list_style_profiles(project_root),
            "submission_profiles": submission_profiles(project_root),
            "review_models": {"primary": _model_capability(), "secondary": _secondary_review_capability()},
            "formal_research_readiness": formal_research_readiness(project_root)}


def submission_profiles(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        return [
            {"manuscript_id": row["manuscript_id"], **json.loads(row["profile_json"]),
             "updated_at": row["updated_at"]}
            for row in connection.execute(
                "SELECT manuscript_id, profile_json, updated_at FROM manuscript_submission_profiles"
            )
        ]


def save_submission_profile(project_root: Path, manuscript_id: str,
                            payload: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "name", "real_name", "gender", "ethnicity", "native_place", "degree", "discipline",
        "affiliation", "professional_title", "position", "research_interests", "project_source",
        "project_number", "phone", "postal_address", "postal_code", "email",
    )
    profile = {key: str(payload.get(key, "")).strip() for key in allowed}
    now = utc_now()
    with connect(project_root) as connection:
        if connection.execute("SELECT 1 FROM manuscripts WHERE manuscript_id = ?", (manuscript_id,)).fetchone() is None:
            raise KeyError(f"unknown manuscript: {manuscript_id}")
        connection.execute(
            "INSERT OR REPLACE INTO manuscript_submission_profiles(manuscript_id, profile_json, updated_at) VALUES (?, ?, ?)",
            (manuscript_id, _json(profile), now),
        )
        append_audit(connection, "submission_profile_saved", "manuscript", manuscript_id,
                     {"fields": [key for key, value in profile.items() if value]})
    return {"manuscript_id": manuscript_id, **profile, "updated_at": now}
