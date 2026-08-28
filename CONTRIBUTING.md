# Contributing

欢迎提交Issue和Pull Request。问津处理的往往是未公开研究材料，因此贡献代码时不得附带私人PDF、项目数据库、API Key、Cookie、登录截图、绝对用户路径或完整研究对话。

## Development checks

```powershell
python -m unittest discover -s tests -v
node --check src/research_workbench/web_assets/app.js
npm ci
cargo check --locked --manifest-path src-tauri/Cargo.toml
```

新功能应保持以下边界：

- 原文件默认只读；
- 自动分类、OCR、翻译和模型输出均为候选；
- 证据采用、正文写入、记忆提升和外部提交保留人工决定；
- 项目代码与领域插件分离；
- 插件不能绕过来源、证据、版本和审批门禁。

提交前请运行`git diff --check`，并确认没有秘密、构建产物或个人研究资料进入Git。
