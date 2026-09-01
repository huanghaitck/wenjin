#!/usr/bin/env python3
"""Heuristically flag template-like prose in a Chinese historical manuscript."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


PATTERNS: dict[str, re.Pattern[str]] = {
    "H01_INTERNAL_PROCESS": re.compile(r"Phase\s*\d|Agent|门禁|证据冻结|冻结文件|失败测试|内部讨论|方向淘汰", re.I),
    "H02_PREEMPTIVE_DEFENSE": re.compile(r"本文(?:并不|不是|没有).{0,45}(?:而是|也不是)|这里(?:并不|不是).{0,45}(?:而是|也不是)"),
    "H03_CONCEPT_BEFORE_EVIDENCE": re.compile(r"^(?:基于|依据|从.{0,12}角度看|本文所谓|本文所说的|这一界定)"),
    "H04_EVIDENCE_LEDGER_PROSE": re.compile(r"证据(?:链)?(?:的)?强度|每项材料承担|较小结论|证据等级|材料负责|本文能够说明"),
    "H05_SYMMETRIC_LAYERS": re.compile(r"^(?:第[一二三四五六七八九十]+层(?:[:：，、]|是|为))|第一(?:层|种|点).{0,120}第二(?:层|种|点)|首先.{0,120}其次.{0,120}(?:再次|最后)"),
    "H06_SUMMARY_CASCADE": re.compile(r"综上所述|由此可见|这意味着|这一点说明|可以看出|正在于|历史意义"),
    "H07_APHORISTIC_CLAIM": re.compile(r"物质重量|彼此塑造|取得具体形态|由此能够积累|并非自然存在|不是自然给定"),
    "H08_QUOTE_NOT_WORKING": re.compile(r"[”」』]\s*(?:\[\^[^\]]+\])?\s*$"),
    "H09_SOURCE_FLATTENING": re.compile(r"研究(?:已经)?证明.{0,25}(?:当时|现场)|理论证明.{0,25}(?:当时|现场)"),
    "H11_ARTIFICIAL_VOICE": re.compile(r"笔者认为|出乎意料的是|坦率地说|回头想想|有意思的是|说起来容易"),
    "H12_STYLE_MIMICRY": re.compile(r"仿照.{0,12}(?:文风|笔法|口吻)|模仿.{0,12}(?:文风|笔法|口吻)"),
}

ABSTRACT_TERMS = {
    "环境",
    "动物",
    "劳动",
    "技术",
    "时间",
    "知识",
    "机制",
    "意义",
    "层次",
    "关系",
    "条件",
    "能力",
    "配置",
    "形式",
    "内容",
    "位置",
    "可达",
    "可见",
    "记录",
    "传播",
}

ABSTRACT_PREDICATES = re.compile(r"共同|形成|决定|限定|影响|构成|转化|塑造|生产|进入")
TIME_MARKERS = re.compile(r"(?:18|19|20)\d{2}年|[七八九]十年代")
SYNOPTIC_MARKERS = re.compile(r"集中|转疏|重组|再调查|重新组织|相继|先后|时间节奏")


def paragraphs(text: str) -> list[str]:
    result: list[str] = []
    for raw in re.split(r"\n\s*\n", text):
        item = raw.strip()
        if not item:
            continue
        if item.startswith(("#", "[^", "![", "**图", "**关键词", "资料来源：")):
            continue
        if all(line.lstrip().startswith(">") for line in item.splitlines()):
            continue
        result.append(re.sub(r"\s+", " ", item))
    return result


def sentence_lengths(paragraph: str) -> list[int]:
    return [len(item.strip()) for item in re.split(r"[。！？!?；;]", paragraph) if item.strip()]


def analyze(text: str) -> dict[str, object]:
    paras = paragraphs(text)
    results: list[dict[str, object]] = []
    starts = Counter(item[:6] for item in paras if len(item) >= 6)
    for index, paragraph in enumerate(paras, start=1):
        tags = [name for name, pattern in PATTERNS.items() if pattern.search(paragraph)]
        abstract_hits = {term for term in ABSTRACT_TERMS if term in paragraph}
        dense_abstract_list = (
            paragraph.count("、") >= 4
            and len(abstract_hits) >= 5
            and ABSTRACT_PREDICATES.search(paragraph)
        )
        repeated_balanced_clauses = paragraph.count("；") >= 3 and len(abstract_hits) >= 4
        if dense_abstract_list or repeated_balanced_clauses:
            tags.append("H05_DENSE_ENUMERATION")
        if (
            len(paragraph) >= 180
            and len(TIME_MARKERS.findall(paragraph)) >= 5
            and len(SYNOPTIC_MARKERS.findall(paragraph)) >= 2
        ):
            tags.append("H14_SYNOPTIC_GRID_PROSE")
        lengths = sentence_lengths(paragraph)
        if len(lengths) >= 4:
            mean = sum(lengths) / len(lengths)
            spread = max(lengths) - min(lengths)
            if mean and spread / mean < 0.25:
                tags.append("H06_UNIFORM_SENTENCE_RHYTHM")
        if len(paragraph) >= 6 and starts[paragraph[:6]] >= 3:
            tags.append("H06_REPEATED_PARAGRAPH_OPENING")
        if tags:
            results.append(
                {
                    "paragraph": index,
                    "risk_tags": sorted(set(tags)),
                    "preview": paragraph[:180],
                }
            )
    return {
        "paragraph_count": len(paras),
        "flagged_paragraph_count": len(results),
        "findings": results,
        "note": "Heuristic style flags are prompts for close reading, not evidence of AI authorship and not automatic rewrite instructions.",
    }


def self_test() -> int:
    sample = (
        "Phase 6 的证据链强度来自三层材料。第一层是地图，第二层是旅行记，第三层是书评。"
        "由此可见，道路并非自然存在，而是动物、劳动、技术和时间共同形成。"
    )
    report = analyze(sample)
    standalone = analyze("第一层：先检查证据强度。")
    synoptic = analyze(
        "1860年换约以后，旅行已有依据。1872年甲进入山地，1875年乙又到此处。"
        "此后丙、丁和戊相继经过同一区域，分别从事道路调查、标本采集、外交观察和官方考察。"
        "几项旅行彼此并无统属，所负任务也不相同，却都在七十年代留下记录。"
        "进入八十年代，类似活动转疏，域外机构的调查方向也发生变化。"
        "1892年以后，专业学会重新组织人员，至1894年又形成新的调查。"
        "数次活动由此呈现集中、转疏和再调查的时间节奏。"
    )
    standalone_tags = set(standalone["findings"][0]["risk_tags"])
    synoptic_tags = set(synoptic["findings"][0]["risk_tags"])
    ok = (
        report["flagged_paragraph_count"] == 1
        and len(report["findings"][0]["risk_tags"]) >= 4
        and {"H04_EVIDENCE_LEDGER_PROSE", "H05_SYMMETRIC_LAYERS"}
        <= standalone_tags
        and "H14_SYNOPTIC_GRID_PROSE" in synoptic_tags
    )
    print(
        json.dumps(
            {
                "self_test": "PASS" if ok else "FAIL",
                "report": report,
                "standalone_layer": standalone,
                "synoptic_grid": synoptic,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    if args.input is None:
        raise SystemExit("input path is required unless --self-test is used")
    report = analyze(args.input.read_text(encoding="utf-8"))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
