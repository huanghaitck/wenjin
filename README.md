# 问津｜人文社会科学研究工作台

[English](README_EN.md) | 中文

问津是一个本地优先、模型可选、面向人文社会科学研究过程的 Agent 工作台。它把研究对话、个人图书馆、原页清洗、联网检索、证据固定、学术史、写作、Word 往返、Skills、CLI 与 MCP 组织在同一套可审计的项目数据上。

当前版本为 **0.1.1 Public Preview**，主要支持 Windows 10/11。

## 主要能力

- 本地项目、SQLite 自动备份和非覆盖恢复；
- 研究图书馆的作品、版本、文件与哈希分层；
- 只读目录盘点、建议分类、人工确认后批量入库；
- PDF 原页、文本块、跨页关系和人工修复；
- 可回到来源版本与页码的证据、史料长编和知识图谱；
- 主模型、辅助模型、Ollama、OpenAI 兼容接口与可选 MoA；
- 版本化研究人格、Skills、MCP、CLI 与 Codex 双向桥接；
- 随安装包内置16项`Historical Research Skill Pack 0.3.0`与最新证据保真中文史学语言返修Skill；
- 结构化文章工作台、脚注/参考文献、DOCX 导入导出和多角色评审；
- 中英文界面；史学长期记忆与工程长期记忆分层接入；
- 标准领域插件工程与本地 ZIP/目录安装入口。
- 问津自有的普通微信扫码私聊网关；不依赖Hermes或OpenClaw运行时。

## 安装

