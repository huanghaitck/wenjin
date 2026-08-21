from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import append_audit, connect


READING_BLOCK_TYPES = {"paragraph", "heading", "footnote"}
HUMAN_VERIFIED_STATES = {"human_verified", "human_repaired"}


def _confirmed_continuations(connection: Any, source_id: str) -> set[tuple[str, str]]:
    confirmed: set[tuple[str, str]] = set()
    rows = connection.execute(
        """SELECT from_block_id, to_block_id, human_value, verification_state
           FROM page_relations WHERE source_id = ?
             AND relation_type IN ('continues_to', 'continues_on_next_page')""",
        (source_id,),
    ).fetchall()
    for row in rows:
        if row["verification_state"] not in HUMAN_VERIFIED_STATES or not row["human_value"]:
            continue
        value = json.loads(row["human_value"])
        continues = value is True or (
            isinstance(value, dict)
            and (value.get("continues") is True or value.get("value") is True)
        )
        if continues and row["from_block_id"] and row["to_block_id"]:
            confirmed.add((str(row["from_block_id"]), str(row["to_block_id"])))
    return confirmed


def _page_label(page: dict[str, Any]) -> str:
    printed = str(page.get("printed_page") or "").strip()
    return f"物理页 {page['physical_page']}" + (f"（印刷页 {printed}）" if printed else "")


def _render_unit(unit: dict[str, Any]) -> list[str]:
    segments = unit["segments"]
    first = segments[0]
    block_type = first["block_type"]
    lines: list[str] = []
    if block_type == "heading":
        lines.append(f"### {first['text'].strip()}")
        return lines
    if block_type == "footnote":
        lines.append(f"> 注：{first['text'].strip()}")
        return lines
    for index, segment in enumerate(segments):
        if index:
            lines.append(
                f"<!-- confirmed_page_continuation: {_page_label(segments[index - 1])} -> "
                f"{_page_label(segment)} -->"
            )
        lines.append(
            f"<!-- block: {segment['block_id']}; physical_page: {segment['physical_page']}; "
            f"printed_page: {segment.get('printed_page') or 'unknown'}; "
            f"verification: {segment['verification_state']} -->"
        )
        lines.append(segment["text"].strip())
    return lines


def build_reading_markdown(
    project_root: Path,
    source_id: str,
    *,
    verified_only: bool = False,
) -> dict[str, Any]:
    """Build a readable derivative without replacing page-aware forensic Markdown."""
    project_root = project_root.resolve()
    with connect(project_root) as connection:
        source = connection.execute(
            "SELECT source_id, title, processing_state, use_state FROM sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if source is None:
            raise KeyError(f"unknown source: {source_id}")
        version = connection.execute(
            """SELECT source_version_id, sha256, project_path FROM source_versions
               WHERE source_id = ? ORDER BY created_at DESC LIMIT 1""",
            (source_id,),
        ).fetchone()
        pages = [dict(row) for row in connection.execute(
            """SELECT page_id, physical_page, printed_page, verification_state, use_state
               FROM pages WHERE source_id = ? ORDER BY physical_page""",
            (source_id,),
        ).fetchall()]
        continuations = _confirmed_continuations(connection, source_id)
        blocks_by_page: dict[str, list[dict[str, Any]]] = {}
        for page in pages:
            blocks = [dict(row) for row in connection.execute(
                """SELECT block_id, block_order, block_type,
                          COALESCE(human_text, machine_text) AS text,
                          verification_state, use_state
                   FROM blocks WHERE page_id = ? AND use_state != 'superseded'
                   ORDER BY block_order""",
                (page["page_id"],),
            ).fetchall()]
            selected = []
            for block in blocks:
                if block["block_type"] not in READING_BLOCK_TYPES or not block["text"].strip():
                    continue
                if verified_only and not (
                    block["verification_state"] in HUMAN_VERIFIED_STATES
                    and block["use_state"] == "research_usable"
                ):
                    continue
                selected.append({**block, **page})
            blocks_by_page[page["page_id"]] = selected

    units: list[dict[str, Any]] = []
    selected_block_count = 0
    for page in pages:
        for block in blocks_by_page[page["page_id"]]:
            selected_block_count += 1
            segment = {
                "block_id": block["block_id"],
                "block_type": block["block_type"],
                "text": block["text"],
                "verification_state": block["verification_state"],
                "physical_page": block["physical_page"],
                "printed_page": block["printed_page"],
            }
            previous = units[-1]["segments"][-1] if units else None
            if (
                previous
                and previous["block_type"] == "paragraph"
                and segment["block_type"] == "paragraph"
                and (previous["block_id"], segment["block_id"]) in continuations
            ):
                units[-1]["segments"].append(segment)
            else:
                units.append({"segments": [segment]})

    mode = "verified" if verified_only else "current"
    lines = [
        f"# {source['title']}",
        "",
        "> 本文件是从问津页级结构生成的派生阅读本，不替代原PDF、逐页核验Markdown或证据锚点。",
        f"> 模式：{'仅人工核验文本' if verified_only else '当前有效文本（可能含待核块）'}。",
        f"> 来源：{source_id}；版本：{version['source_version_id'] if version else 'unknown'}；"
        f"SHA-256：{version['sha256'] if version else 'unknown'}。",
        "",
    ]
    last_page: int | None = None
    for unit in units:
        first = unit["segments"][0]
        if first["physical_page"] != last_page:
            lines.extend([f"## {_page_label(first)}", ""])
        lines.extend(_render_unit(unit))
        lines.append("")
        last_page = unit["segments"][-1]["physical_page"]
    if not units:
        lines.extend(["（当前模式下没有可输出的文本块。）", ""])
    return {
        "source_id": source_id,
        "source_version_id": version["source_version_id"] if version else "",
        "mode": mode,
        "page_count": len(pages),
        "block_count": selected_block_count,
        "confirmed_continuation_count": sum(max(0, len(unit["segments"]) - 1) for unit in units),
        "markdown": "\n".join(lines).rstrip() + "\n",
    }


def export_reading_markdown(
    project_root: Path,
    source_id: str,
    *,
    verified_only: bool = False,
) -> dict[str, Any]:
    artifact = build_reading_markdown(project_root, source_id, verified_only=verified_only)
    target = (
        project_root.resolve() / "sources" / source_id / "derived" / "reading"
        / f"reading-{artifact['mode']}.md"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(artifact.pop("markdown"), encoding="utf-8")
    receipt = {**artifact, "project_path": target.relative_to(project_root.resolve()).as_posix()}
    with connect(project_root.resolve()) as connection:
        append_audit(connection, "source_reading_markdown_exported", "source", source_id, receipt)
    return receipt
