---
name: historical-material-intake
description: 对用户明确提供、上传、授权下载或项目配置中的历史材料进行文件验收、去重、版本关系识别、元数据登记和引用资格分级。处理 PDF、DOCX、图像、OCR、网页存档和 Zotero 条目时使用；不得扫描未授权目录，也不得把导入或 OCR 存在等同于全文已读。
---

# 史学材料导入

先完整读取 [核心政策](../../references/core-policy.md) 和 [史学证据契约](../../references/evidence-contract.md)。

## 验收

1. 确认材料入口获得授权，只处理明确路径、上传文件、批准下载或配置的 `source_roots`。
2. 记录稳定 ID、路径或 URL、SHA-256、字节数、页数、格式、文本层和可打开性。
3. 对 PDF 检查 `%PDF-`、非 HTML、页数、加密状态及代表页；关键扫描页用图像核验。
4. 区分原件、译本、重印、OCR、摘录、镜像和检索副本，标记共同母本。
5. 登记作者、题名、版本、形成或出版时间、语言、材料类型、权利与使用范围。
6. 连接上游 `retrieval_id`，分配 `witness_id` 和 `independence_group`；无法确认的关系保持未知。

## 状态

使用 `../../assets/templates/source_manifest.csv`，并运行 `../../scripts/validate_source_manifest.py`。新导入材料最多升级到 `FILE_VERIFIED`；只有完成相应阅读和页码核验后才能标为 `CITABLE`。

不要修改原件。异常文件、重复件和不完整下载要单独标记，不静默删除。
