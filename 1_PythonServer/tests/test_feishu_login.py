import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.errors import BadRequestError
from app.services.mobile import feishu_login
from app.services.mobile.feishu_login import FeishuLogin

BEGIN = dict(device_code='private-device-code', verification_uri_complete='https://accounts.feishu.cn/verify?code=test',
             interval=1, expire_in=60)
CREDS = dict(client_id='app', client_secret='private-secret', user_info={'tenant_brand': 'feishu'})


def test_qr_validation_and_credentials_stay_backend_only(monkeypatch):
    async def run():
        request = AsyncMock(side_effect=[BEGIN, CREDS])
        monkeypatch.setattr(feishu_login, 'registration_request', request)
        manager = SimpleNamespace(configure_platform=AsyncMock(return_value={'connection_id': 'feishu:app'}))
        login = FeishuLogin(manager)
        state = await login.start()
        assert state['image'].startswith('data:image/png;base64,')
        await login.task
        assert login.status(state['id'])['status'] == 'confirmed'
        assert 'private' not in str(login.status(state['id']))
        request.assert_any_await('begin', archetype='PersonalAgent', auth_method='client_secret', request_user_info='open_id tenant_brand')
        manager.configure_platform.assert_awaited_once_with('feishu', enabled=True, app_id='app', secret='private-secret')
    asyncio.run(run())


@pytest.mark.parametrize('response,status', [({'error': 'expired_token'}, 'expired'),
    ({'error': 'invalid_grant'}, 'expired'), ({'error': 'access_denied'}, 'error'),
    ({'error': 'unknown', 'error_description': 'private-secret'}, 'error'),
    (dict(CREDS, user_info={'tenant_brand': 'lark'}), 'error')])
def test_rejected_registration_never_saves_connection(monkeypatch, response, status):
    async def run():
        monkeypatch.setattr(feishu_login, 'registration_request', AsyncMock(side_effect=[BEGIN, response]))
        manager = SimpleNamespace(configure_platform=AsyncMock())
        login = FeishuLogin(manager)
        await login.start()
        await login.task
        assert login.state['status'] == status
        assert 'private-secret' not in str(login.state)
        manager.configure_platform.assert_not_called()
    asyncio.run(run())


def test_policy_failure_is_not_reported_as_success(monkeypatch):
    async def run():
        monkeypatch.setattr(feishu_login, 'registration_request', AsyncMock(side_effect=[BEGIN, CREDS]))
        manager = SimpleNamespace(configure_platform=AsyncMock(side_effect=BadRequestError('平台策略限制 21001')))
        login = FeishuLogin(manager)
        await login.start()
        await login.task
        assert login.state['status'] == 'error'
        assert '21001' in login.state['error']
        assert 'connection_id' not in login.state
    asyncio.run(run())


def test_pending_network_retry_and_slow_down(monkeypatch):
    async def run():
        monkeypatch.setattr(feishu_login, 'registration_request', AsyncMock(side_effect=[BEGIN,
            {'error': 'authorization_pending'}, httpx.ConnectTimeout('secret-url'), {'error': 'slow_down'}, CREDS]))
        sleep = AsyncMock()
        monkeypatch.setattr(feishu_login.asyncio, 'sleep', sleep)
        manager = SimpleNamespace(configure_platform=AsyncMock(return_value={'connection_id': 'feishu:app'}))
        login = FeishuLogin(manager)
        await login.start()
        await login.task
        assert [call.args[0] for call in sleep.await_args_list] == [1, 1, 6]
        assert login.state['status'] == 'confirmed'
    asyncio.run(run())


def test_new_qr_cancels_old_poll_and_stale_status(monkeypatch):
    async def run():
        entered = asyncio.Event()
        async def request(action, **_):
            if action == 'begin':
                return BEGIN
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(feishu_login, 'registration_request', request)
        manager = SimpleNamespace(configure_platform=AsyncMock())
        login = FeishuLogin(manager)
        first = await login.start()
        await entered.wait()
        old = login.task
        second = await login.start()
        assert first['id'] != second['id'] and old.cancelled()
        with pytest.raises(BadRequestError, match='失效'):
            login.status(first['id'])
        await login.close()
        manager.configure_platform.assert_not_called()
    asyncio.run(run())


def test_cannot_replace_qr_during_validation(monkeypatch):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def save(*args, **kwargs):
            entered.set()
            await release.wait()
            return {'connection_id': 'feishu:app'}
        monkeypatch.setattr(feishu_login, 'registration_request', AsyncMock(side_effect=[BEGIN, CREDS]))
        login = FeishuLogin(SimpleNamespace(configure_platform=save))
        await login.start()
        await entered.wait()
        with pytest.raises(BadRequestError, match='正在验证'):
            await login.start()
        release.set()
        await login.task
        assert login.state['status'] == 'confirmed'
    asyncio.run(run())
