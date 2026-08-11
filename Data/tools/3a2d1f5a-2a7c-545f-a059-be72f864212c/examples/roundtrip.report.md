# Excel 反向提取报告

- 输入文件：`examples/roundtrip.xlsx`
- 内容文件：`examples/roundtrip.content.md`
- 格式文件：`examples/roundtrip.format.md`
- Sheet 数量：2
- 图片数量：0

## 给 AI 的读取规则

1. 先读取 content.md，理解表格内容和公式。
2. 再读取 format.md；它与 content.md 按标题和单元格位置一一对应。
3. 内容表只修改值，格式表只修改格式和结构指令。
4. 仅在需要重新生成 Excel 时使用 markdown_to_excel；若当前没有该工具，先从在线市场安装，不能自行猜测单元格偏移。
5. 本次提取是规范化结果，不保证还原原始 Excel 编辑过程。
