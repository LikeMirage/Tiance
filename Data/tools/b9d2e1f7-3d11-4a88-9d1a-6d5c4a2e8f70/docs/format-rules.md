# Markdown 转 Excel 完整规则

调用工具前先读取本文件和 `examples/complete-content.md`、`examples/complete-format.md`。工具调用参数只有内容路径、格式路径、输出路径和是否覆盖；复杂格式全部写在格式 Markdown 的对应格子中。

## 输入模型

`content.md` 和 `format.md` 都由“标题 + 标准 Markdown 表格”组成。标题决定 Sheet 名，标题为空时按 `Sheet1`、`Sheet2` 顺序命名。格式表按标题匹配内容表，行数和列数必须完全相同；不一致直接报错，不会自动补格或错位套用。

内容表只写正文、数字、日期、公式和换行：

- `=SUM(B2:B8)`：Excel 公式。
- `date:2026-08-05`：真正的日期。
- `text:0012` 或 `'0012`：强制文本。
- `<br>`：单元格换行。
- `\\|`：正文中的字面竖线。

格式表每个格子用英文分号分隔指令。所有指令必须带明确名称；合并不能写裸词。

## 合并

在同一合并区的格子写同一个标记：

```text
merge:title
```

工具取这些格子的包围盒作为合并范围。建议只写左上角和右下角。不同合并区不能交叉或重叠；合并区除左上角外的内容必须为空，否则报错，避免静默丢数据。

## 单元格格式

```text
font-family:微软雅黑
font-size:14
font-weight:bold
font-style:italic
text-decoration:underline
color:#FFFFFF
background:#1F4E78
text-align:left|center|right|justify
vertical-align:top|center|bottom
wrap-text:on|off
shrink-to-fit:on|off
text-rotation:45
border:thin|medium|thick|double|dashed|dotted|none
border-top:thin
border-right:thin
border-bottom:thin
border-left:thin
border-color:#000000
number-format:0.00%
protection:locked|unlocked
hyperlink:https://example.com
comment:批注内容
```

简写 `bold`、`italic`、`underline`、`wrap`、`nowrap` 可用，但推荐完整写法。颜色支持 `#RGB`、`#RRGGBB`、`#RRGGBBAA`。

## 行列和工作表

写在某格时，`width`/`column-width` 作用于该列，`height`/`row-height` 作用于该行：

```text
width:18
height:28
width:auto
height:auto
freeze:A2
filter:A1:H20
table:on
table-style:TableStyleMedium9
tab-color:#4472C4
hidden-row:on
hidden-column:on
print-area:A1:H20
page-orientation:landscape
fit-to-width:1
fit-to-height:0
margin:0.25
```

`table:on` 会创建 Excel 原生 Table，表头必须非空、不重复，且第一行不能是合并区。`filter` 直接写筛选范围。

## 图片

```text
image:assets/logo.png; image-width:120; image-height:60
```

图片路径相对于 `format.md`，也支持 `http://` 和 `https://`。网络图片超时 15 秒、单张最大 10MB。图片与同一内容格的文字不能同时存在。只写一个图片尺寸时按比例缩放，不写尺寸时使用锚点格的大小。

## 下拉验证

```text
validation:未开始,进行中,已完成@G2:G20
```

下拉选项放在 `@` 前，范围放在 `@` 后。Excel 对单个列表公式有长度限制，过长时应改用工作表范围。

## 条件格式

条件值中的竖线必须写成 `\\|`，因为单个 `|` 是 Markdown 表格分隔符。

```text
data-bar:#63C384@F2:F20
color-scale:#F8696B,#FFEB84,#63BE7B@F2:F20
cell-is:>100\|#FFFF00@F2:F20
formula-rule:$F2="异常"\|#FFC7CE@A2:H20
```

## 图表

图表写在锚点格：

```text
chart:bar@A1:D10; chart-title:月度趋势; chart-width:480; chart-height:288; chart-cats:col1
```

支持 `bar`、`line`、`area`、`pie`、`scatter`。范围使用 Excel A1 表示法。

## 范围样式

在任意格式格中写 `range:A1:H1`，该格中的其他样式会应用到整个范围：

```text
range:A1:H1; background:#1F4E78; color:#FFFFFF; font-weight:bold
```

## 隐藏格式块

如果不单独传 `format_path`，可以把完整格式 Markdown 放进内容文件的 HTML 注释中。Markdown 预览不会显示它：

```html
<!-- md2xlsx-format
# 项目汇总

| merge:title; font-weight:bold | merge:title | merge:title |
|---|---|---|
| ... | ... | ... |
-->
```

## 失败处理

任何结构错误、同构错误、未知指令、合并冲突、图片失败、对象参数错误都会终止转换，不生成错误的 Excel。输出文件使用临时文件写入，校验成功后才替换目标文件；目标已存在时必须显式传 `overwrite:true`。
