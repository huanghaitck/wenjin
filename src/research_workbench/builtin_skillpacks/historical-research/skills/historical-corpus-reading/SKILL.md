---
name: historical-corpus-reading
description: 对已经验收的史学语料制定阅读计划并执行元数据阅读、定向阅读或全文阅读，登记材料功能、证据边界、异常与待核页位置。用户要求完整阅读论文、研读史料或判断哪些材料值得 AI 读时使用；不把摘要、目录、OCR 命中或阅读札记冒充原文全文。
---

# 史学语料阅读

完整读取 [核心政策](../../references/core-policy.md)、[方法摘要](../../references/methodology.md) 和 [史学证据契约](../../references/evidence-contract.md)。研究领域已经明确且存在对应 Profile Pack 时，按 [领域 Profile Pack 规范](../../references/domain-profile-packs.md) 只加载相关领域包。

## 分配深度

- 核心一手史料：全文或边界明确的连续精读，关键页图像核验。
- 直接研究：原则上全文阅读。
- 邻近研究：围绕指定问题定向阅读。
- 方法研究：提炼操作、适用范围与反例。
- 结构范例：学习问题和材料组织，不复制作者声腔。
- 目录、摘要和工具书：只作定位。

## 记录

使用 `../../assets/templates/reading_manifest.csv`。分别记录材料明确记载、作者解释、研究者推论、竞争解释、未知项和需要回看原页的位置。标明实际阅读页段、跳过部分和不可读页。

承担论证的具体段落、地图、照片、表格或档案页使用 `../../assets/templates/evidence_items.csv` 建立 Evidence Item，并运行 `../../scripts/validate_evidence_items.py`。全文阅读状态不自动使每一条摘录成为可引用证据。

多 Agent 只有在用户授权后才可按材料家族分工；每个 Agent 必须返回阅读范围和未读范围，主 Work 统一去重，避免把多格式副本计为独立见证。
