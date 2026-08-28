---
name: historical-research-router
description: 识别学术性历史研究请求并选择最小技能组合。仅在历史对象与史学操作同时出现时使用；排除 Git 或浏览历史、软件日志、普通编程、当前新闻、商业调研、历史小说和通用润色。自动识别只进入模块模式；完整项目、多 Agent、批量下载、长稿和长期记忆必须另获明确授权。
---

# 史学研究路由

先完整读取 [核心政策](../../references/core-policy.md)。

## 路由

1. 检查请求是否同时包含历史对象和史学操作；不满足时停止使用本插件。
2. 默认采用模块模式，只选能够完成请求的最少技能。
3. 用户明确启动完整史学项目或批准下一门禁时，转交 `historical-project-workflow`。
4. 读取被选技能的 `SKILL.md` 后再行动，不要凭技能名称猜流程。

按下列顺序判断：

- 找材料、开放全文、数据库题录或人工获取清单：`historical-literature-search`。
- 验收已有文件：`historical-material-intake`。
- 阅读已验收语料：`historical-corpus-reading`。
- 版本、母本、转引或证词独立性：`historical-source-criticism`。
- 问题与边界：`historical-question-and-scope`。
- 学术史：`historical-historiography`。
- 竞争解释与反证：`historical-explanation-testing`。
- 论证与结构：`historical-argument-planning`。
- 正式写作前冻结：`historical-evidence-freeze`。
- 按指定中文史学格式插入、改写或补齐脚注与尾注：`historical-citation-insertion-zh`。
- 唯一正式稿：`historical-drafting`。
- 学术评审与返修：`historical-review-and-revision`。
- 稳定稿中文返修：`historical-prose-revision-zh`。
- 投稿前终审：`historical-final-audit`。

输出路由决定、技能顺序、所需授权和停止点。不要用路由技能代替专业技能完成研究。
