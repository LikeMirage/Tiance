# 图标搜索与导出

独立 Python 工具，调用名称 `icon_library`。完整收录 Phosphor、Lucide、Tabler、Heroicons 四库，合计 18,939 个 SVG（含各库的不同样式）。安装 Python 依赖后，搜索、预览、导出均离线运行，不需要 Key、浏览器或天策能力桥。

## 使用

按 **搜索 → 指定候选 → 合并预览 → 读取预览图 → 导出** 操作。

```json
{"action":"search","queries":["gear","factory","network"],"limit":10}
```

搜索只返回文字候选。名称、库、样式、精确 ID 和总匹配数均在结果中。英文关键词搜索原始名称、标签、别名与分类；多个查询分别返回结果，每个查询可用 `next_offset` 翻页。中文意图由调用模型转换关键词，工具不额外请求模型。

```json
{"action":"preview","icons":["phosphor:regular/gear","lucide:factory","heroicons:24/outline/cog-8-tooth"],"columns":3}
```

预览为一张 PNG。每格包含序号、名称、库/样式和完整 ID，长名称换行保留。默认每行最多 5 个，数量增加时向下扩展，不丢弃候选。读取返回的 `data.preview.path` 即可查看，再按编号与 ID 选中要用的图标。

```json
{"action":"export","icons":["heroicons:24/outline/cog-8-tooth"],"formats":["svg","png"],"color":"#2563EB","size":512}
```

默认 SVG + PNG，PNG 边长 512 像素、透明背景；SVG 保留矢量。`color` 可省略；仅替换原 SVG 的 `currentColor`，固定颜色、无填充属性与双色透明度保留。预览棋盘背景和文字不进入导出图标。

`libraries` 返回版本、样式与完整数量。所有参数详见 `.tool/input.schema.json`，更详细用法在 `.tool/examples.json`，由动态加载工具按需读取。

## 输出与失败

- 默认父目录是调用方工作区的 `icons`；可指定 `output_dir`。相对路径以 `TIANCE_WORKSPACE_ROOT` 为基准；无调用工作区时必须明确提供绝对路径。
- 每次写入创建唯一子目录，避免覆盖与并发冲突。导出按库/样式目录保存，附 `manifest.json` 和使用到的原始许可证。
- 返回绝对路径、字节大小与编号映射，不把 SVG/XML/base64 塞入对话。AI 需要主动用图片读取工具查看预览。
- 无效 ID 在写入前报错；单个导出项失败时返回 `ok=false`、已完成文件和逐项错误。预览任何一个图标失败都不宣称整张预览完成。
- 不隐藏截断数量、替换库或调整尺寸。异常大请求可能受可用内存和用户在工具设置中的标准执行超时限制，失败明确返回；没有工具内另设的超时。

## 独立运行与依赖

在天策工具依赖页面安装 `program/requirements.txt`，由平台管理本工具私有依赖目录。也可在独立 Python 环境中 `pip install -r program/requirements.txt`，向 `python program/main.py` 的 stdin 写入上述 JSON，stdout 接收单个 JSON 结果。独立运行需要写文件时提供绝对 `output_dir`。

只有渲染 PNG 才加载 Pillow 与 resvg-py；列库、搜索、只导出 SVG 使用 Python 标准库即可。无需 Cairo DLL、Node.js 或完整前端包。

## 图库数据与维护

工具程序遵循 Apache-2.0（见根目录 `LICENSE`）；随附图标素材分别遵循各图库自己的 MIT / ISC 许可，原文保存在 `assets/licenses/`，导出时一并附带。

| 库 | 固定版本 | SVG 数量 |
| --- | --- | ---: |
| Phosphor | 2.1.1 | 9,072 |
| Lucide | 1.70.0 | 2,322 |
| Tabler | 3.50.0 | 6,257 |
| Heroicons | 2.2.0 | 1,288 |

`assets/*.zip` 各保存一个完整图库的 SVG，直接按索引随机读取，不在调用时解压整库。`assets/index.json.gz` 保存原始标签/分类与 SHA-256；`assets/catalog.json` 保存来源、固定版本和包完整性信息。读取时校验索引及使用到的 SVG。压缩归档保留矢量，不做有损精简。

`scripts/build_assets.py` 是开发者手动重建脚本，从固定版本的官方 npm 包提取资源并验证 npm SHA-512，**工具运行不会执行它或联网更新图库**。升级应修改固定版本、复核元数据格式、重新构建并运行测试。不要混装新旧索引和资源。原始许可完整保存在 `assets/licenses/`；输出的素材也携带对应许可。

测试：已安装依赖的 Python 执行 `python -m unittest discover -s tests -v`。测试使用临时输出目录，不改用户项目。
