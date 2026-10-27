# 工具开发工作区

此项目由“新建空白工具”创建。标准配置和 Python 入口已备齐，业务尚未实现，工具默认关闭。

制作前先阅读 [工具制作指南](docs/tool-development/README.md)，再按该索引阅读相应章节。配置与程序必须保持一致。

- 工具清单与开关：`.tool/tool.json`
- 输入、输出、案例、权限：`.tool/` 中的对应 JSON
- 程序入口：`program/main.py`
- 可选业务配置：`program/config.json`
- 依赖声明：`program/requirements.txt`

程序完成且通过验证后，按用户意愿决定是否把 `.tool/tool.json` 的 `state.enabled` 改为 `true`。新建完成不等于制作完成，不自动开启。
