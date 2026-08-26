# Third-party notices
问津本身采用 `AGPL-3.0-only`。本文件记录0.1.1直接使用或随安装包分发的主要第三方组件；各组件仍受其自身许可证约束。精确版本以`pyproject.toml`、`package-lock.json`、`Cargo.lock`和实际发布构建清单为准。

## Python runtime

| Component | Use | License | Upstream |
| --- | --- | --- | --- |
| PyMuPDF / MuPDF | PDF读取、文字坐标与页面渲染 | AGPL-3.0或Artifex商业许可 | https://pymupdf.readthedocs.io/ |
| python-docx | DOCX导入导出 | MIT | https://github.com/python-openxml/python-docx |
| Model Context Protocol Python SDK | MCP客户端与服务端 | MIT | https://github.com/modelcontextprotocol/python-sdk |
| certifi | HTTPS CA证书集合 | MPL-2.0 | https://github.com/certifi/python-certifi |
| qrcode 8.2 | 本地生成微信登录二维码SVG | BSD-3-Clause | https://github.com/lincolnloop/python-qrcode |
| Pydantic | 数据验证 | MIT | https://github.com/pydantic/pydantic |
| AnyIO | 异步运行支持 | MIT | https://github.com/agronholm/anyio |
| jsonschema | JSON Schema验证 | MIT | https://github.com/python-jsonschema/jsonschema |
| PyInstaller | Windows侧车打包 | GPL-2.0-or-later，并适用PyInstaller Bootloader Exception | https://pyinstaller.org/ |
| agent-browser 0.33.0 | 可见受控浏览器自动化运行时 | Apache-2.0 | https://github.com/vercel-labs/agent-browser |
| uiautomation 2.0.29 | Windows UI Automation与控件树 | Apache-2.0 | https://github.com/yinkaisheng/Python-UIAutomation-for-Windows |
| comtypes 1.4.16 | Windows COM接口 | MIT | https://github.com/enthought/comtypes |
| Tencent openclaw-weixin 2.4.6 | 腾讯iLink微信扫码、长轮询与消息协议的兼容实现参考 | MIT | https://github.com/Tencent/openclaw-weixin |

PyMuPDF官方说明其开放源码许可为AGPL，同时提供商业许可。问津0.1.1选择AGPL-3.0-only发布，不声称获得Artifex商业许可。

## Desktop runtime and build chain

| Component | Use | License | Upstream |
| --- | --- | --- | --- |
| Tauri | 桌面壳与WebView集成 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri |
| Microsoft Edge WebView2 Runtime | Windows桌面WebView运行时；独立安装程序只收入完整离线ZIP | Microsoft Software License Terms | https://developer.microsoft.com/microsoft-edge/webview2/ |
| Tauri CLI | 桌面构建 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri |
| tauri-plugin-shell | 受控桌面命令 | Apache-2.0 OR MIT | https://github.com/tauri-apps/plugins-workspace |
| rfd | Windows文件与目录选择器 | MIT | https://github.com/PolyMeilex/rfd |
| windows-sys | Windows API绑定 | Apache-2.0 OR MIT | https://github.com/microsoft/windows-rs |
| Cytoscape.js 3.34.1 | 书目与内容知识图谱交互渲染 | MIT | https://github.com/cytoscape/cytoscape.js |
| cytoscape-fcose 2.2.0 | Obsidian式力导向布局，使关系紧密的作品自然聚集 | MIT | https://github.com/iVis-at-Bilkent/cytoscape.js-fcose |
| cose-base 2.2.x / layout-base 2.x | fCoSE布局基础算法 | MIT | https://github.com/iVis-at-Bilkent |

Node.js和Rust只属于源码构建链；普通用户运行安装包不需要另装Node.js、Rust或Python。

Windows安装包只携带`agent-browser`的Windows原生可执行文件，不携带npm包装器或Node.js。普通安装包在WebView2缺失时调用微软引导程序；完整离线ZIP另附微软WebView2独立安装程序。可见研究浏览器仍优先调用系统Microsoft Edge或用户明确指定的兼容Chrome/Chromium；问津不会替换默认浏览器。

## Architecture and interaction references

问津的0.1架构与交互曾参考以下开源项目，但没有直接复制或内置其源码：

- NousResearch/hermes-agent（MIT）：模型服务、辅助任务路由、Mixture of Agents与可编辑Soul概念；
- badlogic/pi-mono（MIT）：provider、Agent循环、工具、状态与界面的分层；
- openai/codex（Apache-2.0）：线程事件、审批、Skills、MCP与app-server边界；
- Model Context Protocol specification：prompts、resources、tools和控制边界。

`src/research_workbench/weixin_gateway.py`依据Tencent `openclaw-weixin` 2.4.6（上游提交`cef0bfc390393f716903e16d50408118047f87e0`）公开的iLink请求结构和登录状态实现了问津自有Python网关，并修改了运行方式、凭据存储、权限与消息路由。问津不内置OpenClaw宿主，也不通过Hermes转发。腾讯MIT许可证全文见`licenses/Tencent-openclaw-weixin-MIT.txt`；Cytoscape.js MIT许可证全文见`licenses/cytoscape-MIT.txt`。

问津内置`Historical Research Skill Pack 0.3.0`，来源为`huanghaitck/historical-research-codex-plugin`，按Apache License 2.0再分发。完整Apache许可证与NOTICE随Skill Pack源码和安装包保留。问津自身继续采用AGPL-3.0-only；内置Skill Pack文件不因此改变其原有Apache-2.0许可。

如果以后内置、复制或修改第三方源码，必须在本文件补充精确版本、文件范围、修改说明和许可证文本，不能只以“参考设计”代替许可义务。

## Domain plugin data

领域插件可以携带与软件代码不同许可证的数据包。具体许可、来源、版本、哈希与引用要求由每个独立领域包自行声明，不因安装到问津而改用AGPL。
