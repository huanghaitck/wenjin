# D3 Migration Plan｜Library, Document Editor and Research Browser

状态：方案已批准；D3 Demo 实施中
日期：2026-08-10

## 1. 迁移目标

在不丢失 D1/D2 项目、页面修复、线程、证据冻结和稿件版本的前提下，把当前功能重组为研究对话、
研究图书馆、文章工作台和项目设置四个稳定工作空间。迁移采用 additive-first：先增加新对象和兼容
读取，再切换写入，最后在验收后停止旧路径；不原地破坏旧表。

## 2. 当前问题与目标归属

| 当前对象或入口 | 当前问题 | 目标归属 |
|---|---|---|
| 顶栏 PDF 文件框、导入按钮 | 全局工具暴露，绕过收件箱概念 | 图书馆收件箱；对话拖放作为快捷入口 |
| 顶层“文献修复” | 把文献级动作误当工作空间 | 图书馆的 FileVersion 文献详情 |
| 项目库中的 Page/Block/Repair | 同一文件跨项目可能重复处理 | Library DocumentProcessingRevision |
| 项目 Source | 混合文件身份、处理结果和研究资格 | ProjectSourceLink + 项目资格/阅读状态 |
| Markdown 章节文本框 | 难以表达脚注、批注、修订和复杂结构 | Structured Manuscript Document Model |
| 外开浏览器回执 | 页面与对话、收件箱割裂 | 中央 Browser Tab + 右侧研究收集栏 |
| 独立对话和稿件编辑 | 灵感讨论缺少选区和版本锚点 | Context-bound Research Dialogue |

## 3. 数据模型迁移

### 3.1 Library Store v2

在独立图书馆数据库中增量加入：

- `document_processing_revisions`：绑定精确 `file_version_id`、解析器/模型、输入哈希和状态；
- `document_pages`：物理页、印刷页候选、图像与页面 Markdown 路径；
- `document_blocks`：块顺序、类型、区域、机器文本和当前人工文本；
- `document_relations`：阅读顺序、跨页续接和图文关系；
- `document_anomalies`、`document_repairs`、`ocr_proposals`；
- `library_access_policy`：workspace/private scope、取得方式、许可说明、访问到期和下载限制。

原文件继续原地只读索引或复制到明确目录；Library Store 只保存路径、哈希、元数据和派生产物引用，
不把大二进制塞入 SQLite。

### 3.2 Project Store v6（拟定）

增量加入：

- `project_source_links`：项目到 Work/Edition/FileVersion/ProcessingRevision 的引用；
- `project_source_qualifications`：相关性、阅读状态、引用资格和项目备注；
- Evidence 增加外部 processing revision、page、block 锚点；
- `object_tabs` / `workspace_layout_state`：可恢复的当前研究对象；
- `thread_context_bindings`：对话到稿件、章节、选区、来源页、浏览器会话的版本化绑定；
- 稿件文档树、节点、脚注、引用、批注与修订提案；
- DOCX/Markdown import-export receipt 与 fidelity report。

跨 SQLite 引用只保存稳定 ID 和快照，不依赖 SQLite 外键跨库工作。Evidence Freeze 继续保存完整来源
版本快照，避免图书馆当前表示变化后旧论证失去可审计性。

## 4. 现有数据迁移算法

### Phase 0｜只读盘点与备份

1. 记录项目 schema、图书馆 schema、数据库哈希和项目路径；
2. 复制数据库和 `project.yaml` 到带时间戳的本地备份目录；
3. 统计 Source、SourceVersion、Page、Block、Repair、Evidence、Freeze、Manuscript 和 Thread 数量；
4. 若原项目处于待审批 Run，暂停迁移；
5. 生成 migration manifest，不修改任何业务表。

### Phase 1｜界面兼容层，不迁数据

1. 建立四个永久入口和中央对象标签页；
2. 把顶栏 PDF 导入转发到图书馆收件箱 API；
3. 把现有文献修复页面嵌入具体来源详情；
4. 旧 URL 继续可用，并显示迁移提示；
5. 此阶段可单独回滚，不触碰数据库。

### Phase 2｜建立 Library Processing 对象

1. 对每个现有 Project Source 查找 `source_library_links`；
2. 已连接图书馆的来源：以精确 library file version 建立 processing revision；
3. 未连接的项目来源：建立 `private` 图书馆记录，不自动与相似作品合并；
4. 复制 Page/Block/Relation/Anomaly/Repair/OCR 元数据到 Library Store v2；
5. 页面图和 Markdown 保持原路径或复制到版本化派生目录，记录哈希；
6. 逐对象比较计数、文本哈希、物理页和修复记录；
7. 旧项目表保持只读，不立即删除。

### Phase 3｜切换项目引用

