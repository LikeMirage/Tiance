import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.infra.database.schema import ensure_database_schema
from app.repositories.mobile_repository import MobileRepository
from app.services.mobile.activity import record_activity
from app.services.mobile.manager import MobileAccessService
from app.services.mobile.service import MobileService
from app.services.mobile.telegram_transport import TelegramError


@pytest.fixture
def repository(tmp_path):
    path = tmp_path / 'activity.db'
    ensure_database_schema(path)
    return MobileRepository(path)


def test_activity_is_bounded_scoped_paginated_and_keeps_delivery_records(repository, monkeypatch):
    monkeypatch.setattr(MobileRepository, 'ACTIVITY_LIMIT', 5)
    first = repository.scoped('telegram:1')
    second = repository.scoped('telegram:2')
    first.put('outbox', 'pending', {'parts': ['keep']})
    first.receive('telegram:1', 'update', {'update': {}})
    for index in range(9):
        first.append_activity('message_received', 'info', {'update_id': index})
    second.append_activity('enabled', 'info', {})
    page = first.activity_page(0, 2)
    assert page['total'] == 5 and page['retention'] == 5
    assert [row['details']['update_id'] for row in page['items']] == [8, 7]
    assert [row['details']['update_id'] for row in first.activity_page(2, 3)['items']] == [6, 5, 4]
    assert second.activity_page()['total'] == 1
    assert repository.scoped('').activity_page()['total'] == 0
    assert first.get('outbox', 'pending')['parts'] == ['keep']
    assert not first.receive('telegram:1', 'update', {})


def test_log_sanitizes_secrets_and_failures_do_not_fail_business(repository, monkeypatch):
    async def run():
        scoped = repository.scoped('telegram:1')
        error = httpx.HTTPStatusError('secret-body', request=httpx.Request('POST', 'https://example.com/botSECRET'),
                                      response=httpx.Response(502))
        await record_activity(scoped, 'receive_failed', error=error, token='SECRET', body='secret-body', chat_id=1)
        row = scoped.activity_page()['items'][0]
        assert row['details'] == {'chat_id': 1, 'error_type': 'HTTPStatusError', 'http_status': 502}
        assert 'SECRET' not in json.dumps(row) and 'secret-body' not in json.dumps(row)
        monkeypatch.setattr(scoped, 'append_activity', lambda *_: (_ for _ in ()).throw(OSError('SECRET')))
        await record_activity(scoped, 'enabled')  # diagnostic persistence is not business persistence
    asyncio.run(run())


def test_receiver_logs_failure_transition_and_recovery_once(repository):
    async def run():
        host = MobileService(repository.scoped('telegram:1'))
        host.config = {'bot': {'id': 1}, 'enabled': True}
        host.get = AsyncMock(return_value=0)
        host.activity = AsyncMock()
        calls = 0
        async def receive(*_, **__):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise TelegramError('safe', retry_after=0)
            if calls == 3:
                return []
            raise asyncio.CancelledError
        host.transport = SimpleNamespace(call=receive)
        # Patch just this module's sleep while retaining asyncio cancellation behavior.
        from unittest.mock import patch
        with patch('app.services.mobile.service.asyncio.sleep', new=AsyncMock()):
            with pytest.raises(asyncio.CancelledError):
                await host.receive_loop()
        assert [c.args[0] for c in host.activity.call_args_list] == ['receive_failed', 'receive_recovered']
    asyncio.run(run())


def test_manager_log_selection_does_not_install_or_start_adapter(repository):
    async def run():
        repository.put('settings', 'telegram_selected', 'telegram:2')
        repository.scoped('telegram:1').append_activity('enabled', 'info', {})
        repository.scoped('telegram:2').append_activity('disabled', 'info', {})
        manager = MobileAccessService(repository)
        assert (await manager.activity())['items'][0]['event'] == 'disabled'
        assert (await manager.activity('telegram:1'))['items'][0]['event'] == 'enabled'
        assert manager.adapters == {}
    asyncio.run(run())


@pytest.mark.parametrize('response', [
    httpx.Response(502, text='<html>gateway SECRET</html>'),
    httpx.Response(429, json={'ok': False, 'description': 'SECRET', 'parameters': {'retry_after': 2}}),
])
def test_configuration_failure_keeps_safe_http_metadata(repository, monkeypatch, response):
    from contextlib import asynccontextmanager
    from app.services.mobile import telegram_transport
    from app.services.mobile.telegram_config import validate_configuration
    from app.core.errors import BadRequestError

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
            @asynccontextmanager
            async def lease(_):
                yield client
            monkeypatch.setattr(telegram_transport, 'get_shared_http_client', lambda: client)
            monkeypatch.setattr(telegram_transport, 'lease_http_client', lease)
            with pytest.raises(BadRequestError) as captured:
                await validate_configuration({}, token='SECRET', enabled=True, api_base='https://example.test')
            await record_activity(repository.scoped('telegram:1'), 'configuration_failed', error=captured.value)
        row = repository.scoped('telegram:1').activity_page()['items'][0]
        assert row['details']['http_status'] == response.status_code
        assert row['details']['error_type']
        assert 'SECRET' not in json.dumps(row)
        assert 'example.test' not in json.dumps(row)
    asyncio.run(run())
