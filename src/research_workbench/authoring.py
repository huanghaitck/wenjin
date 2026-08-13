from __future__ import annotations

import json
import hashlib
import os
import re
import ssl
import statistics
import unicodedata
import uuid
from collections import Counter
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
INTERNAL_PROSE_PATTERNS = {
    "internal_process": re.compile(
        r"(?:正式研究)?门禁|证据冻结|冻结(?:证据|边界|依据|文件|包)|"
        r"(?:工作台|项目)(?:内部|随研究包)|补证(?:票|任务)|待补证项|"
        r"(?:事件|证据)(?:台账|清单)|在本文中的作用|核心个案(?:之一)?|"
        r"核心窗口|时间锚|观察段|正文时段|EVID:|CITE:|Phase\s*\d|Agent",
        re.I,
    ),
    "defensive_cluster": re.compile(
        r"(?:不能|不得|不等于|并非|不再|不作|不以|只限于|仅限于).{0,90}"
        r"(?:不能|不得|不等于|并非|不再|不作|不以|只限于|仅限于)"
    ),
    "process_exposition": re.compile(
        r"在材料层面|本文所能确认|本文所用材料中|"
        r"这里所能确认|还要另查|待后续查证|"
        r"故不纳入(?:本文|表\s*\d)|故不列入表\s*\d|"
        r"不据此统计|不据此推断|本文能够讨论的是|"
        r"该研究提供的是.{0,20}(?:参照|参照系|参考)"
    ),
}
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
    patterns = [
        r"“[^”]+”", r"\[\^[^\]]+\]", r"\[(?:EVID|CITE):[^\]\r\n]+\]",
        r"(?<![A-Za-z0-9_])\d+(?:[.,:]\d+)*(?![A-Za-z0-9_])", r"(?:SRC|EVI|CLM|FRZ)_[A-Za-z0-9_]+",
    ]
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


def _is_complete_markdown_table(text: str) -> bool:
    """Accept one complete, rectangular Markdown table and no surrounding prose."""
    lines = text.replace("\r\n", "\n").strip().splitlines()
    if len(lines) < 3:
        return False
    rows: list[list[str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            return False
        rows.append([cell.strip() for cell in stripped[1:-1].split("|")])
    width = len(rows[0])
    if width < 2 or any(len(row) != width for row in rows):
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1])


def _direct_quote_contents(text: str) -> list[str]:
    quotes: list[str] = []
    for pattern in (r"“([^”]{12,})”", r"„([^“”\"]{12,})[“”\"]", r"«([^»]{12,})»", r'"([^"\n]{12,})"'):
        quotes.extend(re.findall(pattern, text))
    return quotes


def _approved_freeze_evidence_scope(project_root: Path, freeze_id: str,
                                    evidence_ids: list[str] | None) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not freeze_id.strip():
        raise ValueError("selection evidence supplement requires an approved evidence freeze")
    selected_ids = list(dict.fromkeys(
        str(value).strip() for value in (evidence_ids or []) if str(value).strip()
    ))
    if not selected_ids:
        raise ValueError("selection evidence supplement requires at least one selected frozen evidence item")
    freeze = freeze_detail(project_root, freeze_id)
    if freeze["status"] != "approved":
        raise ValueError("selection evidence supplement requires an approved evidence freeze")
    frozen_by_id: dict[str, dict[str, Any]] = {}
    for claim in freeze["payload"].get("claims", []):
        for evidence in claim.get("evidence", []):
            evidence_id = str(evidence.get("evidence_id", "")).strip()
            if evidence_id:
                frozen_by_id.setdefault(evidence_id, evidence)
    unknown = [value for value in selected_ids if value not in frozen_by_id]
    if unknown:
        raise ValueError(f"evidence is not part of the approved freeze: {unknown[0]}")
    return freeze, {value: frozen_by_id[value] for value in selected_ids}


def _selection_evidence_supplement_validation(original: str, replacement: str,
                                               selected_evidence: dict[str, dict[str, Any]]) -> dict[str, Any]:
    before_tokens = re.findall(r"\[EVID:([^\]\r\n]*)\]", original)
    after_tokens = re.findall(r"\[EVID:([^\]\r\n]*)\]", replacement)
    before = Counter(value for value in before_tokens if re.fullmatch(r"[A-Za-z0-9_]+", value))
    after = Counter(value for value in after_tokens if re.fullmatch(r"[A-Za-z0-9_]+", value))
    added = [
        evidence_id for evidence_id, count in after.items()
        for _ in range(max(0, count - before[evidence_id]))
    ]
    allowed = set(selected_evidence)
    invalid = [evidence_id for evidence_id in added if evidence_id not in allowed]
    malformed_added = list((Counter(after_tokens) - Counter(before_tokens)).elements())
    malformed_added = [value for value in malformed_added if not re.fullmatch(r"[A-Za-z0-9_]+", value)]
    new_citations = list((
        Counter(re.findall(r"\[CITE:[^\]\r\n]+\]", replacement))
        - Counter(re.findall(r"\[CITE:[^\]\r\n]+\]", original))
    ).elements())
    protected_pattern = (r"\[EVID:[^\]\r\n]+\]|\[CITE:[^\]\r\n]+\]|\[\^[^\]]+\]|"
                         r"(?<![A-Za-z0-9_])\d+(?:[.,:]\d+)*(?![A-Za-z0-9_])")
    original_markers = Counter(re.findall(protected_pattern, original))
    replacement_markers = Counter(re.findall(protected_pattern, replacement))
    missing_protected = list((original_markers - replacement_markers).elements())
    original_quotes = Counter(_direct_quote_contents(original))
    replacement_quotes = Counter(_direct_quote_contents(replacement))
    new_quotes = list((replacement_quotes - original_quotes).elements())
    allowed_quotes = {
        re.sub(r"\s+", " ", str(evidence.get("quote", ""))).strip()
        for evidence in selected_evidence.values()
    }
    altered_quotes = [
        quote for quote in new_quotes
        if re.sub(r"\s+", " ", quote).strip() not in allowed_quotes
    ]
    return {
        "supplemental_evidence_linked": bool(added),
        "new_evidence_ids": list(dict.fromkeys(added)),
        "invalid_new_evidence_ids": list(dict.fromkeys(invalid)),
        "malformed_new_evidence_markers": list(dict.fromkeys(malformed_added)),
        "new_citation_markers": list(dict.fromkeys(new_citations)),
        "selection_missing_protected_counts": missing_protected,
        "altered_supplemental_quotes": list(dict.fromkeys(altered_quotes)),
        "supplemental_evidence_valid": bool(
            added and not invalid and not malformed_added and not new_citations
            and not missing_protected and not altered_quotes
        ),
    }


