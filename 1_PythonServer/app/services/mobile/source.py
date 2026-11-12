"""Visible provenance belongs to the ordinary user message, not hidden context."""


def append_message_source(text, *, platform, connection_id, user_id, chat_id):
    return (f'{text}\n\n[消息来源]\n平台：{platform}\n连接 ID：{connection_id}'
            f'\n用户 ID：{user_id}\n聊天 ID：{chat_id}'
            '\n渠道说明：此入口不展示思考、工具调用及中途文字，只自动回传最终回复或错误。'
            '需要汇报进度或询问时，可使用已启用的对外发送工具主动发送；单向发送不等待用户回复。')
