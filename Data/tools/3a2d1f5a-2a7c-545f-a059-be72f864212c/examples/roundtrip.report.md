# Excel 反向提取报告

- 输入文件：`C:\Users\WW\Desktop\Tiance\Data\tools\b9d2e1f7-3d11-4a88-9d1a-6d5c4a2e8f70\examples\complete-result.xlsx`
- 内容文件：`C:\Users\WW\Desktop\Tiance\Data\tools\3a2d1f5a-2a7c-545f-a059-be72f864212c\examples\roundtrip.content.md`
- 格式文件：`C:\Users\WW\Desktop\Tiance\Data\tools\3a2d1f5a-2a7c-545f-a059-be72f864212c\examples\roundtrip.format.md`
- Sheet 数量：2
- 图片数量：0

## 给 AI 的读取规则

1. 先读取 content.md，理解表格内容和公式。
2. 再读取 format.md；它与 content.md 按标题和单元格位置一一对应。
3. 内容表只修改值，格式表只修改格式和结构指令。
4. 修改后调用 markdown_to_excel，不能自行猜测单元格偏移。
5. 本次提取是规范化结果，不保证还原原始 Excel 编辑过程。
