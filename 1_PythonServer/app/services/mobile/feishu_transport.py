"""Feishu application bot: shared HTTP policy, long connection, original files."""
import asyncio
import json
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, quote
from uuid import NAMESPACE_URL, uuid5

from app.core.errors import BadRequestError
from app.infra.http_client import get_shared_http_client, lease_http_client, get_http_timeout, get_network_proxy_url
from .feishu_events import normalize_event
from .feishu_cards import build_card

BASE = 'https://open.feishu.cn'


class FeishuTransport:
    def __init__(self, app_id, secret):
        self.app_id, self.secret = app_id, secret
        self.token, self.expires = '', 0
        self.token_lock = asyncio.Lock()

    async def request(self, path, *, method='POST', auth=True, **kwargs):
        headers = kwargs.pop('headers', {})
        if auth:
            headers['Authorization'] = 'Bearer ' + await self.access_token()
        async with lease_http_client(get_shared_http_client()) as client:
            response = await client.request(method, BASE + path, headers=headers, timeout=get_http_timeout(), follow_redirects=False, **kwargs)
            if not response.is_success:
                raise BadRequestError(f'飞书接口 HTTP {response.status_code}。请检查应用权限和网络。')
            body = response.json()
        if body.get('code', 0):
            raise BadRequestError(f"飞书接口错误 {body['code']}。请检查应用凭据、权限和发布状态。")
        return body

    async def access_token(self):
        async with self.token_lock:
            if time.monotonic() >= self.expires:
                body = await self.request('/open-apis/auth/v3/tenant_access_token/internal', auth=False,
                                          json={'app_id': self.app_id, 'app_secret': self.secret})
                self.token = body['tenant_access_token']
                self.expires = time.monotonic() + max(1, body.get('expire', 7200) - 60)
            return self.token

    async def identity(self):
        body = await self.request('/open-apis/bot/v3/info', method='GET')
        bot = body.get('bot', {})
        if not bot.get('open_id'):
            raise BadRequestError('未取得飞书机器人身份，请先为应用添加机器人能力并发布。')
        return {'id': self.app_id, 'first_name': bot.get('app_name') or self.app_id, 'open_id': bot['open_id']}

    async def events(self, repository):
        import websockets
        from .feishu_frames import Frame
        body = await self.request('/callback/ws/endpoint', auth=False,
                                  json={'AppID': self.app_id, 'AppSecret': self.secret})
        data = body['data']
        url = data['URL']
        parsed = urlsplit(url)
        if parsed.scheme != 'wss' or not parsed.hostname or not parsed.hostname.endswith(('.feishu.cn', '.larksuite.com')):
            raise BadRequestError('飞书返回了非预期的长连接地址。')
        service = int(parse_qs(parsed.query)['service_id'][0])
        interval = max(1, data.get('ClientConfig', {}).get('PingInterval', 120))
        timeout = get_http_timeout()
        async with websockets.connect(url, proxy=get_network_proxy_url(), open_timeout=timeout.connect,
                                      max_size=None, ping_interval=None) as socket:
            yield None  # Connected, clear a previous transport error.
            async def heartbeat():
                while True:
                    frame = Frame(SeqID=0, LogID=0, service=service, method=0)
                    frame.headers.add(key='type', value='ping')
                    await socket.send(frame.SerializeToString())
                    await asyncio.sleep(interval)
            ping = asyncio.create_task(heartbeat())
            fragments = {}
            try:
                while True:
                    # Missing pong/data is a transport failure, never an AI timeout.
                    raw = await asyncio.wait_for(socket.recv(), max(interval * 3, timeout.read or 120))
                    frame = Frame.FromString(raw)
                    headers = {h.key: h.value for h in frame.headers}
                    if frame.method == 0:
                        if headers.get('type') == 'pong' and frame.payload:
                            interval = max(1, json.loads(frame.payload).get('PingInterval', interval))
                        yield None
                        continue
                    payload = frame.payload
                    total, sequence = int(headers.get('sum', 1)), int(headers.get('seq', 0))
                    if total > 1:
                        key = headers['message_id']
                        if not 0 <= sequence < total:
                            raise BadRequestError('飞书长连接消息分片序号无效。')
                        parts, started = fragments.setdefault(key, ({}, time.monotonic()))
                        parts[sequence] = payload
                        if any(time.monotonic() - stamp > 120 for _, stamp in fragments.values()):
                            raise BadRequestError('飞书消息分片未收齐，将重新连接。')
                        if len(parts) != total:
                            continue
                        payload = b''.join(parts[i] for i in range(total))
                        del fragments[key]
                    if headers.get('type') == 'event':
                        yield normalize_event(json.loads(payload))
                    # The runtime has durably committed the event before resuming.
                    frame.payload = b'{"code":200}'
                    await socket.send(frame.SerializeToString())
            finally:
                ping.cancel()
                with suppress(asyncio.CancelledError):
                    await ping

    async def send(self, chat_id, kind, content, delivery_id):
        body = await self.request('/open-apis/im/v1/messages?receive_id_type=chat_id',
            json={'receive_id': str(chat_id), 'msg_type': kind, 'content': json.dumps(content, ensure_ascii=False),
                  'uuid': str(uuid5(NAMESPACE_URL, delivery_id))})
        return {'message_id': body['data']['message_id']}

    async def deliver(self, peer, text, rows, *, context=None, document=None, delivery_id, header=''):
        if document:
            caption = '\n\n'.join(part for part in (header, text) if part)
            return await self.send_file(peer['chat_id'], document, caption, delivery_id)
        return await self.send(peer['chat_id'], 'interactive', build_card(text, rows, header=header), delivery_id)

    async def download(self, media, destination):
        path = '/open-apis/im/v1/messages/' + quote(media['message_id'], safe='') + '/resources/' + quote(media['file_key'], safe='')
        token = await self.access_token()
        temporary = destination.with_suffix(destination.suffix + '.part')
        try:
            async with lease_http_client(get_shared_http_client()) as client:
                async with client.stream('GET', BASE + path, params={'type': media['type']},
                                         headers={'Authorization': 'Bearer ' + token}, timeout=get_http_timeout(), follow_redirects=False) as response:
                    if not response.is_success:
                        raise BadRequestError(f'飞书文件下载失败 HTTP {response.status_code}。请检查文件权限。')
                    with temporary.open('wb') as handle:
                        async for chunk in response.aiter_bytes(128 * 1024):
                            await asyncio.to_thread(handle.write, chunk)
            await asyncio.to_thread(temporary.replace, destination)
        finally:
            temporary.unlink(missing_ok=True)

    async def send_file(self, chat_id, path: Path, caption, delivery_id):
        with path.open('rb') as handle:
            body = await self.request('/open-apis/im/v1/files', data={'file_type': 'stream', 'file_name': path.name},
                                      files={'file': (path.name, handle, 'application/octet-stream')})
        result = await self.send(chat_id, 'file', {'file_key': body['data']['file_key']}, delivery_id + ':file')
        if caption:
            from .telegram_transport import split_message
            for index, text in enumerate(split_message(caption)):
                await self.send(chat_id, 'text', {'text': text}, f'{delivery_id}:caption:{index}')
        return result