def _frozen_evidence_fingerprint(evidence_by_id: dict[str, dict[str, Any]]) -> str:
    payload = [evidence_by_id[evidence_id] for evidence_id in evidence_by_id]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validated_writing_selection(base_content: str, base_version_id: str,
                                 requested_base_version_id: str,
                                 selection: dict[str, Any] | None) -> dict[str, Any]:
    """Validate an exact, version-bound selection without guessing its location."""
    if not requested_base_version_id or requested_base_version_id != base_version_id:
        raise ValueError("selected section version is stale; reload the manuscript and select the text again")
    if not isinstance(selection, dict):
        raise ValueError("selection-only revision requires a text selection")
    try:
        start, end = int(selection["start"]), int(selection["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("selection requires exact start and end offsets") from exc
    selected_text = selection.get("text")
    selection_hash = str(selection.get("sha256", "")).strip().lower()
    node_ids = selection.get("node_ids")
    selection_kind = str(selection.get("kind", "text")).strip() or "text"
    if selection_kind not in {"text", "table"}:
        raise ValueError("selection kind must be text or table")
    if (not isinstance(selected_text, str) or not selected_text or start < 0
            or end <= start or end > len(base_content)):
        raise ValueError("selection range is empty or outside the current section")
    if not isinstance(node_ids, list) or not node_ids or any(
        not isinstance(value, str) or not value.strip() for value in node_ids
    ):
        raise ValueError("selection requires its paragraph node IDs")
    if base_content[start:end] != selected_text:
        raise ValueError("selected text no longer matches the current section; select it again")
    expected_hash = hashlib.sha256(selected_text.encode("utf-8")).hexdigest()
    if selection_hash != expected_hash:
        raise ValueError("selection fingerprint does not match the selected text")
    if base_content.count(selected_text) != 1:
        raise ValueError("selected text is not unique in the current section; select a larger unique passage")
    if selection_kind == "table":
        if len(node_ids) != 1 or not _is_complete_markdown_table(selected_text):
            raise ValueError("table selection must contain exactly one complete Markdown table")
    return {
        "start": start, "end": end, "text": selected_text, "sha256": expected_hash,
        "node_ids": list(dict.fromkeys(value.strip() for value in node_ids)), "kind": selection_kind,
    }


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


def _external_style_sample(project_root: Path, source_id: str) -> dict[str, Any]:
    verified_states = {"human_spot_checked", "human_verified", "human_repaired"}
    with connect(project_root) as connection:
        source = connection.execute(
            """SELECT s.source_id, s.title, s.use_state, m.author, m.verification_status
               FROM sources s LEFT JOIN source_citation_metadata m ON m.source_id = s.source_id
               WHERE s.source_id = ?""", (source_id,),
        ).fetchone()
        if source is None:
            raise KeyError(f"unknown project source: {source_id}")
        if source["verification_status"] != "HUMAN_VERIFIED":
            raise ValueError("external style sample requires HUMAN_VERIFIED bibliography")
        version = connection.execute(
            "SELECT * FROM source_versions WHERE source_id = ? ORDER BY created_at DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        pages = connection.execute(
            """SELECT page_id, physical_page, verification_state, use_state
               FROM pages WHERE source_id = ? ORDER BY physical_page""", (source_id,),
        ).fetchall()
        if version is None or not pages:
            raise ValueError("external style sample requires a processed exact source version")
        if source["use_state"] != "research_usable" or any(
            page["use_state"] != "research_usable" or page["verification_state"] not in verified_states
            for page in pages
        ):
            raise ValueError("external style sample requires every page to be human verified and research usable")
        page_ids = [page["page_id"] for page in pages]
        placeholders = ",".join("?" for _ in page_ids)
        blocks = connection.execute(
            f"""SELECT page_id, block_order, COALESCE(human_text, machine_text) AS text,
                       verification_state, use_state
                FROM blocks WHERE page_id IN ({placeholders})
                ORDER BY page_id, block_order""", page_ids,
        ).fetchall()
        if not blocks or any(
            block["use_state"] != "research_usable"
            or block["verification_state"] not in {"human_verified", "human_repaired"}
            for block in blocks
        ):
            raise ValueError("external style sample requires every text block to be human verified and research usable")
        open_anomaly = connection.execute(
            "SELECT 1 FROM anomalies WHERE source_id = ? AND status = 'open' LIMIT 1", (source_id,),
        ).fetchone()
        if open_anomaly is not None:
            raise ValueError("external style sample cannot contain open source, page, block, or relation anomalies")
    content = "\n\n".join(str(block["text"]).strip() for block in blocks if str(block["text"]).strip())
    if len(content) < 800:
        raise ValueError("external style sample is too short; use a verified full article with at least 800 characters")
    return {
        "sample_role": "external_verified_article", "source_id": source_id,
        "source_version_id": version["source_version_id"], "source_version_ids": [version["source_version_id"]],
        "content": content, "sample_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "features": _style_features(content), "title": source["title"],
        "author": str(source["author"]).strip(),
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
               source_version_ids_json, sample_sha256, character_count, features_json, created_at, sample_role)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manuscript')""",
            (sample_id, profile_id, manuscript_id, _json(sample["source_version_ids"]),
             sample["sample_sha256"], len(sample["content"]), _json(sample["features"]), now),
        )
        append_audit(connection, "style_profile_created", "style_profile", profile_id,
                     {"manuscript_id": manuscript_id, "sample_id": sample_id})
    return style_profile_detail(project_root, profile_id)


def create_external_style_profile(project_root: Path, source_id: str, name: str,
                                  owner_label: str, scope: str = "historical_articles") -> dict[str, Any]:
    name, owner_label, scope = name.strip(), owner_label.strip(), scope.strip()
    if not name or not owner_label:
        raise ValueError("external style profile requires a name and identified author")
    sample = _external_style_sample(project_root, source_id)
    if re.sub(r"\s+", "", owner_label).casefold() != re.sub(r"\s+", "", sample["author"]).casefold():
        raise ValueError("external style profile author must match HUMAN_VERIFIED bibliography")
    profile_id, sample_id, now = _id("STY"), _id("STS"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO style_profiles(profile_id, name, owner_label, scope, manuscript_id, section_id,
               source_version_id, sample_sha256, features_json, status, created_at)
               VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?, 'OBSERVED_ONCE', ?)""",
            (profile_id, name, owner_label, scope or "historical_articles",
             sample["sample_sha256"], _json(sample["features"]), now),
        )
        connection.execute(
            """INSERT INTO style_profile_samples(sample_id, profile_id, manuscript_id,
               source_version_ids_json, sample_sha256, character_count, features_json, created_at,
               sample_role, source_id, source_version_id)
               VALUES (?, ?, NULL, ?, ?, ?, ?, ?, 'external_verified_article', ?, ?)""",
            (sample_id, profile_id, _json(sample["source_version_ids"]), sample["sample_sha256"],
             len(sample["content"]), _json(sample["features"]), now, source_id, sample["source_version_id"]),
        )
        append_audit(connection, "external_style_profile_created", "style_profile", profile_id, {
            "source_id": source_id, "source_version_id": sample["source_version_id"], "sample_id": sample_id,
        })
    return style_profile_detail(project_root, profile_id)


def add_style_profile_sample(project_root: Path, profile_id: str, manuscript_id: str) -> dict[str, Any]:
    profile = style_profile_detail(project_root, profile_id)
    if profile["status"] == "REJECTED":
        raise ValueError("cannot add samples to a rejected style profile")
    if any(sample.get("sample_role") == "external_verified_article" for sample in profile["samples"]):
        raise ValueError("research manuscripts and external author style sources must remain separate profiles")
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
               source_version_ids_json, sample_sha256, character_count, features_json, created_at, sample_role)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manuscript')""",
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


def add_external_style_profile_sample(project_root: Path, profile_id: str, source_id: str) -> dict[str, Any]:
    profile = style_profile_detail(project_root, profile_id)
    if profile["status"] == "REJECTED":
        raise ValueError("cannot add samples to a rejected style profile")
    if any(sample.get("sample_role") != "external_verified_article" for sample in profile["samples"]):
        raise ValueError("research manuscripts and external author style sources must remain separate profiles")
    sample, sample_id, now = _external_style_sample(project_root, source_id), _id("STS"), utc_now()
    if re.sub(r"\s+", "", profile["owner_label"]).casefold() != re.sub(r"\s+", "", sample["author"]).casefold():
        raise ValueError("all external style samples must have the same HUMAN_VERIFIED author")
    if any(item.get("source_id") == source_id for item in profile["samples"]):
        raise ValueError("this external article is already part of the style profile")
    samples = profile["samples"] + [{
        "sample_id": sample_id, "manuscript_id": None, "sample_role": sample["sample_role"],
        "source_id": source_id, "source_version_id": sample["source_version_id"],
        "source_version_ids": sample["source_version_ids"], "sample_sha256": sample["sample_sha256"],
        "character_count": len(sample["content"]), "features": sample["features"], "created_at": now,
    }]
    aggregate = _aggregate_style_features(samples)
    status = "REVIEW_READY" if len(samples) >= 3 else ("RECURRING" if len(samples) >= 2 else "OBSERVED_ONCE")
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO style_profile_samples(sample_id, profile_id, manuscript_id,
               source_version_ids_json, sample_sha256, character_count, features_json, created_at,
               sample_role, source_id, source_version_id)
               VALUES (?, ?, NULL, ?, ?, ?, ?, ?, 'external_verified_article', ?, ?)""",
            (sample_id, profile_id, _json(sample["source_version_ids"]), sample["sample_sha256"],
             len(sample["content"]), _json(sample["features"]), now, source_id, sample["source_version_id"]),
        )
        connection.execute(
            """UPDATE style_profiles SET features_json = ?, status = ?, decided_by = NULL,
               decision_reason = NULL, decided_at = NULL WHERE profile_id = ?""",
            (_json(aggregate), status, profile_id),
        )
        append_audit(connection, "external_style_profile_sample_added", "style_profile", profile_id, {
            "source_id": source_id, "source_version_id": sample["source_version_id"],
            "sample_id": sample_id, "sample_count": len(samples),
        })
    return style_profile_detail(project_root, profile_id)


def decide_style_profile(project_root: Path, profile_id: str, approved: bool,
                         reviewer: str, reason: str) -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("reviewer and decision reason are required")
    profile = style_profile_detail(project_root, profile_id)
    if profile["status"] not in {"OBSERVED_ONCE", "RECURRING", "REVIEW_READY", "AUTHOR_APPROVED"}:
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
    result["minimum_sample_count"] = 3
    result["recommended_sample_count"] = 5
    result["sample_count_warning"] = (
        "建议补足至少 5 篇同一作者的已核全文论文" if len(result["samples"]) < 5 else "已达到建议样本数"
    )
    return result


def list_style_profiles(project_root: Path) -> list[dict[str, Any]]:
    with connect(project_root) as connection:
        ids = [row[0] for row in connection.execute("SELECT profile_id FROM style_profiles ORDER BY created_at DESC")]
    return [style_profile_detail(project_root, value) for value in ids]


def _validate_markers(content: str, markers: list[str], evidence_contract: dict[str, Any] | None = None) -> dict[str, Any]:
    missing = [marker for marker in markers if marker not in content]
    result: dict[str, Any] = {"valid": not missing, "missing_markers": missing}
    if evidence_contract and "evidence_ids" in evidence_contract:
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
    citation_contract = (evidence_contract or {}).get("citation_markers", [])
    required_historiography_entries = (
        (evidence_contract or {}).get("required_historiography_entries", {})
    )
    cited_markers = re.findall(r"\[CITE:([A-Za-z0-9_]+)@([A-Za-z0-9_:]+)\]", content)
    malformed_citations = re.findall(r"\[CITE:([^\]\r\n]*)\]", content)
    malformed_citations = [
        value for value in malformed_citations
        if not re.fullmatch(r"[A-Za-z0-9_]+@[A-Za-z0-9_:]+", value)
    ]
    if cited_markers or malformed_citations or citation_contract:
        allowed = set(citation_contract)
        invalid_citations = [f"[CITE:{source_id}@{page_id}]" for source_id, page_id in cited_markers
                             if f"[CITE:{source_id}@{page_id}]" not in allowed]
        result.update({
            "cited_historiography_markers": list(dict.fromkeys(
                f"[CITE:{source_id}@{page_id}]" for source_id, page_id in cited_markers
            )),
            "invalid_citation_markers": list(dict.fromkeys(invalid_citations)),
            "malformed_citation_markers": list(dict.fromkeys(malformed_citations)),
        })
        result["valid"] = bool(result["valid"] and not invalid_citations and not malformed_citations)
    if required_historiography_entries:
        cited_sources = {source_id for source_id, _page_id in cited_markers}
        missing_entry_ids = [
            entry_id for entry_id, source_ids in required_historiography_entries.items()
            if not cited_sources.intersection(source_ids)
        ]
        result.update({
            "required_historiography_entry_ids": list(required_historiography_entries),
            "missing_historiography_entry_ids": missing_entry_ids,
            "historiography_coverage_valid": not missing_entry_ids,
        })
        result["valid"] = bool(result["valid"] and not missing_entry_ids)
    return result


def _selected_historiography_context(project_root: Path, entry_ids: list[str],
                                      explicit_page_refs: list[str] | None) -> dict[str, Any]:
    selected_ids = list(dict.fromkeys(str(value).strip() for value in entry_ids if str(value).strip()))
    if not selected_ids:
        raise ValueError("historiography selection requires at least one entry id")
    with connect(project_root) as connection:
        placeholders = ",".join("?" for _ in selected_ids)
        rows = [dict(row) for row in connection.execute(
            f"SELECT * FROM historiography_entries WHERE entry_id IN ({placeholders})", selected_ids,
        )]
        by_id = {row["entry_id"]: row for row in rows}
        missing = [entry_id for entry_id in selected_ids if entry_id not in by_id]
        if missing:
            raise KeyError(f"unknown historiography entry: {missing[0]}")
        entries = [by_id[entry_id] for entry_id in selected_ids]
        unapproved = [row["entry_id"] for row in entries if str(row["status"]).lower() != "approved"]
        if unapproved:
            raise ValueError(f"historiography entry is not approved: {unapproved[0]}")
        for row in entries:
            row["source_refs"] = list(dict.fromkeys(json.loads(row["source_refs_json"])))
        source_ids = list(dict.fromkeys(
            source_id for row in entries for source_id in row["source_refs"]
        ))
        if not source_ids:
            raise ValueError("approved historiography entries must retain project source references")
        source_placeholders = ",".join("?" for _ in source_ids)
        source_rows = {
            row["source_id"]: dict(row) for row in connection.execute(
                f"""SELECT s.source_id, s.title, m.verification_status
                    FROM sources s LEFT JOIN source_citation_metadata m ON m.source_id = s.source_id
                    WHERE s.source_id IN ({source_placeholders})""", source_ids,
            )
        }
        absent_sources = [source_id for source_id in source_ids if source_id not in source_rows]
        if absent_sources:
            raise ValueError(f"historiography source does not belong to this project: {absent_sources[0]}")
        unverified_sources = [
            source_id for source_id in source_ids
            if source_rows[source_id].get("verification_status") != "HUMAN_VERIFIED"
        ]
        if unverified_sources:
            raise ValueError(f"historiography source bibliography is not HUMAN_VERIFIED: {unverified_sources[0]}")

        note_rows = [dict(row) for row in connection.execute(
            f"""SELECT note_id, source_id, page_refs_json, content, created_at
                FROM reading_notes WHERE source_id IN ({source_placeholders})
                  AND qualification = 'READING_NOTE_NOT_EVIDENCE'
                ORDER BY created_at DESC""", source_ids,
        )]
        notes_by_source: dict[str, list[dict[str, Any]]] = {source_id: [] for source_id in source_ids}
        for note in note_rows:
            if len(notes_by_source[note["source_id"]]) >= 2:
                continue
            note["page_refs"] = json.loads(note.pop("page_refs_json"))
            note["content"] = note["content"][:600]
            notes_by_source[note["source_id"]].append(note)

        requested_pairs: list[tuple[str, str]] = []
        if explicit_page_refs is not None:
            for value in explicit_page_refs:
                token = str(value).strip()
                match = re.fullmatch(r"(?:\[CITE:)?([A-Za-z0-9_]+)@([A-Za-z0-9_:]+)\]?", token)
                if not match:
                    raise ValueError(f"invalid historiography page ref: {token}")
                requested_pairs.append(match.groups())
        else:
            for source_id, notes in notes_by_source.items():
                page_ids = list(dict.fromkeys(
                    str(ref.get("page_id", "")) for note in notes for ref in note["page_refs"]
                    if str(ref.get("page_id", "")).strip()
                ))
                requested_pairs.extend((source_id, page_id) for page_id in page_ids[:5])
        requested_pairs = list(dict.fromkeys(requested_pairs))
        foreign_refs = [source_id for source_id, _ in requested_pairs if source_id not in source_ids]
        if foreign_refs:
            raise ValueError(f"historiography page ref is outside selected sources: {foreign_refs[0]}")
        page_rows = {
            (row["source_id"], row["page_id"]): dict(row) for row in connection.execute(
                f"""SELECT source_id, page_id, physical_page, printed_page, verification_state, use_state
                    FROM pages WHERE source_id IN ({source_placeholders})""", source_ids,
            )
        }
    allowed_pages: list[dict[str, Any]] = []
    verified_states = {"human_spot_checked", "human_verified", "human_repaired"}
    for pair in requested_pairs:
        page = page_rows.get(pair)
        if page is None:
            raise ValueError(f"historiography page ref does not exist: {pair[0]}@{pair[1]}")
        if page["use_state"] != "research_usable" or page["verification_state"] not in verified_states:
            raise ValueError(f"historiography page is not human-verified research usable: {pair[0]}@{pair[1]}")
        if not str(page["printed_page"] or "").strip():
            raise ValueError(f"historiography page has no printed_page: {pair[0]}@{pair[1]}")
        allowed_pages.append({
            **page, "marker": f"[CITE:{pair[0]}@{pair[1]}]",
            "source_title": source_rows[pair[0]]["title"],
        })
    missing_page_sources = [
        source_id for source_id in source_ids
        if not any(page["source_id"] == source_id for page in allowed_pages)
    ]
    if missing_page_sources:
        raise ValueError(
            "approved historiography source needs a verified reading-note page or explicit page ref: "
            + missing_page_sources[0]
        )
    return {
        "entry_ids": selected_ids, "entries": entries, "source_ids": source_ids,
        "entry_source_ids": {
            entry["entry_id"]: entry["source_refs"] for entry in entries
        },
        "reading_notes": [note for source_id in source_ids for note in notes_by_source[source_id]],
        "allowed_pages": allowed_pages,
        "citation_markers": [page["marker"] for page in allowed_pages],
    }


def _prose_risk_warnings(content: str) -> list[str]:
    """Flag research-process prose without treating a style warning as evidence failure."""
    return [name for name, pattern in INTERNAL_PROSE_PATTERNS.items() if pattern.search(content)]


def _requested_character_budget(instruction: str) -> tuple[int, int] | None:
    """Read an explicit Chinese-character budget from the author's instruction."""
    compact = instruction.replace(",", "").replace("，", "")
    match = re.search(r"(\d{3,5})\s*[—–~至到-]\s*(\d{3,5})\s*(?:个)?(?:中文)?(?:字|字符)", compact)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        return (min(low, high), max(low, high))
    match = re.search(r"(?:约|控制在|严格)?\s*(\d{3,5})\s*(?:个)?(?:中文)?(?:字|字符)", compact)
    if match:
        target = int(match.group(1))
        return (max(1, int(target * 0.8)), int(target * 1.2))
    return None


def _character_budget_is_strict(instruction: str) -> bool:
    """Only explicit hard wording lets a length preference override human approval."""
    budget_number = re.search(r"\d{3,5}", instruction)
    if budget_number is None:
        return False
    start = max(instruction.rfind(mark, 0, budget_number.start()) for mark in "。！？\n") + 1
    ends = [instruction.find(mark, budget_number.end()) for mark in "。！？\n"]
    end = min((value for value in ends if value >= 0), default=len(instruction))
    budget_clause = instruction[start:end]
    return bool(re.search(r"(?:严格|必须|务必|不得少于|不得超过|不多于|不少于)", budget_clause))


def _without_repeated_heading(content: str, heading: str) -> str:
    """Remove a model-echoed section heading before saving approved body text."""
    lines = content.lstrip().splitlines()
    if not lines:
        return content.strip()
    first = re.sub(r"^#{1,6}\s*", "", lines[0]).strip()
    if first == heading.strip():
        return "\n".join(lines[1:]).lstrip()
    return content.strip()


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
                            style_profile_id: str = "",
                            historiography_entry_ids: list[str] | None = None,
                            historiography_page_refs: list[str] | None = None,
                            attached_refs: list[dict[str, Any]] | None = None,
                            selection_only: bool = False, base_version_id: str = "",
                            selection: dict[str, Any] | None = None) -> dict[str, Any]:
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
    selection_context = None
    supplemental_freeze: dict[str, Any] | None = None
    supplemental_evidence: dict[str, dict[str, Any]] = {}
    if selection_only:
        if operation != "polish":
            raise ValueError("selection-only revision currently supports evidence-preserving polish only")
        selection_context = _validated_writing_selection(
            base_content, str(row["current_version_id"]), base_version_id, selection,
        )
        supplement_requested = bool(freeze_id.strip() or evidence_ids)
        if supplement_requested:
            supplemental_freeze, supplemental_evidence = _approved_freeze_evidence_scope(
                project_root, freeze_id, evidence_ids,
            )
            if historiography_entry_ids:
                raise ValueError("selection evidence supplement cannot be combined with historiography context")
            evidence_refs = [
                {
                    "evidence_id": evidence_id,
                    "page_id": evidence.get("page_id", ""),
                    "source_version_id": evidence.get("source_version_id", ""),
                }
                for evidence_id, evidence in supplemental_evidence.items()
            ]
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
            "6. 后台的冻结、核验、门禁、事件表和补证状态只约束取材，不得写进论文。谨慎通过来源归属、"
            "时间范围和限定词自然体现；避免连续使用‘不能、不得、不等于、并非’作预防性辩护。"
            "先写人物在具体时间地点的行动及材料差异，再形成有限判断。\n"
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
            "摘要只概括历史问题、时段、主要材料、历史过程和结论；不要报告事件条数、证据门禁、冻结状态、"
            "待补证清单或审计结果，也不要用连续否定句预先回应内部研究风险。\n"
            f"具体要求：{instruction}\n\n已批准正文：\n{body}"
        )
        fallback = base_content
    elif operation == "historical_humanize":
        evidence_contract = None
        selected_skill = get_skill(skill_name or "historical-humanizer-zh")
        profile = None
        if style_profile_id:
            profile = style_profile_detail(project_root, style_profile_id)
            if profile["status"] != "STABLE_PROFILE" or len(profile["samples"]) < 3:
                raise ValueError("style profile must be author approved with at least three samples before use")
        style_context = _json(profile["features"]) if profile else "未选择作者画像；只使用通用史学表达规则"
        prompt = (
            "对以下中文历史学段落制作证据保真的语言修订副本。只返回修订正文。\n"
            "硬约束：不得改变事实、归因、因果、时间顺序、论证范围、限定词、阴性结果；不得改变引文、译文、"
            "脚注、页码、档号、专名、数字、术语、URL；不得增加第一人称、情绪、反问或模仿具体学者。\n"
            "表达操作：让材料和行动者先于抽象概念，叙事与分析交替，删除内部流程语言和重复总结；"
            "除非作者明确要求压缩，不得删减史料叙述、历史过程或有证据支撑的分析。证据足以支持时应明确下判断，"
            "不得用成串否定和预防性辩解代替论断；真正的史料限度只在相关判断处简洁交代，不另写流程说明。"
            "无法确定为纯语言变化时保留原句。\n"
            f"技能：{selected_skill['name']} / SHA-256 {selected_skill['sha256']}。\n"
            f"经批准的高层文风画像：{style_context}\n具体要求：{instruction}\n\n{base_content}"
        )
        fallback = base_content
    else:
        evidence_contract = (
            {
                "selection_supplement": {
                    "freeze_id": supplemental_freeze["freeze_id"],
                    "evidence_ids": list(supplemental_evidence),
                    "evidence_fingerprint": _frozen_evidence_fingerprint(supplemental_evidence),
                }
            }
            if supplemental_freeze else None
        )
        writing_input = selection_context["text"] if selection_context else base_content
        if selection_context and selection_context["kind"] == "table":
            scope_rule = (
                "你只会看到作者完整选择的一张 Markdown 表。只返回一张完整 Markdown 表，不要代码围栏、"
                "标题、说明或前后文；必须保留表头、分隔行和至少一行数据，并保持各行列数一致。"
            )
        else:
            scope_rule = (
                "你只会看到作者选中的连续段落。只返回用于替换该选区的文字，不要返回整节、标题、说明或前后文。"
                if selection_context else "只返回修改后正文。"
            )
        if supplemental_freeze:
            evidence_text = "\n".join(
                f"- [EVID:{evidence_id}]｜关系 {evidence.get('relation', '')}｜物理页 "
                f"{'–'.join(str(page) for page in evidence.get('physical_pages', [evidence.get('physical_page', '')]))}"
                f"｜原文：{evidence.get('quote', '')}"
                for evidence_id, evidence in supplemental_evidence.items()
            )
            if selection_context["kind"] == "table":
                supplement_scope = (
                    "返修下列中文历史学论文中的完整 Markdown 表。模型只获得当前完整表格和作者选择的已批准冻结证据。"
                    "必须保留表内原有事实、数字、脚注与 EVID/CITE 标识；除表内已有事实外，只能新增冻结证据原文直接支持的事实。"
                    "每项新增事实必须在同一单元格附对应 [EVID:证据编号]。"
                )
                input_label = "当前完整表格"
            else:
                supplement_scope = (
                    "返修下列中文历史学论文选区。模型只获得当前选区和作者选择的已批准冻结证据。"
                    "必须保留选区内原有事实、数字、脚注与 EVID/CITE 标识；除选区内已有事实外，只能新增冻结证据原文直接支持的事实。"
                    "每项新增事实必须在同一句附对应 [EVID:证据编号]。"
                )
                input_label = "当前选区"
            prompt = (
                supplement_scope
                + "只能新增下列证据编号，且必须至少新增其中一个 [EVID:证据编号]。"
                "不得从证据推演未记载的原因、规模、连续性或影响；如使用直接引文，必须逐字复制证据原文。"
                f"{scope_rule}具体要求：{instruction}\n\n{input_label}：\n{writing_input}"
                f"\n\n允许补充的冻结证据：\n{evidence_text}"
            )
        else:
            prompt = (
                "润色以下中文历史学论文段落。不得新增、删除或强化事实，不得改变引文、数字、脚注标记和来源标识。"
                "除非作者明确要求压缩，不得以精简、概括或合并为目标，不得降低材料密度或删去有助于讲清历史过程的叙述。"
                "行文先交代人物、行动、时间、地点和材料，再据此作出判断；证据能够支持的判断应直接、肯定地写出，"
                "不要改写成连续的‘并非’‘不能’‘不足以’等预防性辩解。真正的史料限度应紧邻相关判断简洁说明，"
                "不得另写研究流程、材料分流、门禁、核验状态、统计口径或面向评审的自我辩护。"
                f"{scope_rule}具体要求：{instruction}\n\n{writing_input}"
            )
        fallback = re.sub(r"[ \t]+", " ", writing_input).replace(" ,", "，").replace(" .", "。")
    historiography_context = None
    if historiography_entry_ids:
        if historiography_page_refs is None and attached_refs:
            historiography_page_refs = [
                f"{value.get('source_id', '')}@{value.get('page_id', '')}"
                for value in attached_refs
                if value.get("kind") == "source_page" and value.get("source_id") and value.get("page_id")
            ] or None
        historiography_context = _selected_historiography_context(
            project_root, historiography_entry_ids, historiography_page_refs,
        )
        entry_text = "\n".join(
            f"- {entry['entry_id']}｜《{entry['work_title']}》｜立场：{entry['position']}｜"
            f"贡献：{entry['contribution']}｜限制：{entry['limitation']}｜与本文关系：{entry['relevance']}"
            for entry in historiography_context["entries"]
        )
        note_text = "\n".join(
            f"- {note['source_id']}｜阅读札记（仅作解释线索，不是证据）：{note['content']}"
            for note in historiography_context["reading_notes"]
        ) or "- 未附加阅读札记摘要。"
        citation_text = "\n".join(
            f"- {page['marker']}｜{page['source_title']}｜原书页 {page['printed_page']}"
            for page in historiography_context["allowed_pages"]
        )
        prompt += (
            "\n\n人工选用的学术史材料：\n" + entry_text
            + "\n\n有界阅读札记摘要：\n" + note_text
            + "\n\n允许的直接学术史引证白名单：\n" + citation_text
            + "\n只能在确实使用相应观点时原样附上上述 [CITE:来源@页面] 标识；不得输出任何其他 CITE，"
              "每个明确选用的学术史条目都必须至少使用其对应来源的一条白名单 CITE；同一条目无须穷尽所有允许页面。"
              "不得把阅读札记当作史料证据，也不得因为材料已收藏或读过就自动写入正文或参考文献。"
        )
        if selection_context:
            prompt += (
                "\n这是选区返修：不得为了满足学术史覆盖向选区新增原来没有的 CITE；"
                "选区外正文将由程序原样回填，最终仍按完整章节检查学术史覆盖。"
            )
        evidence_contract = dict(evidence_contract or {})
        evidence_contract["citation_markers"] = historiography_context["citation_markers"]
        evidence_contract["required_historiography_entries"] = historiography_context["entry_source_ids"]
    if selection_context:
        existing_citations = re.findall(r"\[CITE:[A-Za-z0-9_]+@[A-Za-z0-9_:]+\]", base_content)
        if existing_citations:
            evidence_contract = dict(evidence_contract or {})
            evidence_contract["citation_markers"] = list(dict.fromkeys(
                [*(evidence_contract.get("citation_markers") or []), *existing_citations]
            ))
    model_output = (writer(prompt) if writer else (_model_write(prompt) if _model_capability()["available"] else fallback)).strip()
    proposed = (
        base_content[:selection_context["start"]] + model_output + base_content[selection_context["end"]:]
        if selection_context else model_output
    ).strip()
    validation = _validate_markers(proposed, markers, evidence_contract)
    if operation == "polish":
        validation["no_change"] = proposed == base_content.strip()
        validation["valid"] = bool(validation["valid"] and not validation["no_change"])
    if selection_context:
        replacement_prose = re.sub(
            r"\[(?:EVID|CITE):[^\]\r\n]+\]|\[\^[^\]\r\n]+\]", "", model_output,
        )
        replacement_warnings = _prose_risk_warnings(replacement_prose)
        missing_selection_markers = [
            marker for marker in _markers(selection_context["text"]) if marker not in model_output
        ]
        table_structure_valid = (
            selection_context["kind"] != "table" or _is_complete_markdown_table(model_output)
        )
        validation.update({
            "selection_only": True,
            "selection_internal_process": "internal_process" in replacement_warnings,
            "selection_missing_markers": missing_selection_markers,
            "selection_kind": selection_context["kind"],
            "table_structure_valid": table_structure_valid,
            "replacement_character_count": len(model_output),
        })
        validation["valid"] = bool(
            validation["valid"] and not validation["selection_internal_process"]
            and not missing_selection_markers and table_structure_valid
        )
        if supplemental_evidence:
            supplement_validation = _selection_evidence_supplement_validation(
                selection_context["text"], model_output, supplemental_evidence,
            )
            validation.update(supplement_validation)
            validation["valid"] = bool(
                validation["valid"] and supplement_validation["supplemental_evidence_valid"]
            )
    if validation.get("invalid_citation_markers") or validation.get("malformed_citation_markers"):
        invalid = validation.get("invalid_citation_markers") or validation.get("malformed_citation_markers")
        raise ValueError("writing model returned a CITE outside the approved historiography whitelist: " + invalid[0])
    validation["prose_risk_warnings"] = _prose_risk_warnings(proposed)
    budget = _requested_character_budget(instruction)
    if budget:
        validation["requested_character_budget"] = {"min": budget[0], "max": budget[1]}
        validation["actual_character_count"] = len(model_output) if selection_context else len(proposed)
        validation["character_budget_status"] = (
            "PASS" if budget[0] <= validation["actual_character_count"] <= budget[1] else "OUT_OF_RANGE"
        )
        validation["character_budget_enforcement"] = (
            "STRICT" if _character_budget_is_strict(instruction) else "ADVISORY"
        )
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
        "historiography_context": historiography_context,
        "selection": selection_context,
    }
    if selection_context:
        with connect(project_root) as connection:
            latest = connection.execute(
                "SELECT current_version_id FROM manuscript_sections WHERE section_id = ?", (section_id,),
            ).fetchone()
        if latest is None or latest["current_version_id"] != row["current_version_id"]:
            raise ValueError("selected section version changed while the model was writing; select the text again")
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
    if approved and proposal["model_snapshot"].get("selection"):
        with connect(project_root) as connection:
            current = connection.execute(
                "SELECT current_version_id FROM manuscript_sections WHERE section_id = ?",
                (proposal["section_id"],),
            ).fetchone()
        if current is None or current["current_version_id"] != proposal["base_version_id"]:
            raise ValueError("writing proposal is based on a stale section version; create a new selection proposal")
    with connect(project_root) as connection:
        heading_row = connection.execute(
            "SELECT heading FROM manuscript_sections WHERE section_id = ?", (proposal["section_id"],)
        ).fetchone()
    if heading_row is not None:
        final_content = _without_repeated_heading(final_content, heading_row["heading"])
    budget_content = final_content
    contract = proposal["model_snapshot"].get("evidence_contract")
    supplemental_evidence: dict[str, dict[str, Any]] = {}
    supplemental_contract = (contract or {}).get("selection_supplement")
    if approved and supplemental_contract:
        _freeze, supplemental_evidence = _approved_freeze_evidence_scope(
            project_root,
            str(supplemental_contract.get("freeze_id", "")),
            [str(value) for value in supplemental_contract.get("evidence_ids", [])],
        )
        if _frozen_evidence_fingerprint(supplemental_evidence) != supplemental_contract.get("evidence_fingerprint"):
            raise ValueError("approved evidence freeze changed after proposal generation; create a new proposal")
    validation = _validate_markers(final_content, proposal["protected_markers"], contract)
    if proposal["operation"] == "polish":
        with connect(project_root) as connection:
            base_row = connection.execute(
                "SELECT content FROM section_versions WHERE version_id = ?",
                (proposal["base_version_id"],),
            ).fetchone()
        selection = proposal["model_snapshot"].get("selection")
        if selection and base_row is not None:
            base_text = str(base_row["content"])
            start, end = int(selection["start"]), int(selection["end"])
            prefix, suffix = base_text[:start], base_text[end:]
            if not final_content.startswith(prefix) or (suffix and not final_content.endswith(suffix)):
                raise ValueError("selection-only approval changed text outside the selected passage")
            replacement_end = len(final_content) - len(suffix) if suffix else len(final_content)
            replacement = final_content[len(prefix):replacement_end]
            budget_content = replacement
            replacement_prose = re.sub(
                r"\[(?:EVID|CITE):[^\]\r\n]+\]|\[\^[^\]\r\n]+\]", "", replacement,
            )
            missing_selection_markers = [
                marker for marker in _markers(str(selection["text"])) if marker not in replacement
            ]
            table_structure_valid = (
                selection.get("kind", "text") != "table" or _is_complete_markdown_table(replacement)
            )
            validation.update({
                "selection_only": True,
                "selection_kind": selection.get("kind", "text"),
                "selection_internal_process": "internal_process" in _prose_risk_warnings(replacement_prose),
                "selection_missing_markers": missing_selection_markers,
                "table_structure_valid": table_structure_valid,
                "replacement_character_count": len(replacement),
            })
            validation["valid"] = bool(
                validation["valid"] and not validation["selection_internal_process"]
                and not missing_selection_markers and table_structure_valid
            )
            if supplemental_evidence:
                supplement_validation = _selection_evidence_supplement_validation(
                    str(selection["text"]), replacement, supplemental_evidence,
                )
                validation.update(supplement_validation)
                validation["valid"] = bool(
                    validation["valid"] and supplement_validation["supplemental_evidence_valid"]
                )
        validation["no_change"] = bool(
            base_row is not None and final_content == str(base_row["content"]).strip()
        )
        validation["valid"] = bool(validation["valid"] and not validation["no_change"])
    validation["decision_reason"] = reason
    prose_for_approval = re.sub(r"\[(?:EVID|CITE):[^\]]+\]", "", final_content)
    validation["prose_risk_warnings"] = _prose_risk_warnings(prose_for_approval)
    budget = _requested_character_budget(proposal["instruction"])
    if budget:
        validation["requested_character_budget"] = {"min": budget[0], "max": budget[1]}
        validation["actual_character_count"] = len(budget_content)
        validation["character_budget_status"] = (
            "PASS" if budget[0] <= len(budget_content) <= budget[1] else "OUT_OF_RANGE"
        )
        validation["character_budget_enforcement"] = (
            "STRICT" if _character_budget_is_strict(proposal["instruction"]) else "ADVISORY"
        )
    if approved and not validation["valid"]:
        if validation.get("selection_internal_process"):
            raise ValueError("writing proposal still contains research-process prose: internal_process")
        if validation["missing_markers"]:
            raise ValueError("writing proposal removed protected markers: " + ", ".join(validation["missing_markers"]))
        raise ValueError("writing proposal violates its evidence contract")
    blocking_prose = [
        warning for warning in validation["prose_risk_warnings"]
        if warning == "internal_process"
    ]
    if approved and blocking_prose:
        raise ValueError(
            "writing proposal still contains research-process prose: "
            + ", ".join(blocking_prose)
        )
    if (approved and validation.get("character_budget_status") == "OUT_OF_RANGE"
            and validation.get("character_budget_enforcement") == "STRICT"):
        requested = validation["requested_character_budget"]
        raise ValueError(
            f"writing proposal is outside the requested character budget "
            f"({validation['actual_character_count']} not in {requested['min']}–{requested['max']})"
        )
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


