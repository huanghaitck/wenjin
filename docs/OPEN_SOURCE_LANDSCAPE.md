# 开源与正式接口调研记录

调研日期：2026-08-09  
用途：决定哪些设计可以借鉴，哪些依赖暂不引入。版本与服务条款在实际接入前需再次核验。

## 1. PDF 与文档结构

| 项目/标准 | 可借鉴能力 | V1 决定 |
|---|---|---|
| [Docling](https://github.com/docling-project/docling) | 页面布局、阅读顺序、表格及统一文档对象；可替换 PDF backend | 后续作为解析提案器评测，不替换 M2 页面与人工门禁 |
| [MinerU](https://github.com/opendatalab/MinerU) | PDF 到 Markdown/JSON、OCR 与复杂版面 | 作为中文与扫描材料候选；必须保留原页哈希和异常比较 |
| [GROBID](https://github.com/grobidOrg/grobid) | 学术论文元数据、参考文献、脚注/引文标记及 TEI | 适合现代论文的书目解析；不作为历史书籍通用正文真相 |
| [IIIF APIs](https://iiif.io/api/) | 图书馆/档案馆的 manifest、画布、图像和内容搜索互操作 | 作为数字档案来源连接器和页图锚点优先标准 |

结论：解析器之间不是胜者替换关系。M2 的 page/block/relation 模型和人工修正记录是稳定层，
第三方解析器只提交带 provenance 的候选。

## 2. 研究 Agent

| 项目 | 可借鉴能力 | 不直接照搬的部分 |
|---|---|---|
| [STORM / Co-STORM](https://github.com/stanford-oval/storm) | 多视角提问、协作式知识整理和人机讨论 | 目标偏百科报告；历史研究讨论必须保留史料层级和教授决定 |
| [PaperQA2](https://github.com/future-house/paper-qa) | 元数据感知检索、重排、带页码/来源回答、矛盾发现 | 科学文献 RAG 不能替代版本批判、原页核验和史料独立性 |
| [Open Deep Research](https://github.com/langchain-ai/open_deep_research) | 模型与搜索工具可配置、研究计划、人工反馈和评测 | 不引入完整 LangGraph；检索报告不能自动成为证据包 |
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | 本地/网页研究与可插拔模型 | 不采用“先生成完整报告”作为核心交付物 |
| [OpenHands](https://github.com/OpenHands/OpenHands) | 模型无关、事件驱动、工具循环、对话与 runtime 分离 | 不引入代码执行沙箱和开发者专用复杂度 |

结论：产品借鉴 Codex/OpenHands 的有状态工具工作区，借鉴研究 Agent 的搜索规划，但领域状态由
史学 harness 控制。默认一个主 Agent，专门角色只接有界任务。

## 3. 持久化与模型路由

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) 证明 checkpoint、
  replay 和 human-in-the-loop interrupt 是长任务的必要产品语义；M4 直接实现最小语义，不引入框架。
- [LiteLLM](https://docs.litellm.ai/) 提供大量 provider 的统一接口、路由和成本统计，但 V1 仅有
  OpenAI-compatible 与 Ollama 两个真实协议。先用薄适配器，避免自动 fallback 和额外网关进程。
- OpenAI Agents SDK 可以作为未来 provider/runner adapter，但模型可选是产品约束，因此不能成为
  核心领域模型。

## 4. 开放学术与文化遗产接口

优先级不是“数据库名气”，而是正式接口、字段可追溯、合法取得和历史学适用性。

| 接口 | 主要用途 | V1/M5 处理 |
|---|---|---|
| [OpenAlex API](https://developers.openalex.org/api-reference/introduction) | works、authors、sources、institutions、主题和引文关系 | 首批开放检索 connector |
| [Crossref REST](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | DOI 和出版元数据、更新/撤稿信息 | 首批 DOI/书目校验 connector |
| [Semantic Scholar API](https://www.semanticscholar.org/product/api) | 论文、作者、引文图及部分开放 PDF URL | 第二批；注意学科覆盖与限流 |
| [Zotero Web API](https://www.zotero.org/support/dev/web_api/) | 用户书目库、附件元数据和正式写入接口 | 本地库优先只读，写入需明确批准 |
| [IIIF](https://iiif.io/api/) | 数字书、手稿、地图的页序与图像 | 首批文化遗产 connector 基础 |
| [Library of Congress API](https://www.loc.gov/apis/) | 数字馆藏、item/resource/分页对象 | 第二批历史材料 connector |
| [Europeana APIs](https://www.europeana.eu/en/apis) | 欧洲文化遗产搜索、记录和 IIIF | 第二批，需要免费 API key |
| [HathiTrust Research Center](https://htrc.atlassian.net/wiki/spaces/COM/pages/43293057/HTRC+data+access) | 书目、公共领域及授权数据集 | 按机构协议接入，不假定全文可取 |
| [JSTOR Data for Research](https://about.jstor.org/whats-in-jstor/text-mining-support/) | 合规的文本分析数据集 | 独立授权流程，不通过网页自动化批量抓取 |

Google Scholar 等无稳定正式 API 的服务不作为首批程序化 connector。用户可在已登录浏览器中
手动/半自动检索，但必须保留查询收据，且不绕过服务限制。

## 5. 登录态浏览器

- [Playwright authentication](https://playwright.dev/docs/auth) 明确说明 storage state 可能包含可冒充
  用户的 Cookie/headers，不能进入仓库；
- [Browser Use](https://github.com/browser-use/browser-use) 展示了 CDP、可访问性树、视觉和域名限制
  的 Agent 浏览方式；
- [Chrome Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
  可让明确授权的扩展与本地应用通信，并通过 allowed origins 限定调用者；
- 本机 `agent-browser` 能提供持久 session、profile/CDP 和 MCP 工具，但复用已存在登录 profile 时
  无法同时获得同等级的域名 containment；HAR、截图和视频也可能泄露认证信息。

因此产品提供两条路径：默认使用专用 research browser profile；高级模式才附着用户现有浏览器，
只接管用户选定标签页并逐项批准敏感动作。任何路径都不向模型暴露 Cookie 或密码。

## 6. 本地现有资源

- Bookflow：可适配 React/Tauri 外壳、snapshot/event bridge、provider registry、Windows Credential
  Manager 和翻译缓存；不得通过 sibling path 运行时耦合，也不复制其翻译状态机；
- HistRA-Bench：提供真实历史材料、证据固定和直接引文评测经验；只作为授权测试来源；
- historical-research plugin：提供阶段门禁、来源状态、证据冻结和审评契约；
- historical-memory / codex-memory：保持领域记忆与工程记忆的职责边界，通过 adapter 使用。

## 7. 暂不引入的依赖

- 通用 Agent 编排框架；
- 通用 LLM proxy；
- 向量数据库、图数据库、消息队列；
- 浏览器云或托管登录态；
- 自动抓取受限数据库的第三方服务。

只有出现第二个真实调用者、现有薄层无法满足评测或维护成本更低时，才通过 ADR 引入。
