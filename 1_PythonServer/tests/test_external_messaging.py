import asyncio
import importlib.util
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infra.database.schema import ensure_database_schema, SCHEMA_STATEMENTS
from app.repositories.mobile_repository import MobileRepository
from app.services.mobile import manager, messaging, service, telegram_transport
from app.api.routes.tools import host_capabilities as api
from app.domain.tools.host_capabilities import HostCapability


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / 'global.db'
    ensure_database_schema(path)
    return MobileRepository(path)


def save_bot(repo, number=12, enabled=True):
    config = {'token': 'encrypted-secret', 'enabled': enabled, 'api_base': 'https://api.telegram.org',
              'bot': {'id': number, 'first_name': 'Bot', 'username': f'bot{number}'}}
    repo.save_connection(f'telegram:{number}', 'telegram', str(number), config, select=True)
    return config


def test_v51_upgrade_preserves_scopes_credentials_selection_and_pending_work(tmp_path):
    from app.migrations.global_db.v50_to_v51 import MOBILE_SCHEMA
    path = tmp_path / 'v51.db'
    peer = 'telegram:12:7:7'
    config = {'token': 'encrypted-not-plaintext', 'enabled': True, 'bot': {'id': 12}}
    records = [
        ('settings','telegram',config), ('peers',peer,{'bot_id':12,'chat_id':7,'user_id':7,'allowed':True}),
        ('selection',peer,{'project_id':'p','session_id':'s'}),
        ('jobs','job',{'peer':peer,'status':'running','user_message_id':'mobile_job'}),
        ('callbacks','button',{'peer':peer,'action':'new'}),
        ('inbox','telegram:12:88',{'channel':'telegram:12','update':{'update_id':88}}),
        ('outbox','delivery',{'peer':peer,'parts':['final'],'sent':0}),
        ('delivered','delivery',True), ('staged',peer+':p:s',[{'reference':{'id':'image'}}]),
        ('delivered','mobile_job:result',True),
        ('peers','telegram:11:7:7',{'bot_id':11,'chat_id':7,'user_id':7,'allowed':True}),
        ('jobs','old-bot-job',{'peer':'telegram:11:7:7','status':'running','user_message_id':'mobile_old'}),
    ]
    with sqlite3.connect(path) as db:
        for sql in (*SCHEMA_STATEMENTS, *MOBILE_SCHEMA):
            db.execute(sql)
        db.execute("INSERT INTO schema_migrations VALUES (51,'test','now')")
        for ns, key, value in records:
            db.execute('INSERT INTO mobile_records VALUES (?,?,?,?)', (ns,key,json.dumps(value),1))
        db.execute("INSERT INTO mobile_receipts VALUES ('telegram:12','88',1)")
    ensure_database_schema(path)
    ensure_database_schema(path)
    repo = MobileRepository(path)
    configurations={r['connection_id']:r['config'] for r in repo.connections()}
    assert configurations['telegram:12'] == dict(config, allowed_collections=['project'])
    assert not configurations['telegram:11']['enabled'] and 'token' not in configurations['telegram:11']
    assert repo.get('settings','telegram_selected') == 'telegram:12'
    assert repo.get('settings','telegram') is None
    scoped = repo.scoped('telegram:12')
    for ns, key, value in records[1:-2]:
        assert scoped.get(ns,key) == value
    assert repo.scoped('telegram:11').get('jobs','old-bot-job')['status']=='running'
    assert not scoped.receive('telegram:12','88',{})
    assert not repo.scoped('telegram:13').list('outbox')


def test_connection_isolation_and_indexed_queries(repo):
    a, b = repo.scoped('telegram:12'), repo.scoped('other:12')
    a.put('peers','a',{'user_id':'same'})
    b.put('peers','b',{'user_id':'same'})
    a.put('selection','a',{'session_id':'one'})
    b.put('selection','b',{'session_id':'two'})
    assert a.list('peers') == [('a',{'user_id':'same'})]
    assert b.get('selection','a') is None
    b.delete('selection','a')
    assert a.get('selection','a')['session_id'] == 'one'
    with pytest.raises(ValueError):
        b.put('peers','a',{'allowed':True})
    assert a.receive('telegram:12','1',{})
    assert b.receive('other:12','1',{})
    repo.create_job('job',{'peer':'a','references':[]})
    assert a.get('jobs','job')['connection_id'] == 'telegram:12'
    assert not b.list('jobs')
    with sqlite3.connect(repo.path) as db:
        plan = db.execute("EXPLAIN QUERY PLAN SELECT record_key,payload FROM mobile_records WHERE namespace=? AND connection_id=? ORDER BY updated_at", ('peers','telegram:12')).fetchall()
        assert any('mobile_records_connection' in str(row) for row in plan)