def _reading_source_identity(connection: Any, source_id: str) -> dict[str, str]:
    row = connection.execute(
        """SELECT s.source_id, s.title AS project_title, s.original_name,
                  COALESCE(m.title, '') AS citation_title,
                  COALESCE(m.author, '') AS canonical_author,
                  COALESCE(m.verification_status, 'UNVERIFIED') AS citation_verification_status
           FROM sources s LEFT JOIN source_citation_metadata m ON m.source_id = s.source_id
           WHERE s.source_id = ?""",
        (source_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown source: {source_id}")
    canonical_title = (
        str(row["citation_title"]).strip()
        if row["citation_verification_status"] == "HUMAN_VERIFIED"
        and str(row["citation_title"]).strip()
        else str(row["project_title"]).strip()
    )
    return {
        "source_id": str(row["source_id"]),
        "canonical_title": canonical_title,
        "canonical_author": str(row["canonical_author"]).strip(),
        "original_name": str(row["original_name"]),
        "citation_verification_status": str(row["citation_verification_status"]),
    }


def _normalized_title(value: str) -> str:
    return re.sub(
        r"[\W_]+", "", unicodedata.normalize("NFKC", value), flags=re.UNICODE,
    ).casefold()


def _historiography_title_segments(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value)
    return [
        match.group(1).strip()
        for match in re.finditer(r"[《〈](.+?)[》〉]", normalized)
        if match.group(1).strip()
    ]


def _historiography_declared_author(work_title: str, canonical_title: str) -> str:
    """Return an author field only when the supplied value visibly declares one."""
    normalized = unicodedata.normalize("NFKC", work_title).strip()
    canonical_title = unicodedata.normalize("NFKC", canonical_title)
    explicit = re.search(
        r"(?:作者|责任者)\s*[:：]\s*([^,，。；;:：]+)", normalized,
        flags=re.I,
    )
    if explicit:
        return explicit.group(1).strip()

    title_match = re.search(re.escape(canonical_title), normalized, flags=re.I)
    if title_match is None:
        return ""
    prefix = normalized[:title_match.start()]
    prefix = re.sub(r"^\s*\[?\d+\]?\s*", "", prefix)
    prefix = re.sub(r"^\s*(?:18|19|20)\d{2}(?:年)?[\s._-]*", "", prefix)
    prefix = prefix.strip(" \t\r\n_,，.。：:;；-—《〈[（(")
    if not prefix or len(prefix) > 80:
        return ""
    # A title introduced as a quoted object (for example, “评《某书》”) is not
    # a bibliographic author declaration. It must not unlock substring matching.
    if prefix in {"评", "读", "论", "关于", "再论"}:
        return ""
    return prefix


def _verified_historiography_title_matches(work_title: str,
                                            identity: dict[str, str]) -> bool:
    supplied = _normalized_title(work_title)
    canonical = _normalized_title(identity["canonical_title"])
    if supplied == canonical:
        return True

    title_segments = _historiography_title_segments(work_title)
    exact_quoted_title = any(
        _normalized_title(segment) == canonical
        for segment in title_segments
    )
    normalized_work_title = unicodedata.normalize("NFKC", work_title)
    review_wrapper = re.search(
        rf"(?:^|[\s:：,，.。;；])(?:评|读|关于|论|再论)\s*[《〈]"
        rf"\s*{re.escape(unicodedata.normalize('NFKC', identity['canonical_title']))}\s*[》〉]",
        normalized_work_title,
    ) is not None
    declared_author = _historiography_declared_author(
        work_title, identity["canonical_title"],
    )
    canonical_author = _normalized_title(identity["canonical_author"])
    if declared_author and canonical_author:
        supplied_author = _normalized_title(declared_author)
        if supplied_author != canonical_author:
            raise ValueError(
                "historiography work author does not match HUMAN_VERIFIED bibliography: "
                + _json({
                    "source_id": identity["source_id"],
                    "canonical_author": identity["canonical_author"],
                    "supplied_author": declared_author,
                })
            )

    if title_segments and not exact_quoted_title:
        return False
    if exact_quoted_title and not review_wrapper and canonical_author in supplied:
        return True
    citation_segments = [
        _normalized_title(segment)
        for segment in re.split(r"[,，.。;；:：\[\]()（）]+", normalized_work_title)
        if segment.strip()
    ]
    if canonical_author in supplied and canonical in citation_segments:
        return True
    if supplied.endswith(canonical):
        prefix = supplied[:-len(canonical)]
        return bool(re.fullmatch(r"(?:18|19|20)\d{2}年?", prefix))
    return False


def _declared_reading_note_titles(content: str) -> list[str]:
    # Only inspect explicit identity labels. A note may legitimately discuss or
    # compare other named works in its analytical prose.
    pattern = re.compile(
        r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(?:来源(?:题名)?|文献(?:题名)?|作品(?:题名)?|"
        r"阅读对象|札记对象|题名|书名|source(?:_|\s+)title)(?:\*\*)?\s*[:：]\s*(.+?)\s*$"
    )
    return [
        match.group(1).strip().strip("`*_# 《》“”\"'")
        for match in pattern.finditer(content)
        if match.group(1).strip()
    ]


def _declared_reading_note_authors(content: str) -> list[str]:
    pattern = re.compile(
        r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(?:来源作者|文献作者|作品作者|责任者|"
        r"source(?:_|\s+)author)(?:\*\*)?\s*[:：]\s*(.+?)\s*$"
    )
    return [
        match.group(1).strip().strip("`*_# 《》“”\"'")
        for match in pattern.finditer(content)
        if match.group(1).strip()
    ]


def _reading_note_identity_mismatches(content: str, identity: dict[str, str]) -> list[str]:
    canonical = _normalized_title(identity["canonical_title"])
    mismatches = []
    for declared in _declared_reading_note_titles(content):
        normalized = _normalized_title(declared)
        if normalized and canonical not in normalized and normalized not in canonical:
            mismatches.append(f"title={declared}")
    canonical_author = _normalized_title(identity["canonical_author"])
    if canonical_author:
        for declared in _declared_reading_note_authors(content):
            normalized = _normalized_title(declared)
            if normalized and canonical_author not in normalized and normalized not in canonical_author:
                mismatches.append(f"author={declared}")
    return mismatches


def _source_page_choices(connection: Any, source_id: str) -> dict[str, list[int]]:
    rows = connection.execute(
        "SELECT physical_page, use_state FROM pages WHERE source_id = ? ORDER BY physical_page",
        (source_id,),
    ).fetchall()
    return {
        "savable_physical_pages": [
            int(row["physical_page"]) for row in rows if row["use_state"] == "research_usable"
        ],
        "blocked_or_unusable_physical_pages": [
            int(row["physical_page"]) for row in rows if row["use_state"] != "research_usable"
        ],
    }


def _reading_identity_header(identity: dict[str, str]) -> str:
    author = f"｜canonical_author={identity['canonical_author']}" if identity["canonical_author"] else ""
    return (
        f"[来源身份｜source_id={identity['source_id']}｜"
        f"canonical_title=《{identity['canonical_title']}》{author}]"
    )


def create_reading_job(project_root: Path, title: str, question: str, mode: str,
                       source_ids: list[str], stop_condition: str) -> dict[str, Any]:
    if mode not in {"metadata", "targeted", "full"}:
        raise ValueError("reading mode must be metadata, targeted or full")
    if not title.strip() or not question.strip() or not source_ids or not stop_condition.strip():
        raise ValueError("reading job requires title, question, sources and stop condition")
    job_id, now = _id("RDJ"), utc_now()
    with connect(project_root) as connection:
        source_identities = [_reading_source_identity(connection, source_id) for source_id in source_ids]
        connection.execute(
            "INSERT INTO reading_jobs(job_id, title, question, mode, source_ids_json, stop_condition, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)",
            (job_id, title.strip(), question.strip(), mode, _json(source_ids), stop_condition.strip(), now),
        )
    return {"job_id": job_id, "title": title, "question": question, "mode": mode,
            "source_ids": source_ids, "source_identities": source_identities,
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
        source_identity = _reading_source_identity(connection, source_id)
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
        page_choices = _source_page_choices(connection, source_id)
        last_page = pages[-1]["physical_page"] if pages else after_physical_page
        has_more = connection.execute(
            """SELECT 1 FROM pages WHERE source_id = ? AND physical_page > ?
               AND use_state = 'research_usable' LIMIT 1""", (source_id, last_page),
        ).fetchone() is not None
    return {
        "job_id": job_id, "source_id": source_id, "source_identity": source_identity,
        "canonical_title": source_identity["canonical_title"], "mode": job["mode"],
        "question": job["question"], "stop_condition": job["stop_condition"],
        "pages": pages, "next_after_physical_page": last_page, "has_more": has_more,
        "total_pages": total_pages, "usable_pages": usable_pages,
        "blocked_or_unusable_pages": total_pages - usable_pages,
        **page_choices,
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
        source_identity = _reading_source_identity(connection, source_id)
        page_choices = _source_page_choices(connection, source_id)
        mismatches = _reading_note_identity_mismatches(content, source_identity)
        if mismatches:
            raise ValueError(
                "reading note source identity mismatch: "
                + _json({
                    "source_identity": source_identity,
                    "declared_titles": mismatches,
                    **page_choices,
                    "correction": "remove the handwritten source identity and save analysis only",
                })
            )
        placeholders = ",".join("?" for _ in pages)
        page_rows = connection.execute(
            f"""SELECT page_id, physical_page FROM pages
                WHERE source_id = ? AND physical_page IN ({placeholders})
                  AND use_state = 'research_usable' ORDER BY physical_page""",
            (source_id, *pages),
        ).fetchall()
        if [row["physical_page"] for row in page_rows] != pages:
            raise ValueError(
                "reading note pages must all be research usable: "
                + _json({"source_identity": source_identity, "requested_physical_pages": pages,
                         **page_choices})
            )
        version_rows = connection.execute(
            """SELECT source_version_id FROM source_versions
               WHERE source_id = ? ORDER BY created_at, source_version_id""",
            (source_id,),
        ).fetchall()
        if len(version_rows) != 1:
            raise ValueError("reading note requires one exact source version")
        source_version_id = str(version_rows[0]["source_version_id"])
        refs = []
        for page in page_rows:
            block = connection.execute(
                """SELECT block_id FROM blocks WHERE page_id = ? AND use_state = 'research_usable'
                   ORDER BY block_order, block_id LIMIT 1""", (page["page_id"],),
            ).fetchone()
            if block is None:
                raise ValueError(
                    f"reading note page has no representative research-usable block: {page['page_id']}"
                )
            refs.append({
                "source_version_id": source_version_id,
                "page_id": page["page_id"],
                "physical_page": page["physical_page"],
                "block_id": block["block_id"],
            })
        note_id, now = _id("RDN"), utc_now()
        connection.execute(
            """INSERT INTO reading_notes(note_id, job_id, source_id, page_refs_json, content,
               qualification, created_at) VALUES (?, ?, ?, ?, ?, 'READING_NOTE_NOT_EVIDENCE', ?)""",
            (note_id, job_id, source_id, _json(refs),
             _reading_identity_header(source_identity) + "\n\n" + content.strip(), now),
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
            "source_identity": source_identity, "canonical_title": source_identity["canonical_title"],
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
                note["page_refs"] = json.loads(note.pop("page_refs_json"))
    return jobs


def _validate_historiography_sources(connection: Any, work_title: str,
                                      source_refs: list[str]) -> str:
    identities = [_reading_source_identity(connection, source_id) for source_id in source_refs]
    canonical_titles = list(dict.fromkeys(identity["canonical_title"] for identity in identities))
    if len({_normalized_title(title) for title in canonical_titles}) != 1:
        raise ValueError("one historiography entry cannot represent multiple source titles")
    canonical_title = canonical_titles[0]
    verified = all(
        identity["citation_verification_status"] == "HUMAN_VERIFIED"
        for identity in identities
    )
    title_matches = (
        all(_verified_historiography_title_matches(work_title, identity)
            for identity in identities)
        if verified
        else _normalized_title(work_title) == _normalized_title(canonical_title)
    )
    if not title_matches:
        raise ValueError(
            "historiography work title does not match its bound source: "
            + _json({"source_id": source_refs[0], "canonical_title": canonical_title,
                     "canonical_author": identities[0]["canonical_author"] if verified else "",
                     "supplied_work_title": work_title,
                     "citation_verification_status": identities[0]["citation_verification_status"]})
        )
    for identity in identities:
        notes = connection.execute(
            """SELECT note_id, content, qualification FROM reading_notes
               WHERE source_id = ? ORDER BY created_at""",
            (identity["source_id"],),
        ).fetchall()
        eligible = 0
        for note in notes:
            mismatches = _reading_note_identity_mismatches(str(note["content"]), identity)
            if mismatches:
                connection.execute(
                    "UPDATE reading_notes SET qualification = ? WHERE note_id = ?",
                    ("QUARANTINED_SOURCE_IDENTITY_MISMATCH", note["note_id"]),
                )
            elif note["qualification"] == "READING_NOTE_NOT_EVIDENCE":
                eligible += 1
        if not eligible:
            raise ValueError(
                "historiography source has no identity-consistent reading note: "
                + _json({"source_identity": identity})
            )
    return canonical_title


def validate_historiography_entry_payload(project_root: Path,
                                           payload: dict[str, Any]) -> dict[str, Any]:
    source_refs = list(dict.fromkeys(
        str(value).strip() for value in payload.get("source_refs", []) if str(value).strip()
    ))
    if not source_refs:
        raise ValueError("historiography entry requires project source references")
    with connect(project_root) as connection:
        canonical_title = _validate_historiography_sources(
            connection, str(payload.get("work_title", "")).strip(), source_refs,
        )
    return {**payload, "work_title": canonical_title, "source_refs": source_refs}


def create_historiography_entry(project_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    required = ("work_title", "position", "contribution", "limitation", "relevance")
    if any(not str(payload.get(key, "")).strip() for key in required) or not payload.get("source_refs"):
        raise ValueError("historiography entry requires all fields and source references")
    payload = validate_historiography_entry_payload(project_root, payload)
    source_refs = list(dict.fromkeys(str(value).strip() for value in payload["source_refs"]
                                    if str(value).strip()))
    if not source_refs:
        raise ValueError("historiography entry requires project source references")
    entry_id, now = _id("HIS"), utc_now()
    with connect(project_root) as connection:
        connection.execute(
            """INSERT INTO historiography_entries(entry_id, work_title, position, contribution,
               limitation, relevance, source_refs_json, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?)""",
            (entry_id, str(payload["work_title"]).strip(),
             *(str(payload[key]).strip() for key in required[1:]), _json(source_refs), now),
        )
    return {"entry_id": entry_id, "work_title": str(payload["work_title"]).strip(),
            **{key: str(payload[key]).strip() for key in required[1:]},
            "source_refs": source_refs, "status": "candidate", "created_at": now}


def decide_historiography_entry(project_root: Path, entry_id: str, approved: bool,
                                 reviewer: str, reason: str) -> dict[str, Any]:
    reviewer, reason = reviewer.strip(), reason.strip()
    if not reviewer or not reason:
        raise ValueError("reviewer and decision reason are required")
    now = utc_now()
    with connect(project_root) as connection:
        row = connection.execute(
            "SELECT * FROM historiography_entries WHERE entry_id = ?", (entry_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown historiography entry: {entry_id}")
        if row["status"] != "candidate":
            raise ValueError(f"historiography entry is already {row['status']}")
        source_refs = json.loads(row["source_refs_json"])
        if approved:
            _validate_historiography_sources(connection, str(row["work_title"]), source_refs)
        status = "approved" if approved else "rejected"
        connection.execute(
            "UPDATE historiography_entries SET status = ? WHERE entry_id = ? AND status = 'candidate'",
            (status, entry_id),
        )
        append_audit(connection, "historiography_entry_decided", "historiography_entry", entry_id, {
            "approved": approved, "status": status, "reviewer": reviewer, "reason": reason,
        })
        result = dict(row)
    result["source_refs"] = json.loads(result.pop("source_refs_json"))
    result["status"] = status
    result["decision"] = {
        "approved": approved, "reviewer": reviewer, "reason": reason, "decided_at": now,
    }
    return result


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


def _manuscript_coverage_receipt(project_root: Path, manuscript_text: str) -> dict[str, Any]:
    cited_sources = set(re.findall(r"\[CITE:([A-Za-z0-9_]+)@[A-Za-z0-9_:]+\]", manuscript_text))
    cited_evidence_ids = set(re.findall(r"\[EVID:([A-Za-z0-9_]+)\]", manuscript_text))
    with connect(project_root) as connection:
        source_rows = [dict(row) for row in connection.execute(
            "SELECT source_id, title FROM sources ORDER BY created_at"
        )]
        read_sources = {
            row[0] for row in connection.execute("SELECT DISTINCT source_id FROM reading_notes")
        }
        historiography_sources: set[str] = set()
        for row in connection.execute("SELECT source_refs_json FROM historiography_entries"):
            historiography_sources.update(json.loads(row[0]))
        if cited_evidence_ids:
            placeholders = ",".join("?" for _ in cited_evidence_ids)
            cited_sources.update(
                row[0] for row in connection.execute(
                    f"SELECT DISTINCT source_id FROM evidence_items WHERE evidence_id IN ({placeholders})",
                    list(cited_evidence_ids),
                )
            )
    source_titles = {row["source_id"]: row["title"] for row in source_rows}
    unused_direct = sorted((read_sources & historiography_sources) - cited_sources)
    return {
        "project_source_count": len(source_rows),
        "read_source_count": len(read_sources),
        "historiography_source_count": len(historiography_sources),
        "manuscript_cited_source_count": len(cited_sources),
        "read_but_unused_direct_research": [
            {"source_id": source_id, "title": source_titles.get(source_id, source_id)}
            for source_id in unused_direct
        ],
        "warning": (
            "覆盖回执只提示材料使用分布，不设置数量阈值；收藏、读过或进入学术史条目均不自动成为正文引文或参考文献。"
        ),
    }


def _review_citation_context(project_root: Path,
                             cited_pages: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """Describe only CITE pages that actually occur in the manuscript under review."""
    if not cited_pages:
        return []
    source_ids = sorted({source_id for source_id, _page_id in cited_pages})
    placeholders = ",".join("?" for _ in source_ids)
    verified_states = {"human_spot_checked", "human_verified", "human_repaired"}
    with connect(project_root) as connection:
        source_rows = {
            row["source_id"]: dict(row) for row in connection.execute(
                f"""SELECT s.source_id, s.title AS project_title,
                           COALESCE(m.author, '') AS author,
                           COALESCE(m.title, '') AS citation_title,
                           COALESCE(m.year, '') AS year,
                           COALESCE(m.verification_status, 'UNVERIFIED') AS bibliography_status
                    FROM sources s LEFT JOIN source_citation_metadata m ON m.source_id = s.source_id
                    WHERE s.source_id IN ({placeholders})""", source_ids,
            )
        }
        page_rows = {
            (row["source_id"], row["page_id"]): dict(row)
            for row in connection.execute(
                f"""SELECT source_id, page_id, physical_page, printed_page,
                           verification_state, use_state
                    FROM pages WHERE source_id IN ({placeholders})""", source_ids,
            )
        }
        approved_entries_by_source: dict[str, list[dict[str, Any]]] = {
            source_id: [] for source_id in source_ids
        }
        for row in connection.execute(
            """SELECT entry_id, work_title, position, contribution, limitation,
                      relevance, source_refs_json
               FROM historiography_entries WHERE status = 'approved'
               ORDER BY created_at, entry_id"""
        ):
            entry = dict(row)
            refs = list(dict.fromkeys(json.loads(entry.pop("source_refs_json"))))
            for source_id in refs:
                if source_id in approved_entries_by_source:
                    approved_entries_by_source[source_id].append(entry)
    context: list[dict[str, Any]] = []
    for source_id, page_id in sorted(cited_pages):
        source, page = source_rows.get(source_id), page_rows.get((source_id, page_id))
        bibliography_status = source["bibliography_status"] if source else "SOURCE_NOT_FOUND"
        page_gate_passed = bool(
            page
            and str(page["printed_page"] or "").strip()
            and page["verification_state"] in verified_states
            and page["use_state"] == "research_usable"
        )
        context.append({
            "marker": f"[CITE:{source_id}@{page_id}]", "source_id": source_id,
            "page_id": page_id,
            "title": ((source or {}).get("citation_title") or (source or {}).get("project_title") or ""),
            "author": (source or {}).get("author", ""), "year": (source or {}).get("year", ""),
            "bibliography_status": bibliography_status,
            "printed_page": (page or {}).get("printed_page", ""),
            "physical_page": (page or {}).get("physical_page"),
            "page_verification_state": (page or {}).get("verification_state", "PAGE_NOT_FOUND"),
            "page_use_state": (page or {}).get("use_state", "PAGE_NOT_FOUND"),
            "page_gate_passed": page_gate_passed,
            "approved_historiography": approved_entries_by_source.get(source_id, []),
            "citation_qualification": (
                "APPROVED_HISTORIOGRAPHY_CITABLE"
                if bibliography_status == "HUMAN_VERIFIED" and page_gate_passed
                and approved_entries_by_source.get(source_id)
                else "DIRECT_PAGE_CITABLE"
                if bibliography_status == "HUMAN_VERIFIED" and page_gate_passed
                else "CITATION_GATE_INCOMPLETE"
            ),
        })
    return context


_REVIEW_EVIDENCE_CONTEXT_MAX_CHARS = 80_000


def _review_evidence_context(project_root: Path, cited_evidence_ids: list[str],
                             approved_freezes: list[dict[str, Any]]) -> str:
    """Build a bounded ledger for only the frozen evidence used by this manuscript."""
    cited_evidence_ids = list(dict.fromkeys(cited_evidence_ids))
    if not cited_evidence_ids:
        return "当前正文没有 EVID。"

    cited_evidence_set = set(cited_evidence_ids)
    selected: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    claim_hits: list[dict[str, str]] = []
    relevant_freezes: list[dict[str, Any]] = []
    for freeze in approved_freezes:
        freeze_is_relevant = False
        for claim in freeze["payload"].get("claims", []):
            effective_boundary = str(
                claim.get("does_not_support", "") or freeze["payload"].get("boundary", "")
            )
            for evidence in claim.get("evidence", []):
                evidence_id = str(evidence.get("evidence_id", ""))
                if evidence_id not in cited_evidence_set:
                    continue
                freeze_is_relevant = True
                if evidence_id not in selected:
                    selected[evidence_id] = (freeze, evidence)
                claim_hits.append({
                    "freeze_id": str(freeze["freeze_id"]),
                    "evidence_id": evidence_id,
                    "relation": str(evidence.get("relation", "")),
                    "claim_id": str(claim.get("claim_id", "")),
                    "claim_text": str(claim.get("text", "")),
                    "boundary": effective_boundary,
                })
        if freeze_is_relevant:
            relevant_freezes.append(freeze)

    evidence_alias = {
        evidence_id: f"E{index:02d}"
        for index, evidence_id in enumerate(cited_evidence_ids, 1)
    }
    freeze_alias = {
        str(freeze["freeze_id"]): f"F{index:02d}"
        for index, freeze in enumerate(relevant_freezes, 1)
    }
    claim_signatures: list[tuple[str, str, str]] = []
    for hit in claim_hits:
        signature = (hit["claim_id"], hit["claim_text"], hit["boundary"])
        if signature not in claim_signatures:
            claim_signatures.append(signature)
    claim_alias = {
        signature: f"C{index:02d}"
        for index, signature in enumerate(claim_signatures, 1)
    }

    anchor_ids: list[str] = []
    for evidence_id in cited_evidence_ids:
        if evidence_id not in selected:
            continue
        _freeze, evidence = selected[evidence_id]
        anchors = list(evidence.get("block_ids", []))
        for values in evidence.get("field_anchors", {}).values():
            anchors.extend(values)
        anchor_ids.extend(str(value) for value in anchors if str(value).strip())
    anchor_ids = list(dict.fromkeys(anchor_ids))
    anchor_alias = {
        block_id: f"A{index:03d}" for index, block_id in enumerate(anchor_ids, 1)
    }

    with connect(project_root) as connection:
        page_printed = {
            row["page_id"]: str(row["printed_page"] or "").strip()
            for row in connection.execute("SELECT page_id, printed_page FROM pages")
        }
    eligible_blocks: dict[str, dict[str, Any]] = {}
    if anchor_ids:
        placeholders = ",".join("?" for _ in anchor_ids)
        with connect(project_root) as connection:
            rows = [dict(row) for row in connection.execute(
                f"""SELECT b.block_id, b.block_order,
                           COALESCE(b.human_text, b.machine_text) AS text,
                           b.verification_state AS block_verification_state,
                           b.use_state AS block_use_state,
                           p.page_id, p.physical_page, p.printed_page,
                           p.verification_state AS page_verification_state,
                           p.use_state AS page_use_state
                    FROM blocks b JOIN pages p ON p.page_id = b.page_id
                    WHERE b.block_id IN ({placeholders})""", anchor_ids,
            )]
        verified_blocks = {"human_verified", "human_repaired"}
        verified_pages = {"human_spot_checked", "human_verified", "human_repaired"}
        eligible_blocks = {
            row["block_id"]: row for row in rows
            if row["block_verification_state"] in verified_blocks
            and row["block_use_state"] == "research_usable"
            and row["page_verification_state"] in verified_pages
            and row["page_use_state"] == "research_usable"
        }

    lines = [
        "本稿实际引用 EVID 清单（按正文首次出现顺序；本轮只评审这些编号）：",
        *(f"{evidence_alias[evidence_id]}=[EVID:{evidence_id}]"
          for evidence_id in cited_evidence_ids),
        (
            "证据边界规则：每个 [EVID:...] 都是独立证据单元；其关联主张和单证据边界只约束该编号。"
            "不得用某一计划、出发或途中事件的边界，否定正文另一个已经列入上述清单的 "
            "FROZEN_APPROVED 后续事件；边界不是反证，也不表示事件之间冲突。"
        ),
    ]

    if relevant_freezes:
        lines.append("批准冻结包别名（仅含本稿实际 EVID 所在冻结包）：")
        lines.extend(
            f"{freeze_alias[str(freeze['freeze_id'])]}=批准冻结包 "
            f"{freeze['freeze_id']}：{freeze['title']}"
            for freeze in relevant_freezes
        )
    if claim_signatures:
        lines.append(
            "局部主张/边界定义（相同签名只列一次；后列全部来源冻结包、EVID 与关系；"
            "定义仅通过映射约束对应 EVID，不得跨 EVID 外推）："
        )
        for signature in claim_signatures:
            mappings_by_relation: dict[str, list[str]] = {}
            for hit in claim_hits:
                if (hit["claim_id"], hit["claim_text"], hit["boundary"]) != signature:
                    continue
                relation = hit["relation"] or "未登记"
                mappings_by_relation.setdefault(relation, []).append(
                    f"{freeze_alias[hit['freeze_id']]}:{evidence_alias[hit['evidence_id']]}"
                )
            mappings = ";".join(
                f"{relation}[{','.join(values)}]"
                for relation, values in mappings_by_relation.items()
            )
            claim_id, claim_text, boundary = signature
            lines.append(
                f"[{claim_alias[signature]}] claim_id={claim_id}｜关系映射={mappings}｜"
                f"主张={claim_text}｜边界={boundary}"
            )

    lines.append("逐项证据记录（E/F/C/A 均按上列别名回查；只含正文实际引用 EVID）：")
    for evidence_id in cited_evidence_ids:
        selected_item = selected.get(evidence_id)
        if selected_item is None:
            lines.append(f"- MISSING_APPROVED_FREEZE｜[EVID:{evidence_id}]")
            continue
        freeze, evidence = selected_item
        pages = "–".join(
            str(value) for value in evidence.get("physical_pages", [evidence.get("physical_page", "")])
            if str(value) != ""
        )
        printed_values = evidence.get("printed_pages", []) or [
            page_printed.get(str(page_id), "") for page_id in evidence.get("page_ids", [])
        ]
        printed = "–".join(str(value) for value in printed_values if str(value).strip())
        locator = f"原书页 {printed}｜物理页 {pages}" if printed else f"物理页 {pages}"
        evidence_anchor_ids = list(evidence.get("block_ids", []))
        for values in evidence.get("field_anchors", {}).values():
            evidence_anchor_ids.extend(values)
        evidence_anchor_ids = list(dict.fromkeys(
            str(value) for value in evidence_anchor_ids if str(value).strip()
        ))
        quote = str(evidence.get("quote", ""))
        quote_receipt = "见下列关联锚块完整文本" if evidence_anchor_ids else quote
        lines.append(
            f"[{evidence_alias[evidence_id]}]｜FROZEN_APPROVED｜"
            f"{freeze_alias[str(freeze['freeze_id'])]}｜{evidence.get('relation', '')}｜"
            f"{evidence.get('source_id', '')}｜"
            f"{locator}｜{evidence.get('qualification', '')}｜"
            f"event_date={evidence.get('event_date', '')}｜route={evidence.get('route', '')}｜"
            f"note={evidence.get('note', '') or evidence.get('notes', '')}｜"
            f"anchors={','.join(anchor_alias[value] for value in evidence_anchor_ids) or '未登记'}｜"
            f"冻结引文={quote_receipt}"
        )
        for field_name, values in evidence.get("field_anchors", {}).items():
            field_anchor_ids = list(dict.fromkeys(
                str(value) for value in values if str(value).strip()
            ))
            lines.append(
                f"  field:{field_name}="
                f"{','.join(anchor_alias[value] for value in field_anchor_ids) or '未登记'}"
            )

    if eligible_blocks:
        lines.append(
            f"上下文无损压缩回执｜{len(claim_hits)} 条主张-证据关系按 "
            f"{len(claim_signatures)} 个主张/边界签名归一并保留来源冻结包与关系；"
            f"锚块按编号去重，{len(eligible_blocks)} 个合格锚块均保留全文，未截断。"
        )
        lines.append("关联的人工复核、research_usable 锚块原文（按页聚合；每个块全文只列一次）：")
        previous_page_id = ""
        for block_id in anchor_ids:
            block = eligible_blocks.get(block_id)
            if block is None:
                continue
            printed = str(block["printed_page"] or "").strip()
            if block["page_id"] != previous_page_id:
                locator = (
                    f"原书页 {printed}｜物理页 {block['physical_page']}"
                    if printed else f"物理页 {block['physical_page']}"
                )
                lines.append(f"[PAGE {block['page_id']}｜{locator}]")
                previous_page_id = block["page_id"]
            text = re.sub(r"\s+", " ", str(block["text"])).strip()
            lines.append(f"{anchor_alias[block_id]}=[ANCHOR {block_id}] {text}")
    ineligible = [block_id for block_id in anchor_ids if block_id not in eligible_blocks]
    if ineligible:
        lines.append(
            "未进入评审上下文的锚块（当前并非人工复核且 research_usable）："
            + "、".join(f"{anchor_alias[block_id]}={block_id}" for block_id in ineligible)
        )
    context = "\n".join(lines) or "当前正文所用 EVID 没有批准冻结记录。"
    if len(context) > _REVIEW_EVIDENCE_CONTEXT_MAX_CHARS:
        raise ValueError(
            "review evidence context exceeds the bounded limit; split the review scope "
            "instead of sending the full evidence package"
        )
    return context


def _review_grounded_locators(text: str) -> set[str]:
    locators: set[str] = set()
    for match in re.finditer(
        r"(?<!\d)((?:1[5-9]\d{2}|20\d{2}))[-/.年](\d{1,2})[-/.月](\d{1,2})日?",
        text,
    ):
        year, month, day = (int(value) for value in match.groups())
        locators.update({f"year:{year}", f"date:{year}-{month}-{day}", f"month-day:{month}-{day}"})
    for match in re.finditer(r"(?<!\d)(\d{1,2})月(\d{1,2})日?", text):
        locators.add(f"month-day:{int(match.group(1))}-{int(match.group(2))}")
    for match in re.finditer(r"(?<!\d)(?:1[5-9]\d{2}|20\d{2})(?!\d)", text):
        locators.add(f"year:{int(match.group(0))}")
    for match in re.finditer(
        r"(?:原书页|物理页)\s*(\d+)(?:\s*[–—-]\s*(\d+))?",
        text,
    ):
        locators.add(f"page:{int(match.group(1))}")
        if match.group(2):
            locators.add(f"page:{int(match.group(2))}")
    return locators


def _assert_review_locators_grounded(report: str, prompt: str) -> None:
    unsupported = sorted(_review_grounded_locators(report) - _review_grounded_locators(prompt))
    if unsupported:
        raise ValueError(
            "review returned an ungrounded date/page locator: " + ", ".join(unsupported)
        )


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
    cited_evidence_ids = list(dict.fromkeys(
        re.findall(r"\[EVID:([A-Za-z0-9_]+)\]", internal_manuscript_text)
    ))
    cited_direct_pages = set(re.findall(
        r"\[CITE:([A-Za-z0-9_]+)@([A-Za-z0-9_:]+)\]", internal_manuscript_text,
    ))
    citation_context = _review_citation_context(project_root, cited_direct_pages)
    coverage_receipt = _manuscript_coverage_receipt(project_root, internal_manuscript_text)
    approved_freezes = [freeze for freeze in research["freezes"] if freeze["status"] == "approved"]
    evidence_context = _review_evidence_context(
        project_root, cited_evidence_ids, approved_freezes,
    )
    citation_lines: list[str] = []
    for citation in citation_context:
        citation_lines.append(
            f"- {citation['citation_qualification']}｜{citation['marker']}｜"
            f"{citation['title']}｜{citation['author']}｜{citation['year']}｜"
            f"原书页 {citation['printed_page']}｜物理页 {citation['physical_page']}｜"
            f"页状态 {citation['page_verification_state']}｜用途 {citation['page_use_state']}｜"
            f"书目状态 {citation['bibliography_status']}"
        )
        for entry in citation["approved_historiography"]:
            citation_lines.append(
                f"  已批准学术史 {entry['entry_id']}｜《{entry['work_title']}》｜"
                f"定位：{entry['position']}｜贡献：{entry['contribution']}｜"
                f"限制：{entry['limitation']}｜与本文关系：{entry['relevance']}"
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
            "证据台账中的 CANDIDATE_NOT_FROZEN 只能作为有界回退线索，不能当作当前正文已经获准使用的证据。"
            "FROZEN_APPROVED 是批准冻结的一手或事实证据；APPROVED_HISTORIOGRAPHY_CITABLE 是人工批准的学术史引证，"
            "其书目已核、所引页面已人工复核且可用于研究。二者职责不同：EVID 支撑正文事实，CITE 用于学术史对话、"
            "邻近研究或经人工批准的原页引证。不要因为 CITE 未进入冻结包，就判定它未登记、未批准或不可引用。"
            "DIRECT_PAGE_CITABLE 表示书目与页面门禁已通过但未绑定已批准学术史卡；"
            "CITATION_GATE_INCOMPLETE 才表示本轮确有资格缺口。评审只能按下列本稿实际 CITE 回执判断，不得拿冻结包要求替代 CITE 门禁。\n"
            "评审报告中的日期、原书页、物理页和具体地名，只能复述下列研究设计、证据台账、"
            "CITE 回执或正文中已经出现的定位；上下文没有支持时，不得凭模型记忆发明替代日期、页码或地名。\n"
            "证据台账开头的 EVID 清单是本稿实际引用范围。每个 EVID 下的关联主张与单证据边界只适用于该证据；"
            "不得用某个计划事件或出发事件的边界，否定正文另一个已引用且标为 FROZEN_APPROVED 的后续事件。"
            "如需指出事件冲突，必须引用发生冲突的两个具体 EVID，而不能把单条边界当作冲突证据。\n"
            f"本轮角色：{role}\n职责：{REVIEW_ROLES[role]}\n"
            "请用中文依次输出：阻断问题、主要问题、次要问题、可保留之处、建议的有界回退步骤。"
            "每个问题指出具体章节或证据编号；没有证据就明确说没有。不要展示推理过程，"
            "直接给出 600—900 字的正式评审报告。\n\n"
            f"稿件题名：{manuscript['title']}\n当前字符数：{len(manuscript_text)}\n"
            f"投稿模板：{template['name']}｜{template['version_label']}｜{template['citation_style']}\n"
            f"模板组成：{'；'.join(template['section_rules'])}\n\n"
            f"导出门禁：{export_preview['citation_status']}｜"
            f"{'；'.join(export_preview['warnings']) or '当前未发现导出门禁'}\n\n"
            f"材料覆盖回执（仅作警告，不设硬阈值）：\n{_json(coverage_receipt)}\n\n"
            "人工批准研究设计（这是作者的范围与方法决定，不是史料事实；不要因其缺少史料引文而否定，"
            "但可以检查正文是否越出或误用这一边界）：\n"
            f"{shared_design['title'] + chr(10) + shared_design['content'] if shared_design else '当前没有人工批准的共同计划。'}\n\n"
            f"证据台账：\n{evidence_context}\n\n"
            f"本稿实际 CITE 资格回执（只列正文已出现的 CITE）：\n"
            f"{chr(10).join(citation_lines) or '当前正文没有 CITE。'}\n\n"
            f"期刊导出预览：\n{manuscript_text}{previous_reports}"
        )
        report = (reviewer(prompt) if reviewer else
                  (_secondary_review_write(prompt) if use_secondary else _primary_review_write(prompt))).strip()
        if len(report) < 20:
            raise ValueError(f"{role} returned an empty or unusably short review")
        _assert_review_locators_grounded(report, prompt)
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
            "is_current": True, "reports": reports, "coverage_receipt": coverage_receipt,
            "citation_context": citation_context,
            "created_at": now}


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
