---
name: historical-prose-revision-zh
description: 对事实、引用和论证已经稳定的中文历史论文副本进行证据保真的语言返修，清理翻译腔、车轱辘话、内部工作语言、抽象机制先行和外露式谨慎。仅在用户明确要求语言修订时使用；不得补事实、改论点、提高因果强度、模仿具体作者声腔或以降低检测率为目标。
---

# 中文史学语言返修

完整读取 [核心政策](../../references/core-policy.md) 和 [方法摘要](../../references/methodology.md)。

1. 只编辑副本，保留用户正在修改的基线文件。
2. 建立保护清单：直接引文、数字、专名、日期、限定语、脚注、图表、因果强度和用户已改段落。
3. 允许 `KEEP`；只改有明确问题的句段。
4. 用具体主语、动作、时间和材料推进叙述；把谨慎放进来源范围和句法。
5. 删除重复总结、研究过程语言和面向假想审稿人的连续辩护，但不删除必要证据限制。
6. 生成逐段 `KEEP/REVISE` 决定和 diff。DOCX 可用 `../../scripts/guard_historical_revision.py` 检查受保护文字、脚注和媒体。
7. 一旦修改触及事实、论点或引用，停止并退回 `historical-review-and-revision` 或 `historical-evidence-freeze`。

不得把参考论文的连续措辞写入稿件；只能学习可概括的结构与语言操作。
