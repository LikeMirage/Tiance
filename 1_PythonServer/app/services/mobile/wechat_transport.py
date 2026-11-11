"""Tencent iLink private-message adapter. No WeChat desktop automation."""
import asyncio
import base64
import secrets
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from app.core.errors import BadRequestError
from app.infra.http_client import get_shared_http_client, lease_http_client, get_http_timeout

BASE = 'https://ilinkai.weixin.qq.com'
CDN = 'https://novac2c.cdn.weixin.qq.com/c2c'
PROTOCOL_VERSION = '3.0.1/tiance'


def trusted_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.weixin.qq.com') or parsed.username or parsed.password:
        raise BadRequestError('微信返回了非预期的服务地址。')
    return url.rstrip('/')


def normalize_message(message):
    if message.get('message_type') != 1 or message.get('group_id') or not message.get('from_user_id'):
        return None
    identifier = message.get('message_id') or message.get('seq')
    if identifier is None:
        raise BadRequestError('微信消息缺少唯一标识，无法安全去重；本批次未确认接收。')
    text, media = [], []
    for item in message.get('item_list', []):
        kind = item.get('type')
        if kind == 1:
            text.append(item.get('text_item', {}).get('text', ''))
        elif kind in {2, 3, 4, 5}:
            part = item.get({2: 'image_item', 3: 'voice_item', 4: 'file_item', 5: 'video_item'}[kind], {})
            suffix = {2: '.jpg', 4: '', 5: '.mp4'}.get(kind)
            if kind == 3:
                suffix = {1: '.pcm', 2: '.adpcm', 4: '.speex', 5: '.amr', 6: '.silk', 7: '.mp3', 8: '.ogg'}.get(part.get('encode_type'), '.voice')
            media.append(dict(part, kind=kind, file_name=part.get('file_name') or f"{message.get('message_id', uuid4().hex)}_{len(media)}{suffix}"))
    user = message['from_user_id']
    return dict(id=str(identifier), user_id=user, chat_id=user,
                text='\n'.join(text), media=media, context={'context_token': message.get('context_token', '')})


class WeChatTransport:
    def __init__(self, token='', base=BASE):
        self.token, self.base = token, trusted_url(base)

    async def call(self, method, payload=None, *, auth=True, params=None, get=False, poll=False):
        headers = {'iLink-App-Id': 'bot', 'iLink-App-ClientVersion': str(0x030001)}
        if not get:
            headers.update({'AuthorizationType': 'ilink_bot_token',
                            'X-WECHAT-UIN': base64.b64encode(str(secrets.randbits(32)).encode()).decode()})
        if auth:
            headers['Authorization'] = 'Bearer ' + self.token
            payload = dict(payload or {}, base_info={'channel_version': PROTOCOL_VERSION, 'bot_agent': 'Tiance'})
        timeout = get_http_timeout()
        if poll:
            timeout = httpx.Timeout(
                connect=timeout.connect,
                read=max(timeout.read or 0, 40),
                write=timeout.write,
                pool=timeout.pool,
            )
        async with lease_http_client(get_shared_http_client()) as client:
            response = await client.request('GET' if get else 'POST', self.base + '/ilink/bot/' + method,
                                            params=params, headers=headers, json=None if get else (payload or {}), timeout=timeout,
                                            follow_redirects=False)
            if not response.is_success:
                raise BadRequestError(f'微信接口 HTTP {response.status_code}，请检查网络或稍后重试。')
            body = response.json()
        error = body.get('ret') or body.get('errcode')
        if error:
            if error == -14:
                raise BadRequestError('微信登录已失效，请在访问管理中重新扫码连接。')
            raise BadRequestError(f'微信接口错误 {error}，请稍后重试或重新扫码。')
        return body

    async def events(self, repository):
        cursor_key = repository.connection_id
        if not cursor_key:
            raise ValueError('微信接收需要明确的连接标识。')
        cursor = await asyncio.to_thread(repository.get, 'offsets', cursor_key, '')
        while True:
            try:
                body = await self.call('getupdates', {'get_updates_buf': cursor}, poll=True)
            except httpx.ReadTimeout:
                # An idle long poll can expire without a new message.
                continue
            for message in body.get('msgs', []):
                yield normalize_message(message)
            cursor = body.get('get_updates_buf', cursor)
            await asyncio.to_thread(repository.put, 'offsets', cursor_key, cursor)
            yield None

    async def deliver(self, peer, text, rows, *, context=None, document=None, delivery_id):
        if document:
            return await self.send_file(peer['chat_id'], document, text, delivery_id, context=context)
        return await self.send_items(peer['chat_id'], [{'type': 1, 'text_item': {'text': text}}], delivery_id, context)

    async def send_items(self, chat_id, items, delivery_id, context):
        if not context or not context.get('context_token'):
            raise BadRequestError('微信缺少接收者的有效回复凭据，请先由该用户给机器人发消息。')
        await self.call('sendmessage', {'msg': {'from_user_id': '', 'to_user_id': str(chat_id),
                        'client_id': delivery_id, 'message_type': 2, 'message_state': 2,
                        'context_token': context['context_token'], 'item_list': items}})
        return {'message_id': delivery_id}

    async def download(self, media, destination):
        from .wechat_media import download_file
        await download_file(media, destination)

    async def send_file(self, chat_id, path, caption, delivery_id, *, context=None):
        from .wechat_media import upload_file
        if not context or not context.get('context_token'):
            raise BadRequestError('请先由接收者在微信中给机器人发消息，以取得回复凭据。')
        item = await upload_file(self, chat_id, path)
        result = await self.send_items(chat_id, [item], delivery_id + ':file', context)
        if caption:
            from .telegram_transport import split_message
            for index, text in enumerate(split_message(caption)):
                await self.send_items(chat_id, [{'type': 1, 'text_item': {'text': text}}], f'{delivery_id}:caption:{index}', context)
        return result
