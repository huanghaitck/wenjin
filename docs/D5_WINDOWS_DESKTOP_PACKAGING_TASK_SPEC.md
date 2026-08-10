# D5 Task Spec｜Windows Desktop Packaging and Practical Bridges

状态：已授权，实施中
日期：2026-08-10

## 目标

把当前回环网页 Demo 交付为一个可安装、可启动、可卸载的 Windows 桌面 Demo，并补齐真实使用
所需的本机文件、Microsoft Word 和模型角色配置入口。

## 可观察范围

1. 构建 Tauri 2 Windows 桌面壳和 PyInstaller Python sidecar；
2. 首次启动在本机应用数据目录建立默认 workspace、library 和示例项目；
3. 桌面壳管理 sidecar 启停，界面不要求用户打开命令行；
4. 图书馆可用系统目录选择器选择散落文献目录，原文件保持只读；
5. PDF/DOCX 可用系统文件选择器导入现有入口；
6. 文章工作台可导出 Word、在 Microsoft Word 打开精确导出文件、再把人工修改稿导入为新修订；
7. 设置页可配置主推理、视觉/OCR、翻译三个模型角色，支持 Ollama 与 OpenAI-compatible；
8. API Key 只进入 Windows Credential Manager，所有公开状态只返回 `has_secret`/credential ref；
9. 设置页完整显示客户端版本、sidecar 版本、项目 schema、模板版本和生效模型；
10. 使用用户提供的《历史研究》DOCX 核验预设规则，未完成时明确显示待核状态。

## 完成标准

- 新环境无需 Python 即可从安装后的快捷方式启动；
- sidecar 健康检查失败时显示可理解的启动错误，不出现空白窗口；
- 关闭桌面窗口后，本次启动的 sidecar 不残留；
- 选择目录只建立盘点预览，不移动或改写原文件；
- 选择 DOCX 后可导入，导出 DOCX 可由 Microsoft Word 打开；
- Word 修改稿重新导入后产生新修订和保真报告，旧修订仍存在；
- 模型设置保存后无需修改项目文件即可刷新角色状态；
- 远程模型密钥不出现在项目 SQLite、配置 JSON、日志、API 响应或 Git；
- Python 全量测试、Rust 编译检查、sidecar 独立启动、安装包构建和安装后启动检查通过；
- 产出至少一个 NSIS 安装包和一个可直接运行的桌面可执行文件。

## 明确不做

- 把 Microsoft Word 窗口/COM 编辑器嵌入 WebView；
- 无损支持 Word 的全部批注、修订、域、宏、复杂对象和分页行为；
- 绕过数据库许可、验证码、付费墙或下载限制；
- 导入浏览器 Cookie、密码或现有登录会话；
- 代码签名证书、自动更新服务、Microsoft Store 发布；
- 同时实现后续完整学术史、大规模阅读调度和所有数据库连接器。

## 验收样本

- 当前 D4 示例项目和含真实脚注的示例稿件；
- 一个 HistRA PDF，用于系统文件选择与只读图书馆盘点；
- `D:\下载中转站\《历史研究》关于页面版式和引文注释的规定(1).docx`，用于模板核验；
- 本机 Microsoft Word；
- 本地 Ollama 文本模型，以及不实际保存远程密钥的接口状态测试。

## 提交顺序

1. ADR、任务说明和 gate；
2. Python 桌面启动、配置与测试；
3. Tauri 壳和本机桥接；
4. sidecar/安装包构建脚本；
5. 安装、启动、Word 往返和状态文档。

