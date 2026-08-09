# ADR 0004｜Research Codex runtime and historical-evidence harness

Status: accepted; M4 authorized  
Date: 2026-08-09

## Context

M1-M3 已证明页面关系、局部阻断、视觉提案和人工修正可以工作，但当前形态仍是 PDF 修复工具。
最终产品需要支持开放式对话、可选模型、长任务、工具调用、联网研究、证据固定和长期记忆。若按
功能模块继续横向叠加，会形成多个互不相通的工作台，也无法提供 Codex 类的可恢复 Agent 体验。

## Decision

产品定位为本地优先的 Historian Research Codex。其核心是一个持久化 Agent workspace：线程、
Goal、Run、事件、工具调用、审批和模型角色；历史学 harness 通过来源资格、原页核验、证据冻结
和写作门禁约束 Agent。

V1 采用：

- 单一 Python 应用服务、项目 SQLite 和本地文件目录；
- 追加式运行事件与快照恢复；
- 默认一个主 Agent，加有界的视觉、阅读、翻译、引文审计和评审角色；
- OpenAI-compatible 与 Ollama 的薄模型适配器；
- 工具级只读/写入/外部副作用等级和显式审批；
- 开放 API、公开网页、授权 API、登录浏览器四类有区别的联网入口；
- Retrieval Record 与 Evidence Item 分离；
- 现有两套本地长期记忆通过 adapter 使用，不复制进项目数据库。

M4 先实现 Agent workspace 的一个纵向切片。联网、证据冻结、浏览器和写作按路线图逐阶段接入。

## Simplicity constraints

- 不在 M4 引入 LangGraph、LiteLLM、OpenHands SDK、向量数据库、图数据库或消息队列；
- 不建立通用多 Agent 编排器；
- 不创建独立后端服务或云账户系统；
- 不把现有 M1-M3 重构成抽象插件；
- 只在第二个真实实现出现后抽取共享接口。

## Consequences

- 用户能够在同一对话中逐步使用 PDF、检索、证据和写作工具；
- 运行时与研究领域状态分离，但共用项目事务和审计边界；
- 后续可以替换模型和工具实现，而不会绕过历史证据门禁；
- M4 需要新增数据库迁移、运行事件与客户端对话区，但不改动原始来源或已完成 M1-M3 语义。