def test_multi_connection_uses_one_desktop_and_routes_final_to_original_bot(repo, monkeypatch):
    async def run():
        save_bot(repo,12); save_bot(repo,13)
        monkeypatch.setattr(service,'decrypt_secret',lambda _: 'test-secret')
        hub = manager.MobileAccessService(repo)
        for row in repo.connections():
            await hub.install(row)
        a,b=hub.adapters.values()
        assert a.desktop is b.desktop is hub.desktop
        for adapter, peer in [(a,'a'),(b,'b')]:
            adapter.repository.put('peers',peer,{'connection_id':adapter.repository.connection_id,
                'allowed':True,'bot_id':adapter.config['bot']['id']})
            adapter.result=AsyncMock()
        assert await hub.is_authorized('a')
        assert await hub.is_authorized('b')
        await hub.result({'peer':'a'},'done','reply')
        a.result.assert_awaited_once(); b.result.assert_not_awaited()
        assert len((await hub.status())['connections'])==2
        assert 'test-secret' not in json.dumps(await hub.status())
    asyncio.run(run())


def test_source_is_visible_once_in_text_and_image_parts(repo, monkeypatch, tmp_path):
    from app.services.mobile import context
    async def run():
        adapter=service.MobileService(repo.scoped('telegram:12'))
        adapter.config={'bot':{'id':12},'enabled':True}
        peer='telegram:12:7:7'; target={'project_id':'p','session_id':'s'}
        await adapter.put('peers',peer,{'allowed':True,'user_id':7,'chat_id':7,'bot_id':12})
        monkeypatch.setattr(context,'get_project_service',lambda:NS(get_project=lambda _:NS(root_path=str(tmp_path),project_id='p',project_kind='project')))
        monkeypatch.setattr(context,'get_project_conversation_service',lambda:NS(get_session=lambda *_:NS()))
        key=adapter.staging_key(peer,target)
        await adapter.put('staged',key,[{'reference':{'id':'a','fileName':'photo.png','filePath':'photo.png'}}])
        adapter.desktop.submit=AsyncMock(return_value='job'); adapter.reply=AsyncMock()
        await adapter.submit(peer,target,'处理这张图',[])
        args=adapter.desktop.submit.call_args.args
        assert args[2].count('[消息来源]')==1
        assert '连接 ID：telegram:12' in args[2]
        assert '用户 ID：7' in args[2] and '\n聊天 ID：7' in args[2]
        assert '不展示思考、工具调用及中途文字' in args[2]
        assert '单向发送不等待用户回复' in args[2]
        assert args[4][0]['text']==args[2] and args[4][1]['type']=='image_ref'
    asyncio.run(run())


def test_send_explicit_other_recipient_external_file_and_full_caption(repo, tmp_path, monkeypatch):
    async def run():
        save_bot(repo)
        file=tmp_path/'outside.pptx';file.write_bytes(b'original')
        calls=[]
        class Transport:
            def __init__(self,*args): pass
            async def send_once(self,method,payload,**kwargs):
                calls.append((method,payload,kwargs))
                return {'message_id':len(calls)}
        monkeypatch.setattr(messaging,'TelegramTransport',Transport)
        monkeypatch.setattr(messaging,'decrypt_secret',lambda _: 'secret')
        monkeypatch.setattr(messaging,'target_header',lambda _: 'Project / Session')
        caption='中文😀'*2000
        request=api.ExternalMessagingRequest(action='send_file',platform='telegram',connection_id='telegram:12',chat_id='999',file_path=str(file),caption=caption)
        result=await messaging.execute(repo,request,NS(project_id='p',session_id='s'))
        assert result['ok'] and result['status']=='sent'
        assert all(call[1]['chat_id']=='999' for call in calls)
        assert calls[0][2]['document']==file
        assert len(calls[0][1]['caption'].encode('utf-16-le'))//2<=1024
        assert calls[0][1]['caption']+''.join(call[1]['text'] for call in calls[1:])=='Project / Session\n\n'+caption
        assert file.read_bytes()==b'original'
        assert not repo.list('jobs') and not repo.list('outbox')
    asyncio.run(run())


@pytest.mark.parametrize('confirmed', [False, True])
def test_unknown_or_partial_result_never_retries(repo, tmp_path, monkeypatch, confirmed):
    async def run():
        save_bot(repo)
        file=tmp_path/'doc';file.write_bytes(b'x')
        send=AsyncMock(side_effect=([{'message_id':123}] if confirmed else [])+[
            telegram_transport.TelegramSendError('unknown',status='unknown')])
        monkeypatch.setattr(messaging,'TelegramTransport',lambda *_:NS(send_once=send))
        monkeypatch.setattr(messaging,'decrypt_secret',lambda _: 'secret')
        result=await messaging.telegram_send_file(repo.connections()[0],'99',file,'x'*5000)
        assert result['ok'] is False and result['status']==('partial' if confirmed else 'unknown')
        assert result['message_ids']==([123] if confirmed else [])
        assert result['file_sent'] is (True if confirmed else None)
        assert send.await_count==1+int(confirmed)
    asyncio.run(run())


