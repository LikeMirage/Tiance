# Excel 反向提取规则

调用 `action: export_markdown` 后，会得到三个可读结果：

- `content.md`：每个 Sheet 一个标题和一个 Markdown 表格，只保存正文值、日期、布尔值和 Excel 公式。
- `format.md`：与 `content.md` 按标题、行、列严格对应，只保存格式和结构指令。
- 提取报告：告诉 AI 如何读取两个 Markdown，并列出没有被完整映射的 Excel 对象。

## AI 读取顺序

1. 先读取 `content.md`，理解表格内容和公式。
2. 再读取 `format.md`，按相同标题和相同单元格位置解释格式。
3. 不要把 `format.md` 当成正文，也不要把格式指令写回内容表。
4. 仅在需要重新生成 Excel 时使用 `markdown_to_excel`；若当前没有该工具，先从在线市场安装，并保持两张表的尺寸完全一致。

## 内容值

- 普通文字直接写入。
- 数字、布尔值和 Excel 公式保留原类型。
- 日期写成 `date:YYYY-MM-DD`。
- 合并区域只保留左上角的正文，其余位置为空。

## 格式指令

格式单元格内使用英文分号分隔：

```text
font-weight:bold; color:#1F4E78; background:#D9EAF7; width:18
```

支持的常见指令包括：

- `merge:名称`
- `font-weight`、`font-style`、`text-decoration`、`font-size`、`font-family`、`color`
- `background`、`text-align`、`vertical-align`、`wrap`
- `number-format`
- `border`、`border-left`、`border-right`、`border-top`、`border-bottom`
- `width`、`height`
- `hyperlink`、`comment`
- `freeze`、`filter`、`table`、`table-style`、`tab-color`
- `validation`

## 合并

同一个 Excel 合并区域会生成相同的 `merge:名称`。转换时工具会根据这些标记恢复合并区域；合并区中如果存在多个正文值，应先人工确认内容。

## 不能保证完整还原的对象

Excel 主题色、宏、透视表、切片器、复杂图表、特殊绘图对象和部分高级数据验证可能无法转换成当前 Markdown 规则。工具不会静默丢弃，会写入提取报告的警告。

目标是“结构和格式语义等价”，不是还原 Excel 的原始编辑过程或文件字节。
