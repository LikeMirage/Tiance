"""Outbound host capability. Identity is explicit; no prior-message inference."""
import asyncio
from pathlib import Path

from app.core.errors import BadRequestError
from app.infra.secrets import decrypt_secret
from .context import target_header
from .telegram_transport import TelegramTransport, TelegramSendError, split_message


def public_connection(record):
    config = record['config']
    return dict(connection_id=record['connection_id'], platform=record['platform'],
                remote_id=record['remote_id'], enabled=bool(config.get('enabled')),
                name=config.get('bot', {}).get('first_name', ''),
                username=config.get('bot', {}).get('username', ''))


async def execute(repository, payload, grant):
    records = await asyncio.to_thread(repository.connections, payload.platform)
    if payload.action == 'list_connections':
        return {'ok': True, 'connections': [public_connection(record) for record in records]}
    record = next((r for r in records if r['connection_id'] == payload.connection_id), None)
    if not record or not record['config'].get('enabled'):
        raise BadRequestError('机器人连接不存在或未启用，请在访问管理中配置。')
    adapter = SENDERS.get(record['platform'])
    if adapter is None:
        raise BadRequestError('当前平台尚未实现发送适配器。')
    # Snapshot this connection before any network await; edits never reroute an upload.
    header = ''
    if grant.project_id and grant.session_id:
        try:
            header = await asyncio.to_thread(target_header, {'project_id': grant.project_id, 'session_id': grant.session_id})
        except Exception:
            header = f'天策 · 项目 ID：{grant.project_id} · 会话 ID：{grant.session_id}'
    if payload.action == 'send_text':
        text = '\n\n'.join(part for part in (header, payload.text) if part)
        return await send_text(repository, record, str(payload.chat_id), text)
    path = Path(payload.file_path)
    if not path.is_absolute():
        raise BadRequestError('能力桥的 file_path 必须是绝对路径；工具可先按工作区解析相对路径。')
    if not await asyncio.to_thread(path.is_file):
        raise BadRequestError('待发送文件不存在或不是普通文件。')
    caption = '\n\n'.join(part for part in (header, payload.caption) if part)
    if record['platform'] == 'telegram':
        return await adapter(record, str(payload.chat_id), path, caption)
    return await platform_send_file(repository, record, str(payload.chat_id), path, caption)


def telegram_sender(record):
    config = record['config']
    try:
        return TelegramTransport(decrypt_secret(config['token']), config['api_base'])
    except Exception:
        raise BadRequestError('无法读取此连接的凭据，请在访问管理中重新保存。') from None


async def telegram_send_file(record, chat_id, path, caption):
    transport = telegram_sender(record)
    size = await asyncio.to_thread(lambda: path.stat().st_size)
    # Preserve the entire caption. The first part belongs to the document; any
    # continuation is explicitly sent as ordinary text and tracked separately.
    parts = list(split_message(caption, 1024)) or ['']
    ids = []
    result = dict(connection_id=record['connection_id'], platform='telegram', chat_id=chat_id,
                  file_path=str(path), file_size=size, message_ids=ids)
    try:
        document = await transport.send_once('sendDocument', {'chat_id': chat_id, 'caption': parts[0]}, document=path)
        ids.append(document['message_id'])
        for text in split_message(''.join(parts[1:])):
            sent = await transport.send_once('sendMessage', {'chat_id': chat_id, 'text': text})
            ids.append(sent['message_id'])
    except TelegramSendError as exc:
        return dict(result, ok=False, status='partial' if ids else exc.status,
                    failed_part_status=exc.status, file_sent=True if ids else (False if exc.status == 'not_sent' else None), error=str(exc),
                    retry_after_seconds=exc.retry_after,
                    instruction='不要自动重发整个文件；先核对目标聊天及已确认的消息 ID。')
    return dict(result, ok=True, status='sent', file_sent=True)


async def platform_sender(repository, record, chat_id):
    from .service import FeishuService, WeChatService
    config, context = record['config'], None
    factory = {'feishu': FeishuService, 'wechat': WeChatService}[record['platform']]
    transport = factory(repository.scoped(record['connection_id'])).make_transport(config)
    if record['platform'] == 'wechat':
        # Explicit destination only. Never infer it from the caller's last message.
        peers = await asyncio.to_thread(repository.scoped(record['connection_id']).list, 'peers')
        peer = next((key for key, identity in peers if str(identity.get('chat_id')) == chat_id), None)
        if peer:
            context = await asyncio.to_thread(repository.scoped(record['connection_id']).get, 'reply_context', peer, {})
        if not context or not context.get('context_token'):
            raise BadRequestError('微信接收 ID 没有有效回复凭据；请先让该用户给此机器人发送一条消息。')
    return transport, context


async def send_text(repository, record, chat_id, text):
    """One-way delivery; never consume inbound messages or create an AI job."""
    from uuid import uuid4
    platform = record['platform']
    if platform == 'telegram':
        transport, context = telegram_sender(record), None
    else:
        transport, context = await platform_sender(repository, record, chat_id)
    ids, sent_characters = [], 0
    result = dict(connection_id=record['connection_id'], platform=platform, chat_id=chat_id,
                  message_ids=ids, total_characters=len(text))
    delivery_id = uuid4().hex
    for index, part in enumerate(split_message(text)):
        try:
            if platform == 'telegram':
                sent = await transport.send_once('sendMessage', {'chat_id': chat_id, 'text': part})
            elif platform == 'feishu':
                sent = await transport.send(chat_id, 'text', {'text': part}, f'{delivery_id}:{index}')
            else:
                sent = await transport.send_items(chat_id, [{'type': 1, 'text_item': {'text': part}}],
                                                  f'{delivery_id}:{index}', context)
            ids.append(sent['message_id'])
            sent_characters += len(part)
        except Exception as exc:
            # Lost responses cannot prove non-delivery. Confirmed earlier parts
            # remain visible in the result; do not resend the complete message.
            failure = exc.status if isinstance(exc, TelegramSendError) else 'unknown'
            error = str(exc) if isinstance(exc, TelegramSendError) else getattr(exc, 'message', f'发送未确认（{type(exc).__name__}）。')
            return dict(result, ok=False, status='partial' if ids else failure,
                        failed_part_status=failure, sent_characters=sent_characters, error=error,
                        retry_after_seconds=getattr(exc, 'retry_after', 0),
                        instruction='先核对目标聊天及已确认的消息 ID；不要自动重发整段文字。')
    return dict(result, ok=True, status='sent', sent_characters=sent_characters)


async def platform_send_file(repository, record, chat_id, path, caption):
    from uuid import uuid4
    transport, context = await platform_sender(repository, record, chat_id)
    result = dict(connection_id=record['connection_id'], platform=record['platform'], chat_id=chat_id,
                  file_path=str(path), file_size=path.stat().st_size)
    try:
        kwargs = {'context': context} if record['platform'] == 'wechat' else {}
        sent = await transport.send_file(chat_id, path, caption, uuid4().hex, **kwargs)
        return dict(result, ok=True, status='sent', file_sent=True, message_ids=[sent['message_id']])
    except Exception as exc:
        # A timeout after submitting the message cannot prove non-delivery.
        return dict(result, ok=False, status='unknown', file_sent=None,
                    error=getattr(exc, 'message', f'发送未确认（{type(exc).__name__}）。'),
                    instruction='不要自动重复发送。先核对目标聊天，文件或说明可能已送达。')


SENDERS = {'telegram': telegram_send_file, 'feishu': platform_send_file, 'wechat': platform_send_file}