@pytest.mark.parametrize('failure,status', [(httpx.ConnectTimeout,'not_sent'),(httpx.ReadTimeout,'unknown'),(httpx.WriteError,'unknown')])
def test_send_network_errors_are_explicit_and_redacted(monkeypatch, tmp_path, failure, status):
    async def run():
        file=tmp_path/'doc';file.write_bytes(b'x')
        @asynccontextmanager
        async def lease(_):
            yield NS(post=AsyncMock(side_effect=failure('https://api.telegram.org/botPRIVATE/sendDocument')))
        monkeypatch.setattr(telegram_transport,'lease_http_client',lease)
        monkeypatch.setattr(telegram_transport,'get_shared_http_client',lambda:None)
        monkeypatch.setattr(telegram_transport,'get_http_timeout',lambda:httpx.Timeout(120,connect=10))
        with pytest.raises(telegram_transport.TelegramSendError) as caught:
            await telegram_transport.TelegramTransport('PRIVATE').send_once('sendDocument',{'chat_id':'7'},document=file)
        assert caught.value.status==status
        assert 'PRIVATE' not in str(caught.value)
    asyncio.run(run())


def test_real_httpx_multipart_streams_file_without_whole_file_read(monkeypatch,tmp_path):
    async def run():
        file=tmp_path/'big.bin';file.write_bytes(b'x'*(4*1024*1024))
        chunks=[]
        class Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self,request):
                async for chunk in request.stream:
                    chunks.append(len(chunk))
                return httpx.Response(200,json={'ok':True,'result':{'message_id':456}})
        client=httpx.AsyncClient(transport=Transport())
        @asynccontextmanager
        async def lease(_): yield client
        monkeypatch.setattr(telegram_transport,'lease_http_client',lease)
        monkeypatch.setattr(telegram_transport,'get_shared_http_client',lambda:client)
        monkeypatch.setattr(telegram_transport,'get_http_timeout',lambda:httpx.Timeout(120,connect=10))
        monkeypatch.setattr(Path,'read_bytes',lambda _:pytest.fail('whole file read'))
        try:
            result=await telegram_transport.TelegramTransport('test').send_once('sendDocument',{'chat_id':'7'},document=file)
            assert result['message_id']==456 and sum(chunks)>file.stat().st_size
            assert max(chunks)<=128*1024
        finally:
            await client.aclose()
    asyncio.run(run())


def test_bridge_requires_declared_capability_not_a_tool_name(repo, monkeypatch):
    from app.services.tools.host_capability_access import HostCapabilityAccessService
    access=HostCapabilityAccessService()
    monkeypatch.setattr(api,'get_host_capability_access_service',lambda:access)
    monkeypatch.setattr(service,'get_mobile_service',lambda:NS(repository=repo))
    save_bot(repo)
    app=FastAPI(); app.include_router(api.router)
    grant=access.issue_grant(tool_name='a-user-created-tool',tool_call_id='call',provider_id=None,model_id=None,
                            project_id=None,session_id=None,lifetime_seconds=60,capabilities=(HostCapability.EXTERNAL_MESSAGING,))
    with TestClient(app) as client:
        body={'platform':'telegram','action':'list_connections'}
        assert client.post('/tools/capabilities/external-messaging',json=body).status_code==401
        result=client.post('/tools/capabilities/external-messaging',json=body,headers={'Authorization':'Bearer '+grant.token})
        assert result.status_code==200 and result.json()['connections'][0]['connection_id']=='telegram:12'
        assert 'secret' not in result.text
        invalid=client.post('/tools/capabilities/external-messaging',json={'action':'send_file','platform':'telegram'},headers={'Authorization':'Bearer '+grant.token})
        assert invalid.status_code==422


def test_independent_tool_requires_explicit_ids_and_uses_its_runtime_timeout(tmp_path, monkeypatch):
    root=Path(__file__).resolve().parents[2]/'Data/tools/0efca349-3362-5aa1-8f15-203dab248ea2'
    spec=importlib.util.spec_from_file_location('telegram_file_tool',root/'program/main.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    captured=[]
    monkeypatch.setattr(module,'call_host_capability',lambda *args,**kwargs:captured.append((args,kwargs)) or {'ok':True})
    monkeypatch.setenv('TIANCE_WORKSPACE_ROOT',str(tmp_path))
    with pytest.raises(ValueError,match='chat_id'):
        module.run({'action':'send_file','platform':'telegram','connection_id':'telegram:12','file_path':'file'})
    module.run({'action':'send_file','platform':'telegram','connection_id':'telegram:12','chat_id':'99','file_path':'file'})
    args,kwargs=captured[0]
    assert args[0]=='external_messaging' and args[1]['file_path']==str(tmp_path/'file')
    config=json.loads((root/'.tool/tool.json').read_text(encoding='utf-8'))
    assert kwargs['timeout_seconds']==config['runtime']['timeout_seconds']
