---
name: historical-evidence-freeze
description: 为人工批准的唯一历史论文方向冻结主张、证据、原页、译文、脚注、反证、置信度和禁写范围，形成可直接供唯一写作主体调用的证据包。仅在用户明确批准冻结且问题与论证已稳定时使用；不得同时冻结多个正式方向或把未核材料放入可写区。
---

# 历史证据冻结

完整读取 [核心政策](../../references/core-policy.md)、[项目阶段](../../references/project-stages.md) 和 [史学证据契约](../../references/evidence-contract.md)。

1. 确认唯一方向已获人工批准，竞争候选和合并方案已有处理决定。
2. 为每条主张登记证据 ID、来源身份、原书页/PDF页、独立性、支持范围和不能支持的强说法。
3. 准备首次引证、再次引证、译文、原文、档号、地图和图像信息；不预编号脚注。
4. 登记反证、最低可行论点、失败条件和置信度。
5. 将缺页码或书目信息标为 R1，将机制缺口标为 R2；改变核心题目则标为 R3 并等待批准。
6. 使用 `../../assets/templates/claim_citation_map.csv`，运行 `../../scripts/validate_claim_citation_map.py`。

冻结包必须区分 `FROZEN_WRITABLE`、`CONTEXT_ONLY`、`COUNTEREVIDENCE`、`UNRESOLVED` 和 `PROHIBITED_CLAIM`。冻结完成只授权下一阶段写作，不等于论文已经成立。
