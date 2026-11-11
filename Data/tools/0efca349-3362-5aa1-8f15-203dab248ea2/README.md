# 对外文件发送

独立 Python 工具，无额外第三方依赖。通过天策 `external_messaging` 能力桥复用 Telegram、飞书或微信连接，密钥不进入工具文件或参数。

输入、返回与边界详见 `.tool/input.schema.json`、`.tool/examples.json`。先指定 `platform`，用 `list_connections` 查询连接；发送时明确填写连接 ID、聊天 ID 和文件路径。不推断上一条消息的发送人，不要求任务由手机发起。

微信需要指定接收者近期发来的有效回复凭据；无法取得时明确失败，不改发给其他人。文件和说明可能分为多条消息；返回未确认时先核对目标聊天，不自动重复上传。
