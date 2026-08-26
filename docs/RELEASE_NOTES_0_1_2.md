# 问津 0.1.2 更新说明 / Wenjin 0.1.2 Release Notes

## 中文

0.1.2集中修复研究图书馆与书目关系图谱。作品、版本、文件位置和精确文件版本仍分别保存；本次更新不移动、改名或删除用户原始文件。

### 主要变化

- **更可靠的书目题名。** 入库时以清洗后的文件名为主，纯编号或哈希文件名才使用文档内嵌题名。制作软件不再被误认成作者、出版社或出版年。
- **作品级去重。** 相同题名且能够判定为同一作品的文件并入一条作品记录，同时保留多个文件位置、版本和当前文件指纹。
- **读书笔记单独管理。** 新增“读书笔记”书架；读书报告、阅读札记和课程阅读作业不参与书目关系图谱。
- **Obsidian式自由图谱。** fCoSE力导向布局把有关系的作品聚集成簇，孤立作品散布外围，不再强制排成网格。
- **关系更克制。** 图谱只显示作品节点。关系线包括同作者、同出版社、同期刊、同年代（十年）及有向的引用、材料使用、评述、翻译和提及。
- **Markdown自动建立文献关系。** 脚注、尾注和参考文献中的精确登记题名自动记为引用；正文精确题名记为提及；明确的翻译、评介和材料使用措辞建立相应有向关系。误匹配仍可排除。
- **完整交互。** 支持滚轮缩放、拖动空白处或中键平移、悬停题名、单击聚焦相邻作品、双击打开书目卡，以及搜索后的局部子图。

### 发布验证

- 395项自动测试全部通过；
- `npm audit`未发现高危漏洞；
- Python侧车烟雾测试、Rust/Tauri检查和Windows NSIS安装程序构建通过；
- 公开目录未发现API密钥、Cookie、私人研究语料或领域Agent私有发行包。

### 下载

- `wenjin-0.1.2-x64-setup.exe`：Windows 10/11 x64安装程序；
- `wenjin-0.1.2-win64-complete.zip`：含安装程序、双语文档和WebView2离线安装程序；
- `wenjin-0.1.2-agpl-source.zip`：AGPL-3.0-only源码包。

安装程序仍未代码签名，也没有自动更新服务。请只从GitHub Release下载。macOS版本尚未发布。

## English

Wenjin 0.1.2 focuses on the research library and bibliographic relationship graph. Works, editions, file locations, and exact file versions remain separate. The update does not move, rename, or delete source files.

### Highlights

- Filename-first bibliographic titles with conservative fallback for identifier-only filenames.
- Removal of software-generated author, publisher, and year metadata.
- Work-level deduplication while preserving file locations and exact versions.
- A separate Reading Notes shelf excluded from the bibliographic graph.
- An Obsidian-like fCoSE force layout with clustered related works and scattered isolates.
- Work-only graph nodes with typed colors and relations for shared authors, publishers, journals, decades, citations, material use, reviews, translations, and mentions.
- Automatic traceable literature relations from page-linked Markdown, with optional false-match exclusion.
- Wheel zoom, background or middle-button pan, hover labels, neighbor focus, double-click bibliography cards, and filtered subgraphs.

### Verification

- 395 automated tests passed.
- `npm audit` reported no high-severity vulnerabilities.
- The Python sidecar smoke test, Rust/Tauri checks, and the Windows NSIS build passed.
- The public release tree contains no API keys, cookies, private research corpora, or private domain-Agent packages.

The installer remains unsigned and has no automatic updater. Windows 10/11 x64 is the supported platform for this release.
