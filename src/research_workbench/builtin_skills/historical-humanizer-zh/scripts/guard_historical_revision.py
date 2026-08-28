#!/usr/bin/env python3
"""Detect changes to protected elements in a historical manuscript revision."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable


QUALIFIERS = (
    "可能",
    "或许",
    "未必",
    "仅",
    "只",
    "只限于",
    "限于",
    "至少",
    "至多",
    "尚",
    "尚无",
    "尚未",
    "不足以",
    "不能据此",
    "无法",
    "未见",
    "没有记录",
    "不能证明",
    "不能断言",
    "不等于",
    "不代表",
    "不构成",
)


def regex_items(pattern: str, text: str, flags: int = 0, group: int = 0) -> list[str]:
    return [match.group(group) for match in re.finditer(pattern, text, flags)]


def footnote_definitions(text: str) -> list[str]:
    return regex_items(r"(?m)^\[\^[^\]]+\]:[^\n]*$", text)


def footnote_refs(text: str) -> list[str]:
    without_definitions = re.sub(r"(?m)^\[\^[^\]]+\]:[^\n]*$", "", text)
    return regex_items(r"\[\^[^\]]+\]", without_definitions)


def block_quotes(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith(">"):
            current.append(line)
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def inline_quotes(text: str) -> list[str]:
    return regex_items(r"“[^”\n]*”|‘[^’\n]*’|「[^」\n]*」|『[^』\n]*』", text)


def figures(text: str) -> list[str]:
    images = regex_items(r"!\[[^\]]*\]\([^)]+\)", text)
    captions = regex_items(r"(?m)^\*\*图[^*\n]*\*\*$", text)
    sources = regex_items(r"(?m)^资料来源：[^\n]*$", text)
    return images + captions + sources


def urls(text: str) -> list[str]:
    return regex_items(r"https?://[^\s，。；）)\]]+|doi:\s*\S+|10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text, re.I)


def cyrillic_runs(text: str) -> list[str]:
    return regex_items(r"[А-Яа-яЁё][А-Яа-яЁёA-Za-z.\-—–№]*", text)


def numbers(text: str) -> list[str]:
    return regex_items(r"(?<![A-Za-z])\d+(?:[.,]\d+)*(?:[—–-]\d+(?:[.,]\d+)*)?(?:%|％)?", text)


def qualifier_items(text: str) -> list[str]:
    pattern = "|".join(re.escape(item) for item in sorted(QUALIFIERS, key=len, reverse=True))
    return regex_items(pattern, text)


def load_terms(path: Path | None) -> list[str]:
    if path is None:
        return []
    terms: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        item = raw.strip()
        if item and not item.startswith("#"):
            terms.append(item)
    return terms


def term_items(text: str, terms: Iterable[str]) -> list[str]:
    found: list[tuple[int, str]] = []
    for term in terms:
        start = 0
        while True:
            index = text.find(term, start)
            if index < 0:
                break
            found.append((index, term))
            start = index + len(term)
    return [item for _, item in sorted(found)]


def compare_sequence(original: list[str], revised: list[str]) -> dict[str, object]:
    original_counts = Counter(original)
    revised_counts = Counter(revised)
    removed = list((original_counts - revised_counts).elements())
    added = list((revised_counts - original_counts).elements())
    return {
        "status": "PASS" if original == revised else "FAIL",
        "original_count": len(original),
        "revised_count": len(revised),
        "sequence_equal": original == revised,
        "removed": removed[:30],
        "added": added[:30],
    }


def build_report(original_text: str, revised_text: str, terms: list[str]) -> dict[str, object]:
    extractors: dict[str, Callable[[str], list[str]]] = {
        "footnote_definitions": footnote_definitions,
        "footnote_references": footnote_refs,
        "block_quotes": block_quotes,
        "inline_quotes": inline_quotes,
        "figures_and_sources": figures,
        "urls_and_dois": urls,
        "cyrillic_runs": cyrillic_runs,
        "numbers": numbers,
        "qualifiers": qualifier_items,
        "protected_terms": lambda text: term_items(text, terms),
    }
    categories = {
        name: compare_sequence(extractor(original_text), extractor(revised_text))
        for name, extractor in extractors.items()
    }
    failed = [name for name, result in categories.items() if result["status"] == "FAIL"]
    qualifier_counts = Counter(qualifier_items(original_text))
    qualifier_literals = sorted(qualifier_counts)
    repeated_qualifiers = sorted(
        item for item, count in qualifier_counts.items() if count > 1
    )
    manual_review_warnings: list[dict[str, object]] = []
    if (
        categories["qualifiers"]["status"] == "PASS"
        and qualifier_literals
        and original_text != revised_text
    ):
        manual_review_warnings.append(
            {
                "code": "QUALIFIER_ATTACHMENT_REQUIRES_P1_AUDIT",
                "items": qualifier_literals,
                "repeated_items": repeated_qualifiers,
                "message": (
                    "Exact count and literal order cannot prove that qualifiers "
                    "still modify the same claims. A deletion in one "
                    "sentence and an addition in another can produce a false pass."
                ),
            }
        )
    return {
        "overall_status": "PASS" if not failed else "FAIL",
        "failed_categories": failed,
        "categories": categories,
        "manual_review_warnings": manual_review_warnings,
        "note": "This script checks exact protected elements only; facts, attribution, causality, scope, and evidentiary force still require human review.",
    }


def self_test() -> int:
    original = "1874年，作者写道：“道路可能受雨影响。”[^1]\n\n[^1]: Пясецкий, с. 39。"
    safe = "作者在1874年写道：“道路可能受雨影响。”[^1]\n\n[^1]: Пясецкий, с. 39。"
    unsafe = "作者在1875年写道：“道路受雨影响。”[^1]\n\n[^1]: Пясецкий, с. 39。"
    relocated_original = "有些停留给作画留下了时间；其中一处变化可能影响后续材料。"
    relocated_revised = "停留可能给作画留下时间；其中一处变化会影响后续材料。"
    safe_report = build_report(original, safe, ["Пясецкий"])
    unsafe_report = build_report(original, unsafe, ["Пясецкий"])
    relocated_report = build_report(relocated_original, relocated_revised, [])
    warning_codes = {
        item["code"] for item in relocated_report["manual_review_warnings"]
    }
    ok = (
        safe_report["overall_status"] == "PASS"
        and unsafe_report["overall_status"] == "FAIL"
        and relocated_report["overall_status"] == "PASS"
        and "QUALIFIER_ATTACHMENT_REQUIRES_P1_AUDIT" in warning_codes
    )
    print(
        json.dumps(
            {
                "self_test": "PASS" if ok else "FAIL",
                "safe": safe_report,
                "unsafe": unsafe_report,
                "same_literal_relocation_limit": relocated_report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", nargs="?", type=Path)
    parser.add_argument("revised", nargs="?", type=Path)
    parser.add_argument("--terms", type=Path, help="UTF-8 file with one protected literal per line")
    parser.add_argument("--json", dest="json_path", type=Path, help="Write the report to this JSON file")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    if args.original is None or args.revised is None:
        print("original and revised paths are required unless --self-test is used", file=sys.stderr)
        return 2
    original_text = args.original.read_text(encoding="utf-8")
    revised_text = args.revised.read_text(encoding="utf-8")
    report = build_report(original_text, revised_text, load_terms(args.terms))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
