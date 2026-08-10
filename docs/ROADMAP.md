# Historian Research Codex｜实施路线图

状态：2026-08-10 通过 ADR 0005 调整。M5 先建设研究图书馆，原联网阶段顺延。

2026-08-10 又通过 ADR 0006 启动 D1：不把 M6-M11 的标题提前宣布完成，而是从各阶段抽取最小
能力，先交付一条对话优先的真实端到端 Demo。验证后再分别加固各阶段。

## 总体策略

每个里程碑交付一个可见、可测试的纵向能力。保持一个本地应用、一个数据库写入者和一套领域
状态；不同时重写后端、前端和全部研究流程。每个里程碑单独提交 Git，真实材料检查不覆盖原件。

## 已完成

### M1｜研究来源状态内核

来源复制、页面/块/关系、异常、局部/整页修正、审计事件。

### M2｜页面感知 PDF 清洗

PDF 渲染、坐标文本、页面 Markdown、质量门禁、原页对照和本地修正 UI。

### M3｜视觉 OCR 提案

OpenAI-compatible/Ollama 视觉模型、provenance、人工接受/拒绝和真实历史页评测。

## 已完成的 Agent 基础

### M4｜Agent Workspace Foundation

状态：已完成（2026-08-09）。

目标：让系统第一次具备“科研版 Codex”的核心交互，而不是继续堆独立功能。

范围：

- thread/message、goal/run、追加事件、tool call 和 approval 持久化；
- OpenAI-compatible 与 Ollama 的文本模型 profile/role assignment；
- 一个主 Agent 的最小工具循环；
- 首批只读工具：项目状态、来源列表、页面读取；
- 一个需要人工批准的示范写工具：保存研究札记草稿；
- 对话、模型选择、Run 时间线和审批 UI；
- 应用重启后恢复线程和等待中的审批；
- deterministic mock provider 覆盖测试，不要求真实 API 才能验收。

不包含：联网检索、浏览器控制、证据冻结、长期记忆写入、翻译和正式稿件生成。

验收场景：用户在已有 M2/M3 项目中创建线程，选择模型，要求 Agent 查看一个来源的异常状态并
形成研究札记；Agent 调用只读工具后请求保存，用户可编辑后批准或拒绝；重启后状态与时间线完整。

## 当前阶段

### M5｜Skills-Compatible Research Library

状态：已完成（2026-08-10）。

- 发现并展示 `SKILL.md` 指令型技能，记录技能文件哈希；
- 用户明确选择目录后进行只读盘点，先预览、后批准、默认原地索引；
- 区分 Work、Edition、File、File Version，完整展示路径、时间、大小和哈希；
- 同一路径内容变化产生新 File Version，不因哈希变化丢失作品身份；
- PDF、Markdown、TXT 元数据和最多前十页快速分诊；
- 不确定、需视觉判断和暂不支持的材料继续保留，不自动排除或移动；
- 标签、书目信息、全文片段检索与项目关联。

验收：选择一个测试目录后可看到盘点预览；人工批准后材料原地进入图书馆；修改文件一个字再扫，
同一作品下出现完整的新旧版本；按题名、作者或标签可找回，原文件路径和内容均未被程序修改。

不包含：任意 Skill 脚本执行、自动移动整理、联网研究、登录数据库、证据冻结和桌面打包。

## 当前纵向 Demo

### D1｜Conversation-first End-to-End Demo

状态：已完成（2026-08-10）。范围、门禁和验收记录见 `docs/D1_END_TO_END_DEMO_TASK_SPEC.md`。

- 对话首页、项目新建/切换和可恢复线程；
- 图书馆具体文件版本加入项目并进入页面处理；
- OpenAlex/Crossref 检索记录与 Zotero 本地只读探测；
- Claim、Evidence Item、人工 Freeze、受冻结证据约束的试写/评审/导出；
- 研究浏览器域名授权、外开页面与回执；
- 带来源的记忆候选，不自动写入长期库。

## 后续阶段

### D2｜Evidence-preserving Reading and Section Writing

状态：已完成（2026-08-10）。来自 D1 的首轮真实使用反馈，验收见
`docs/D2_AUTHORING_READING_TASK_SPEC.md`。