普通用户从[0.1.1发布页](https://github.com/huanghaitck/wenjin/releases/tag/v0.1.1)下载 `wenjin-0.1.1-x64-setup.exe` 并运行即可。安装包内包含桌面程序、Python侧车和`agent-browser 0.33.0` Windows原生运行时，运行时不需要另装Python、Node.js、PowerShell 7或Rust。Windows 10/11通常已有WebView2；缺失时普通安装包会调用微软引导程序。完整离线ZIP另含WebView2独立安装程序和`install-wenjin.cmd`，断网机器从该入口安装即可。研究浏览器优先使用系统Microsoft Edge；缺少Edge时可以在设置中指定兼容的Chrome/Chromium可执行文件。

当前安装包尚未代码签名，也没有自动更新服务；Windows 可能显示未知发布者提示。请只从项目发布页或维护者提供的校验链接下载，并核对 SHA-256。

## 图书馆盘点与入库

盘点与入库是两个动作：

1. 指定一个明确目录后，问津只读检查文件，生成题名、责任者、年代、材料类型、重复版本和建议书架；
2. 研究者可以批准当前页所选材料，也可以选择“按建议分类并批量入库”；
3. 入库只登记原路径、书目和精确文件版本，不移动、不改名、不修改原文件；
4. 自动分类属于整理建议，随时可以在书目详情中人工调整书架；
5. 入库不等于材料已经读完、可引用或成为正式证据。

当前书架包括原始史料、学术论文、学术专著、个人论文与稿件、工具书与目录、待分类。

## Agent权限

每个研究线程可以选择：

- **请求批准**：每个会改变电脑状态的动作逐项暂停；
- **帮我批准**：权限代理自动批准常规键鼠、窗口和可逆整理，程序启动与命令执行等敏感动作仍询问；
- **完全访问**：本次运行可以自动调用 Computer Use、文件、程序、命令和已安装领域包暴露的工具，并保存完整审计记录。

Computer Use 通过标准 MCP 领域包提供 Windows 控件树、截图、键盘、鼠标、程序启动和显式命令工具；浏览器后端另由 `agent-browser` 提供。密码控件、隐藏凭据提取、验证码求解和付款确认在三种模式下均不开放。

## 领域包

问津核心程序不绑定具体研究对象。领域包通过 `wenjin-plugin.json`、Skill、MCP运行时、本地数据接口和可选数据包扩展研究方法、字段规范、资料处理器、知识图谱适配器与Agent工具。

领域包可以从 GitHub Release、机构网站或其他分发位置取得。下载完成后，在“AI 与 Agent—领域包”中选择本地ZIP或解压目录安装；若领域包声明本地数据库，安装后再选择用户已有的SQLite、CSV或目录。问津记录路径和哈希回执，不复制或改写数据库。

仓库只提供中立的领域包工程框架和制作说明，不预装任何具体学科样例或用户数据。领域包可以携带独立的 Skill、MCP 工具、处理器、字段规范、图谱适配器以及获得合法授权的数据；大型数据与自运行包应在领域项目自己的 Release 或其他分发位置提供。

建立新插件：

```powershell
wenjin plugin-create my-domain-plugin --output .\plugins
```

详细规范见 [Wenjin Plugin SDK](docs/WENJIN_PLUGIN_SDK.md)。

## 源码开发

要求：Python 3.13、Node.js、Rust stable、PowerShell 7。

```powershell
conda env create -f environment.yml
conda activate historical-research-workbench
python -m unittest discover -s tests -v
node --check src/research_workbench/web_assets/app.js
npm ci
cargo check --manifest-path src-tauri/Cargo.toml
```

构建Windows安装包：

```powershell
& .\scripts\build_desktop.ps1
```

脚本优先使用`HRW_BUILD_PYTHON`、当前虚拟环境或Conda环境中的合格Python，也可以显式传入：

```powershell
& .\scripts\build_desktop.ps1 -PythonPath C:\path\to\python.exe
```

## CLI 与 MCP

```powershell
wenjin --help
wenjin mcp-server C:\Research\my-project --library-root C:\Research\library
hrw add-source C:\Research\my-project C:\Research\books\source.pdf
hrw ingest-pdf C:\Research\my-project SOURCE_ID
hrw serve C:\Research\my-project
```

MCP默认提供只读项目状态、来源、页面、图书馆和稿件结构。任何正式写入仍须经过问津的人工审批与版本门禁。

## 微信直连

“AI 与 Agent—连接器与 MCP”中的微信网关由问津直接连接腾讯 iLink。用户使用普通微信扫码后，问津把获准联系人的私聊文字送入当前本地项目和主 Agent，再把答复发回同一会话。机器人令牌只保存在 Windows 凭据管理器，不写入项目、配置文件或日志。

0.1.1 仅支持由对方发起的私聊文字消息。群聊、主动或定时推送、文件收发、付款、验证码代填均未开放。需要执行工具时仍服从“请求批准、帮我批准、完全访问”三档权限；等待审批的动作只会在微信中提示回到问津客户端处理。

## 数据、隐私与凭据

- 项目、图书馆、备份和记忆适配器默认保存在本机；
- API Key写入Windows凭据管理器，不进入项目数据库、浏览器快照或源码；
- 远程模型只接收研究者明确选择的页块、章节或选区；
- 登录数据库、验证码、付费和下载由研究者在合法权限内操作；
- `historical-memory`与`codex-memory`等私人记忆库不属于公开源码，也不会随安装包上传。

## 当前限制

- 安装程序未签名，无自动更新；
- DOCX往返不承诺保留复杂域、修订、批注和任意嵌入对象；
- 自动书目识别和书架分类只是候选，需要人工抽查；
- 已登录数据库不提供绕过验证码或访问控制的无人值守爬取；
- 内置模板在正式投稿前仍应核对期刊最新版要求。
- 微信网关当前只支持私聊文字回复，且上游iLink协议仍可能变化。

## 文档

- [中文使用手册](docs/USER_MANUAL_ZH.md)
- [English User Manual](docs/USER_MANUAL_EN.md)
- [领域包工程说明](docs/WENJIN_PLUGIN_SDK.md)
- [第三方声明](THIRD_PARTY_NOTICES.md)

## 许可证

问津源代码采用 [GNU Affero General Public License v3.0 only](LICENSE)，SPDX标识为 `AGPL-3.0-only`。

第三方软件及设计参考见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。领域插件所带数据可以使用独立于软件代码的许可证或使用声明，具体以插件包内文件为准。
