# 项目阶段、门禁与回退

## 参考阶段

1. Stage 0：项目、范围与材料入口。
2. Stage 1：材料验收、阅读与引用基础。
3. Stage 2：问题生成、学术史与竞争解释。
4. Stage 3：候选短测试与失败测试。
5. Stage 4：独立评审与唯一方向选择。
6. Stage 5：唯一证据包冻结。
7. Stage 6：唯一作者正式写作。
8. Stage 7：专项审稿、返修和事实引用终审。
9. Stage 8：证据保真语言修订、diff、渲染与人工定稿。

每个阶段都必须保存输入、输出、未解决项、阴性结果和停止状态。候选均不成立时返回问题生成或停止，不得为维持流程前进而勉强选择。

## 写作回退

- `R0`：措辞、段落、结构和冻结材料的准确转述，由写作技能内部处理。
- `R1`：缺页码、版本、书目信息或脚注格式，返回引用补全。
- `R2`：主张缺桥接证据、材料冲突或竞争解释，建立有范围、轮次和停止条件的补证票。
- `R3`：改变题目、地域、时段、核心案例或中心解释，必须人工批准。

## 状态文件

项目模式使用 `.historical-research/project.yaml`。推荐字段：

```yaml
schema_version: 1
project_type: historical_research
mode: project
title: ""
language: zh-CN
citation_style: ""
source_roots: []
memory_backend: none
current_stage: 0
full_workflow_authorized: false
multi_agent_authorized: false
stop_gate: STAGE_0_NOT_STARTED
```

状态文件记录权限和阶段，不替代研究产物本身。
