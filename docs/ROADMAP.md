# Historian Research Codex｜实施路线图

状态：2026-08-09 冻结，使用反馈可通过 ADR 调整。

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

## 已授权的下一阶段

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

### M5｜Open Research Retrieval

- OpenAlex 与 Crossref connector；
- query plan、检索范围和停止条件；
- Retrieval Record、结果去重、零结果和限流状态；
- 在对话中查看、筛选并把结果登记为 `DISCOVERED`；
- 公开 URL/PDF 的有界取得、哈希与来源登记；
- Zotero 本地只读探测作为可选能力。

验收：一次对话产生可复现的检索记录，取得一份公开文件并进入 M1 来源登记；搜索结果本身不具备
引用资格。

### M6｜Authenticated Research Browser

- 专用 headed research profile；
- accessibility/DOM/screenshot 的受控页面读取；
- domain、session、action scope；
- 下载/提交/批量动作审批；
- 用户选择后附着现有浏览器标签页的高级模式；
- 浏览检索收据与下载哈希；不保存 Cookie、密码和未脱敏 HAR。

验收：用户亲自登录一个授权数据库，Agent 在允许域内执行有界检索并下载用户有权访问的文件；
关闭应用后凭证未进入项目或 Git。

### M7｜Evidence and Claim Freeze

- 来源资格状态链；
- Evidence Item 与原页/区域锚点；
- Claim、ClaimLink、反证和来源独立性；
- 原文/译文并排核验；
- 教授批准的 evidence freeze；
- 冻结包差异和回退票。

验收：从 M2 页面固定一条证据、连接一个主张、记录一个竞争解释并经人工冻结；每项可回到原页。

### M8｜Scholarly Dialogue and Historiography

- 研究问题与范围对象；
- 有来源的 seminar thread；
- 学术史立场/分歧/遮蔽图；
- 未决问题和负面结果账本；
- 一名主 Agent + 有界的来源批判/反方评审角色。

验收：教授与 Agent 围绕一个候选解释完成一轮有证据的支持、反驳、修改和决定，后续会话可恢复。

### M9｜Translation, Drafting, Citation and Review

- 适配 Bookflow 翻译 provider/cache，输入限定为已验收块；
- 已冻结证据驱动的大纲与段落写作；
- 段落到 Claim/Evidence 的反向追踪；
- 引用样式、Zotero/BibTeX/RIS、DOCX/Markdown；
- 独立评审、作者答辩和版本差异。

验收：由小型冻结包生成一段正式试写和正确注释，经评审后修改，原文、译文、页码和论证边界可审计。

### M10｜Long-term Memory, Desktop Packaging and Evaluation

- historical-memory 与 codex-memory adapters；
- 记忆候选、人工提升和来源回链；
- Tauri 打包、Windows Credential Manager、项目迁移/备份；
- 成本/调用量、故障恢复和隐私检查；
- PDF、检索、证据、讨论、写作全链路 benchmark。

验收：安装后的桌面应用完成第一可用版本闭环，并在真实项目副本上通过回归评测。

## M4 后的优先级规则

1. 当前使用中最影响研究可信度的问题；
2. 打通纵向闭环所缺的能力；
3. 已有两次真实需求的复用点；
4. 界面美化和广泛 connector 数量。

任一里程碑若证明产品假设错误，先调整路线图和 ADR，不为了追赶编号继续扩张。
