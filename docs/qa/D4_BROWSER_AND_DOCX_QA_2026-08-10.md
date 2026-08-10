# D4 Browser and DOCX QA（2026-08-10）

## 范围

- 文章工作台三栏布局与 1260×720 视口；
- 选区到注释提案、人工批准、正文脚注标记；
- 两套期刊模板的版本和来源展示；
- Word 导出回执与版本信息；
- 浏览器控制台和请求错误。

## 结果

- 选区可固定到段落节点和字符位置；元数据先行注释会保留“页码待作者填写”，批准前不进入正文。
- 人工批准后正文出现脚注标记，状态栏显示 1 条已批准注释、0 条待审。
- 已批准注释可生成待审修订；修订等待决定时旧版脚注仍留在正文和导出中，拒绝后恢复为 0 条待审。
- 选择《中国社会科学》后可导出带真实脚注的 DOCX，回执包含模板和保真警告。
- 项目设置显示 package `0.9.0.dev1` 与 schema `7`，不再硬编码旧版本。
- 浏览器自动化过程未发现 JavaScript 异常或失败请求。
- 首轮截图发现 1260 像素宽度下右侧标签被横向裁切；已将三栏最小宽度收紧并让写作标签换行，复测通过。

## DOCX 渲染

- OOXML 检查：正文包含 `w:footnoteReference`，`word/footnotes.xml` 定义对应脚注，节属性设置每页重编号。
- Microsoft Word 实际打开并导出 PDF 成功；逐页图像检查确认脚注标记在标点后、脚注位于页底且内容正确。
- LibreOffice 的无界面转换在中文标点后紧接脚注标记时可能失败；不能用插入空格的方式规避，因为这会破坏期刊位置要求。该限制已写入导出保真回执。

## 证据文件

- `tmp/d4-browser-qa/screenshots/article-final-fit.png`
- `tmp/d4-browser-qa/screenshots/note-pending.png`
- `tmp/d4-browser-qa/screenshots/note-approved.png`
- `tmp/d4-browser-qa/screenshots/journal-templates.png`
- `tmp/d4-word-page-1.png`
