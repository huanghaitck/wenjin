---
name: historical-project-workflow
description: 建立或推进完整的学术性历史研究项目，管理阶段状态、产物、人工门禁和有界回退。仅在用户明确说启动完整史学流程、显式批准下一阶段或调用本技能时使用；不得因单个史实问题、局部润色或“完整研究一下”自动创建项目。
---

# 史学项目流程

完整读取 [核心政策](../../references/core-policy.md) 和 [项目阶段](../../references/project-stages.md)。

## 建立项目

1. 核对工作区、目标、时空范围、允许写入的位置和用户授权。
2. 从 `../../assets/templates/project.yaml` 创建 `.historical-research/project.yaml`。
3. 使用 `../../scripts/validate_project_state.py` 校验状态。
4. 只启动当前获批阶段；把下一阶段标为关闭。

## 推进与恢复

- 开始前读取状态、既有产物和停止门禁，不因会话重启从头执行。
- 每阶段记录输入、输出、未解决项、阴性结果、回退票和人工决定。
- 同一停止条件连续出现时报告阻塞，不伪造阶段完成。
- 用户暂停、只读或禁止下游阶段时立即停止写入。

## Agent 规则

只有 `multi_agent_authorized: true` 或用户本轮明确要求时才可启动多 Agent。并行任务必须独立、边界明确且主要只读；中央状态和同一正文由主 Work 单独维护。

结束时报告当前阶段、已验证产物、未解决风险和精确停止门禁。
