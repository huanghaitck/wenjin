# M4 Task Spec｜Agent Workspace Foundation

状态：已授权  
日期：2026-08-09

## 目标

在现有 M1-M3 项目上实现最小的、可恢复的 Research Codex Agent 工作空间。用户可以创建研究
对话，选择模型角色，让一个主 Agent 读取项目/来源状态，并在保存研究札记前等待人工审批。

## 允许修改

- `src/research_workbench/` 中与数据库、Agent runtime、模型、CLI、loopback API 和现有 Web UI
  直接有关的文件；
- `tests/` 中 M4 测试；
- 本项目文档、环境示例和包元数据；
- 数据库 schema v3 及从 v1/v2 的前向迁移。

## 必须实现

1. thread/message/goal/run/run-event/tool-call/approval/model-profile/model-assignment 持久化；
2. 明确状态转换和有序事件序列；
3. deterministic mock 模型；
4. OpenAI-compatible 与 Ollama 文本调用，缺配置时显示 unavailable；
5. 主 Agent 的最小 tool-calling loop；
6. 三个只读工具：项目状态、来源列表、页面读取；
7. `save_research_note` 写工具，在执行前暂停；用户可以编辑输入并批准或拒绝；
8. CLI/API：创建线程、发消息、查看/继续 Run、审批；
9. GUI：线程列表、对话、模型角色、Run 时间线、审批卡，并保留 M2/M3 页面修复能力；
10. 重启/重新连接后从数据库恢复线程和等待审批；
11. M1-M3 回归测试保持通过。

## 不实现

- 联网搜索、网页浏览和数据库登录；
- Evidence Item、Claim 或冻结；
- 长期记忆写入；
- 翻译、正式论文写作、引用样式和 DOCX；
- 多 Agent 并行、自动模型 fallback、通用插件系统；
- Tauri 打包或 Bookflow 代码拷贝。

## 审批语义

- 只读工具可以直接执行，但仍记录 tool call；
- `save_research_note` 创建 approval 后 Run 进入 `WAITING_FOR_APPROVAL`；
- 批准时允许用户修改待保存内容，随后恢复同一 Run；
- 拒绝不写文件，Run 收到结构化拒绝结果后给出最终说明；
- 待审批对象和恢复点必须在应用重启后存在；
- 重复提交同一决定不得重复写入札记。

## 验收场景

1. 创建项目或打开已有项目；
2. 创建 thread，并把 `main_reasoning` 指向 mock 或已配置模型；
3. 发送“查看当前来源和异常，并把结论保存为研究札记”；
4. Agent 调用只读工具，返回基于项目状态的草稿；
5. GUI 显示待审批札记，用户编辑后批准；
6. 札记写入 `research/notes/`，事件记录原提案、人工修改和最终文件引用；
7. 在等待审批时重启服务，仍可完成第 5-6 步；
8. 所有 provider/key 信息未进入项目数据库、API 响应、日志或 Git；
9. 完整测试套件通过。

## 验证命令

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench python scripts\assert_environment.py
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench python -m unittest discover -s tests -v
```

真实 provider 测试是有界集成检查，不是 M4 离线验收前提，也不得打印或保存密钥。