1. 为每个现有 Source 建立 `project_source_link`；
2. Evidence 增加 processing/page/block 外部引用和冻结快照；
3. 读取优先新对象，找不到时回退旧表并记录兼容命中；
4. 新修复只写 Library Processing Revision；项目研究判断仍写 Project Store；
5. 至少完成一次跨两个项目共享同一处理版本的测试后，才停止旧页面写入。

### Phase 4｜稿件文档模型

1. 将当前 Manuscript/Section/SectionVersion 转为文档树；
2. 每个章节、段落、脚注和引用分配稳定节点 ID；
3. 原 Markdown 作为 import snapshot 永久保留；
4. 比较纯文本、标题顺序、脚注标记、数字和 Evidence 引用；
5. DOCX 导入首先只支持受控功能集，未知结构进入 fidelity warning；
6. DOCX/Markdown 导出均从文档树生成，不互相串联转换。

### Phase 5｜上下文对话与浏览器标签

1. 文章侧栏消息绑定当前文档版本、章节和选区快照；
2. 旧线程保持 project scope，不伪造缺失的历史选区；
3. 浏览器中央标签绑定 domain/session/action scope；
4. 下载进入收件箱，保存 URL、访问时间、许可说明和响应/文件哈希；
5. 页面提示注入、跨域、下载和提交动作保持审批门禁。

### Phase 6｜停用旧路径

只有满足以下条件才停止兼容读取：

- 新旧对象计数与关键哈希核对通过；
- 现有 D1/D2 回归测试与新增迁移测试通过；
- 真实 HistRA PDF、一次人工修复、一个 Evidence Freeze 和一篇稿件往返成功；
- 用户确认新界面能找到原项目、原页、修复、线程和稿件；
- 备份恢复演练成功。

旧表至少保留一个发布周期。删除旧表需要新的显式批准，不属于 D3 默认范围。

## 5. 文章工作台布局

```text
┌──────────────┬──────────────────────────────────┬──────────────────────┐
│ 稿件与大纲   │ 结构化文档画布                   │ 研究侧栏             │
│ 章节/版本    │ 当前章节、脚注、图片、表格       │ 对话/证据/引用       │
│ 文件/导出    │ 批注、修订、页面预览             │ 批注/审批/版本       │
└──────────────┴──────────────────────────────────┴──────────────────────┘
```

研究侧栏可以折叠或调整宽度。用户选中文字后发起讨论，消息记录选区节点和文本快照。Agent 的建议先
成为批注、Writing Proposal、Claim Candidate 或 Research Note，不能直接进入批准正文。

## 6. 容易遗漏但必须纳入验收的问题

### 研究语义

- 证据回链与书目脚注不是同一对象：一个脚注可包含背景文献，一个 Evidence 必须回到核验页；
- 物理页、印刷页和 DOCX 页面编号必须分开；
- 一个项目可以有多篇论文、书稿章节和会议稿，不把 Project 等同于单篇 Manuscript；
- 同一材料的不同译文、版本和转引关系不能因书名相似自动合并；
- 写作触发的新缺口应生成补证票，而不是让模型临时扩大检索范围。

### 编辑器可靠性

- 自动保存、撤销/重做、崩溃恢复和版本恢复；
- 脚注重排、交叉引用、图片题注、表格和中文标点；
- DOCX 复杂样式、域代码、批注、修订、尾注和嵌入对象的有损提示；
- 字体缺失与不同 Word/LibreOffice 渲染差异；
- 大文档分节加载，避免每次向模型发送全文。

### 权限与隐私

- 工作区共享材料和项目私有材料的可见性；
- 授权数据库文件的许可、访问到期和二次使用限制；
- 浏览器 Cookie、密码、令牌和未脱敏网络日志不进入项目；
- 远程模型只接收用户明确选中的章节、页块和必要上下文。

### 迁移与运维

- 数据库迁移中断后的幂等恢复；
- 两个项目同时引用同一处理版本时的写锁和修订冲突；
- Library 文件移动、离线磁盘和精确旧字节不可用；
- 索引重建、备份、恢复和旧版本应用拒绝打开新 schema；
- 所有迁移结果提供人类可读报告，不仅是“成功/失败”。

## 7. 实施顺序与门禁

建议分成五个可撤回提交：

1. 客户端导航与旧 API 兼容，不迁数据；
2. 图书馆收件箱和文献详情归位；
3. Library Processing 数据迁移；
4. 结构化文章编辑器与 DOCX/Markdown adapters；
5. 上下文研究侧栏和中央浏览器标签。

用户已于 2026-08-10 授权制作可用 Demo。当前实施 Phase 1、Phase 4 的受控文档子集与 Phase 5
上下文绑定；旧表和旧 API 保持兼容。真实 Library Processing 跨库迁移留待独立验收，不在本轮移动
或覆盖真实项目数据。
