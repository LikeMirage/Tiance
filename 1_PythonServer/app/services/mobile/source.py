"""Visible provenance belongs to the ordinary user message, not hidden context."""


def append_message_source(text, *, platform, connection_id, user_id, chat_id):
    return (f'{text}\n\n[消息来源]\n平台：{platform}\n连接 ID：{connection_id}'
            f'\n用户 ID：{user_id}\n接收聊天 ID：{chat_id}')
