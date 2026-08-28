# Security policy

## Supported version

问津目前处于0.1.x公开预览阶段，只维护最新发布的0.1.x版本。

## Reporting a vulnerability

请优先使用GitHub仓库的 **Security → Report a vulnerability** 私密报告入口，不要在公开Issue中发布API Key、Cookie、登录截图、私人文献、项目数据库或可复现的敏感数据。

报告应尽量包含：受影响版本、最小复现步骤、预期与实际行为、是否涉及本地文件、凭据、网络请求或插件边界。维护者确认问题前，请不要公开利用细节。

## Security boundaries

- 问津只监听本机回环地址；
- API Key应存入Windows凭据管理器，不应进入源码或项目数据库；
- 插件没有直接写入正式证据表的权限；
- 登录数据库、验证码、付费和提交行为需要研究者本人操作；
- 项目、图书馆、备份和长期记忆可能包含未公开研究资料，不应随Issue或错误日志上传。