- Markdown 稿件导入、章节和不可变版本；
- 保留引文、数字、脚注与来源标记的润色提案；
- 只依据已批准冻结包的分节试写；
- 有界批量阅读札记、学术史条目和期刊模板第一版；
- 原文/提案对照、人工批准、组合导出。

以下编号阶段仍用于后续生产化加固，不因 D2 的纵向切片而自动宣布完成。

### D3｜Research Object Workspaces and Structured Document Model

状态：ADR 与迁移方案完成，等待实施批准。

- 四个永久工作空间：研究对话、研究图书馆、文章工作台、项目设置；
- 文件导入、收件箱、页面处理和文献修复归入图书馆；
- 稿件采用结构化文档树，DOCX/Markdown 成为工作台内适配器；
- 文章侧栏使用绑定稿件版本、章节和选区的同一主 Agent；
- 研究浏览器作为中央对象标签，右侧保存检索、收集和审批；
- additive-first 迁移，旧表和旧路径在核验前保持可读。

实施前必须通过 `docs/D3_INFORMATION_ARCHITECTURE_MIGRATION_PLAN.md` 的人工门禁。

### M6｜Open Research Retrieval

- OpenAlex 与 Crossref connector；
- query plan、检索范围和停止条件；
- Retrieval Record、结果去重、零结果和限流状态；
- 在对话中查看、筛选并把结果登记为 `DISCOVERED`；
- 公开 URL/PDF 的有界取得、哈希与来源登记；
- Zotero 本地只读探测作为可选能力。

验收：一次对话产生可复现的检索记录，取得一份公开文件并进入 M1 来源登记；搜索结果本身不具备
引用资格。

### M7｜Authenticated Research Browser

- 专用 headed research profile；
- accessibility/DOM/screenshot 的受控页面读取；
- domain、session、action scope；
- 下载/提交/批量动作审批；
- 用户选择后附着现有浏览器标签页的高级模式；
- 浏览检索收据与下载哈希；不保存 Cookie、密码和未脱敏 HAR。

验收：用户亲自登录一个授权数据库，Agent 在允许域内执行有界检索并下载用户有权访问的文件；
关闭应用后凭证未进入项目或 Git。

### M8｜Evidence and Claim Freeze

- 来源资格状态链；
- Evidence Item 与原页/区域锚点；
- Claim、ClaimLink、反证和来源独立性；
- 原文/译文并排核验；
- 教授批准的 evidence freeze；
- 冻结包差异和回退票。

验收：从 M2 页面固定一条证据、连接一个主张、记录一个竞争解释并经人工冻结；每项可回到原页。

### M9｜Scholarly Dialogue and Historiography

- 研究问题与范围对象；
- 有来源的 seminar thread；
- 学术史立场/分歧/遮蔽图；
- 未决问题和负面结果账本；
- 一名主 Agent + 有界的来源批判/反方评审角色。

验收：教授与 Agent 围绕一个候选解释完成一轮有证据的支持、反驳、修改和决定，后续会话可恢复。

### M10｜Translation, Drafting, Citation and Review

- 适配 Bookflow 翻译 provider/cache，输入限定为已验收块；
- 已冻结证据驱动的大纲与段落写作；
- 段落到 Claim/Evidence 的反向追踪；
- 引用样式、Zotero/BibTeX/RIS、DOCX/Markdown；
- 独立评审、作者答辩和版本差异。

验收：由小型冻结包生成一段正式试写和正确注释，经评审后修改，原文、译文、页码和论证边界可审计。

### M11｜Long-term Memory, Desktop Packaging and Evaluation

- historical-memory 与 codex-memory adapters；
- 记忆候选、人工提升和来源回链；
- Tauri 打包、Windows Credential Manager、项目迁移/备份；
- 成本/调用量、故障恢复和隐私检查；
- PDF、检索、证据、讨论、写作全链路 benchmark。

验收：安装后的桌面应用完成第一可用版本闭环，并在真实项目副本上通过回归评测。

## M5 后的优先级规则

1. 当前使用中最影响研究可信度的问题；
2. 打通纵向闭环所缺的能力；
3. 已有两次真实需求的复用点；
4. 界面美化和广泛 connector 数量。

任一里程碑若证明产品假设错误，先调整路线图和 ADR，不为了追赶编号继续扩张。
