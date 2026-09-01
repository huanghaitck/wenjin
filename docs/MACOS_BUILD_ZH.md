# 问津 macOS 构建说明

当前流水线面向 Apple Silicon（M1 及以后）生成 `.app` 与 `.dmg`。构建使用 GitHub Actions 的 macOS runner，应用继续内置问津 Python sidecar 和受控浏览器组件，目标电脑不需要另装 Python 或 Node.js。

## 构建

在 GitHub 仓库的 **Actions → macOS unsigned build → Run workflow** 手动触发。成功后，从该次运行的 Artifacts 下载 `wenjin-0.1.4-macos-arm64-unsigned-test`。

## 当前签名状态

没有 Apple Developer 凭据时，流水线使用 ad-hoc 签名，只用于测试。首次打开仍可能被 Gatekeeper 拦截，需要用户在“系统设置 → 隐私与安全性”中手动允许。

要面向普通用户免提示分发，仍需 Developer ID Application 证书和 Apple 公证凭据。取得凭据后再为流水线增加正式签名与公证，不应绕过 Apple 的信任链。
