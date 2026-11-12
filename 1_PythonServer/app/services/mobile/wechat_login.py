"""QR binding is short-lived; only confirmed credentials enter the global DB."""
import asyncio
import base64
import io
import time
from contextlib import suppress
from uuid import uuid4

import httpx
from app.core.errors import BadRequestError
from app.infra.secrets import encrypt_secret
from .wechat_transport import WeChatTransport, trusted_url


class WeChatLogin:
    def __init__(self, manager):
        self.manager = manager
        self.task = None
        self.state = None
        self.pin = ''
        self.lock = asyncio.Lock()

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def start(self):
        async with self.lock:
            await self.close()
            transport = WeChatTransport()
            result = await transport.call('get_bot_qrcode', {'local_token_list': []}, auth=False, params={'bot_type': '3'})
            if not result.get('qrcode') or not result.get('qrcode_img_content'):
                raise BadRequestError('微信未返回有效二维码。')
            def render():
                import qrcode
                output = io.BytesIO()
                qrcode.make(result['qrcode_img_content']).save(output, format='PNG')
                return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()
            self.state = {'id': uuid4().hex, 'status': 'wait', 'image': await asyncio.to_thread(render),
                          'expires_at': time.time() + 300, 'error': None}
            self.pin = ''
            self.task = asyncio.create_task(self.poll(transport, result['qrcode']))
            return dict(self.state)

    def status(self, login_id):
        if not self.state or self.state['id'] != login_id:
            raise BadRequestError('扫码会话已失效，请重新获取二维码。')
        return dict(self.state)

    def submit_pin(self, login_id, pin):
        self.status(login_id)
        if not pin.isascii() or not pin.isdecimal() or not 4 <= len(pin) <= 12:
            raise BadRequestError('请输入手机上显示的数字验证码。')
        self.pin = pin

    async def poll(self, transport, code):
        try:
            while time.time() < self.state['expires_at']:
                params = {'qrcode': code}
                if self.pin:
                    params['verify_code'] = self.pin
                try:
                    body = await transport.call('get_qrcode_status', auth=False, get=True, params=params, poll=True)
                except httpx.ReadTimeout:
                    continue
                status = body.get('status', 'wait')
                # Confirmation is visible only once credentials and owner access
                # are durably saved, so the UI cannot stop polling too early.
                self.state['status'] = 'saving' if status == 'confirmed' else status
                if status == 'scaned':
                    self.pin = ''
                elif status == 'scaned_but_redirect':
                    transport.base = trusted_url('https://' + body['redirect_host'])
                elif status == 'confirmed':
                    if not body.get('bot_token') or not body.get('ilink_bot_id'):
                        raise BadRequestError('微信确认结果缺少登录凭据，请重新扫码。')
                    bot_id = body['ilink_bot_id']
                    base = trusted_url(body.get('baseurl') or transport.base)
                    async with self.manager.lock:
                        key = await self.manager.save_platform('wechat', bot_id, {'enabled': True,
                            'token': encrypt_secret(body['bot_token']), 'api_base': base,
                            'bot': {'id': bot_id, 'first_name': '微信 ClawBot'}})
                        # The QR-confirming owner is authorized; other identities
                        # never acquire permissions merely by sending first.
                        owner = body.get('ilink_user_id')
                        if owner:
                            peer = f'{key}:{owner}:{owner}'
                            await self.manager.adapters[key].confirm_peer(peer, {'connection_id': key, 'platform': 'wechat',
                                'bot_id': bot_id, 'user_id': owner, 'chat_id': owner, 'name': owner,
                                'allowed': True, 'reviewed': True})
                    self.state.update(status='confirmed', connection_id=key)
                    return
                elif status in {'expired', 'verify_code_blocked', 'binded_redirect'}:
                    return
                await asyncio.sleep(1)
            self.state['status'] = 'expired'
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.update(status='error', error=getattr(exc, 'message', f'扫码连接失败（{type(exc).__name__}），请重新获取二维码。'))
