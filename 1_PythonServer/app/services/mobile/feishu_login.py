"""Feishu PersonalAgent registration; credentials never enter the browser."""
import asyncio
import base64
import io
import math
import time
from contextlib import suppress
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from app.core.errors import BadRequestError
from app.infra.http_client import get_shared_http_client, lease_http_client, get_http_timeout

REGISTRATION_URL = 'https://accounts.feishu.cn/oauth/v1/app/registration'


async def registration_request(action, **fields):
    async with lease_http_client(get_shared_http_client()) as client:
        response = await client.post(REGISTRATION_URL, data={'action': action, **fields},
                                     timeout=get_http_timeout(), follow_redirects=False)
    try:
        body = response.json()
    except ValueError:
        raise BadRequestError(f'飞书扫码接口返回无效内容（HTTP {response.status_code}）。') from None
    if not isinstance(body, dict):
        raise BadRequestError('飞书扫码接口返回格式无效。')
    # OAuth pending/denied responses may use a non-2xx HTTP status.
    if not response.is_success and not body.get('error'):
        raise BadRequestError(f'飞书扫码接口 HTTP {response.status_code}。请稍后重新获取二维码。')
    return body


def qr_image(url):
    import qrcode
    output = io.BytesIO()
    qrcode.make(url).save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()


class FeishuLogin:
    def __init__(self, manager):
        self.manager = manager
        self.task = None
        self.state = None
        self.lock = asyncio.Lock()

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def start(self):
        async with self.lock:
            if self.state and self.state['status'] == 'saving' and self.task and not self.task.done():
                raise BadRequestError('正在验证并保存飞书连接，请稍候。')
            await self.close()
            self.state = None
            try:
                body = await registration_request('begin', archetype='PersonalAgent', auth_method='client_secret',
                                                  request_user_info='open_id tenant_brand')
            except httpx.HTTPError as exc:
                raise BadRequestError(f'飞书二维码获取失败（{type(exc).__name__}），请检查网络设置。') from None
            if body.get('error') or not body.get('device_code'):
                raise BadRequestError('飞书未返回有效的扫码申请，请稍后重试。')
            url = urlsplit(body.get('verification_uri_complete', ''))
            if url.scheme != 'https' or not url.hostname or not (
                url.hostname == 'feishu.cn' or url.hostname.endswith('.feishu.cn')
            ) or url.username or url.password:
                raise BadRequestError('飞书未返回有效的官方扫码地址。')
            query = dict(parse_qsl(url.query))
            query['from'] = 'onboard'
            url = urlunsplit(url._replace(query=urlencode(query)))
            # These are the registration protocol defaults when omitted by Feishu.
            interval = max(1, float(body.get('interval') or 5))
            duration = max(1, float(body.get('expire_in') or 600))
            if not math.isfinite(interval) or not math.isfinite(duration):
                raise BadRequestError('飞书返回了无效的扫码有效期，请重新获取二维码。')
            self.state = {'id': uuid4().hex, 'status': 'wait', 'image': await asyncio.to_thread(qr_image, url),
                          'expires_at': time.time() + duration, 'error': None}
            self.task = asyncio.create_task(self.poll(body['device_code'], interval, duration))
            return dict(self.state)

    def status(self, login_id):
        if not self.state or self.state['id'] != login_id:
            raise BadRequestError('扫码会话已失效，请重新获取二维码。')
        return dict(self.state)

    async def poll(self, device_code, interval, duration):
        try:
            async with asyncio.timeout(duration):
                while True:
                    try:
                        body = await registration_request('poll', device_code=device_code)
                    except httpx.HTTPError as exc:
                        self.state['error'] = f'暂时无法连接飞书（{type(exc).__name__}），正在重试。'
                        await asyncio.sleep(interval)
                        continue
                    self.state['error'] = None
                    if (body.get('user_info') or {}).get('tenant_brand') == 'lark':
                        raise BadRequestError('此二维码用于飞书接入，请使用飞书账号扫码；当前不支持 Lark 国际版。')
                    error = body.get('error')
                    if error in {'expired_token', 'invalid_grant'}:
                        self.state['status'] = 'expired'
                        return
                    if error == 'access_denied':
                        raise BadRequestError('已取消飞书扫码授权。可重新获取二维码。')
                    if error == 'slow_down':
                        interval += 5
                    elif error not in {None, '', 'authorization_pending'}:
                        raise BadRequestError('飞书拒绝了本次扫码申请，请重新获取二维码或联系飞书支持。')
                    elif not error and body.get('client_id') and body.get('client_secret'):
                        break
                    await asyncio.sleep(interval)
            # QR expiry bounds authorization polling, not validation or database writes.
            self.state['status'] = 'saving'
            result = await self.manager.configure_platform('feishu', enabled=True,
                app_id=body['client_id'], secret=body['client_secret'])
            self.state.update(status='confirmed', connection_id=result['connection_id'])
        except TimeoutError:
            self.state.update(status='expired', error=None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.update(status='error', error=getattr(exc, 'message',
                f'飞书扫码连接失败（{type(exc).__name__}）。请检查网络后重新获取二维码。'))
