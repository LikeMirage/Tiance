import asyncio
import json
import sqlite3
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from app.infra.database.schema import ensure_database_schema, SCHEMA_STATEMENTS, SCHEMA_VERSION
from app.repositories.mobile_repository import MobileRepository
from app.services.mobile import context, desktop_bridge, service
from app.services.mobile.service import MobileService
from app.services.mobile.manager import MobileAccessService
from app.services.mobile import telegram_config
from app.services.mobile.telegram_transport import split_message, safe_filename, TelegramError


@pytest.fixture
def repository(tmp_path):
    path = tmp_path / 'app.db'
    ensure_database_schema(path)
    return MobileRepository(path)


@pytest.fixture
def host(repository, monkeypatch, tmp_path):
    mobile = MobileService(repository)
    mobile.config = {'bot':{'id':12}, 'enabled':True}
    mobile.transport = NS(call=AsyncMock())
    project = NS(root_path=str(tmp_path), name='Project A', project_id='p', project_kind='project', category_id='cat')
    session = NS(title='Session A', model_id='model', provider_id='provider')
    monkeypatch.setattr(context, 'get_project_service', lambda: NS(get_project=lambda _:project))
    monkeypatch.setattr(context, 'get_project_conversation_service', lambda: NS(get_session=lambda *_:session))
    return mobile


def test_upgrade_50_preserves_existing_data(tmp_path):
    path=tmp_path/'old.db'
    with sqlite3.connect(path) as conn:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.execute("INSERT INTO schema_migrations VALUES(50,'test','now')")
        conn.execute("INSERT INTO app_metadata VALUES('keep','value','now')")
    ensure_database_schema(path)
    ensure_database_schema(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT value FROM app_metadata WHERE key='keep'").fetchone()[0]=='value'
        assert conn.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==SCHEMA_VERSION


def test_receipt_dedup_and_atomic_staged_claim(repository):
    assert repository.receive('telegram:12','99',{'text':'hello'})
    assert not repository.receive('telegram:12','99',{'text':'duplicate'})
    assert len(repository.list('inbox'))==1
    refs=[{'reference':{'id':'a'}},{'reference':{'id':'b'}}]
    repository.append_staged('target',refs)
    repository.append_staged('target',refs)
    repository.create_job('j',{'references':refs[:1]},'target')
    assert repository.get('staged','target')==refs[1:]
    assert repository.get('jobs','j')['references']==refs[:1]


def test_telegram_limits_and_filename():
    text='中文😀\n'*4000
    parts=list(split_message(text))
    assert ''.join(parts)==text
    assert all(len(p.encode('utf-16-le'))//2<=3500 for p in parts)
    assert '/' not in safe_filename('../../CON.txt')
    assert safe_filename('CON.txt')=='_CON.txt'


def test_unknown_sender_cannot_submit_or_choose(host):
    async def run():
        host.desktop.submit=AsyncMock()
        message={'message_id':4,'chat':{'id':7,'type':'private'},'from':{'id':7,'first_name':'A'},'text':'/projects'}
        await host.dispatch('i',{'channel':'telegram:12','update':{'update_id':1,'message':message}})
        assert not (await host.get('peers','telegram:12:7:7'))['allowed']
        assert not await host.records('callbacks')
        assert not await host.records('selection')
        host.desktop.submit.assert_not_awaited()
        item=(await host.records('outbox'))[0][1]
        assert 'Project A' not in item['header'] and not item['rows']
    asyncio.run(run())


def test_reply_selection_and_late_result_are_independent(host):
    async def run():
        peer='telegram:12:7:7'; a={'project_id':'p','session_id':'a'}; b=dict(a,session_id='b')
        await host.put('selection',peer,b)
        await host.put('messages',peer+':100',{'target':a})
        await host.result(dict(a,peer=peer,user_message_id='u',status='running'),'done','final A')
        assert await host.get('selection',peer)==b
        assert await host.navigation.message_target(peer,{'reply_to_message':{'message_id':100}})==a
        assert await host.get('selection',peer)==a
        with pytest.raises(Exception,match='对应关系'):
            await host.navigation.message_target(peer,{'reply_to_message':{'message_id':101}})
        assert await host.get('selection',peer)==a
    asyncio.run(run())


def test_callback_owned_by_sender(host):
    async def run():
        peer='telegram:12:7:7'
        await host.put('peers',peer,{'allowed':True})
        button=await host.navigation.button('another-peer','choose','new',target={'project_id':'p'})
        host.navigation.action=AsyncMock()
        await host.dispatch('i',{'channel':'telegram:12','update':{'update_id':1,'callback_query':{
            'id':'c','data':button['callback_data'],'from':{'id':7},'message':{'chat':{'id':7,'type':'private'}}}}})
        host.navigation.action.assert_not_awaited()
        await asyncio.gather(*host.work)
    asyncio.run(run())


def test_navigation_reply_keeps_current_target_header(host):
    async def run():
        peer='telegram:12:7:7'; target={'project_id':'p','session_id':'a'}
        await host.put('selection',peer,target)
        await host.reply(peer,'选择项目')
        item=(await host.records('outbox'))[0][1]
        assert item['target']==target
        assert 'Project A' in item['header'] and 'Session A' in item['header']
    asyncio.run(run())


def test_busy_target_and_stop_old_job_do_not_interrupt_new_run(repository, monkeypatch):
    async def run():
        manager=NS(get_run_status=AsyncMock(return_value={'running':True}), stop=AsyncMock())
        monkeypatch.setattr(desktop_bridge,'get_conversation_run_manager',lambda:manager)
        bridge=desktop_bridge.MobileDesktopBridge(repository,AsyncMock())
        bridge.owner='ui'; bridge.last_seen=time.monotonic()
        target={'project_id':'p','session_id':'a'}
        with pytest.raises(Exception,match='正在运行'):
            await bridge.submit('peer',target,'hi',[])
        assert not repository.list('jobs')
        assert not await bridge.stop(target,'old-user-message')
        manager.stop.assert_not_awaited()
    asyncio.run(run())


def test_preparation_is_idempotent_and_uses_ordinary_runner(repository, monkeypatch):
    async def run():
        manager=NS(get_run_status=AsyncMock(return_value={'running':False}),start=AsyncMock(return_value='subscription'))
        monkeypatch.setattr(desktop_bridge,'get_conversation_run_manager',lambda:manager)
        monkeypatch.setattr(desktop_bridge,'get_project_conversation_stream_service',lambda:NS(validate_conversation_target=lambda _:None))
        bridge=desktop_bridge.MobileDesktopBridge(repository,AsyncMock())
        bridge.owner='ui'; bridge.last_seen=time.monotonic(); bridge.follow=AsyncMock()
        target={'project_id':'p','session_id':'a'}
        key=await bridge.submit('peer',target,'original',[])
        payload=dict(target,provider_id='provider',model_id='model',messages=[{'role':'user','message_id':'mobile_'+key,'content':'substituted'}])
        await bridge.prepare('ui',key,payload,None)
        await bridge.prepare('ui',key,payload,None)
        await asyncio.gather(*bridge.tasks)
        assert manager.start.await_count==1
        assert manager.start.call_args.args[0].messages[0].content=='original'
    asyncio.run(run())


def test_only_run_settlement_delivers_final_answer(repository, monkeypatch):
    async def run():
        events=[{'kind':'done'}, {'kind':'tool_result','tool_result':{'call_id':'x'}},
                {'kind':'conversation_run_settled','status':'done','assistant_message_id':'final'}]
        async def stream(_):
            for event in events:
                yield event
        monkeypatch.setattr(desktop_bridge,'get_conversation_run_manager',lambda:NS(stream=stream))
        monkeypatch.setattr(desktop_bridge,'get_project_conversation_service',lambda:NS(get_message=lambda *_:NS(content='The final answer',tool_calls=[])))
        sink=AsyncMock(); bridge=desktop_bridge.MobileDesktopBridge(repository,sink)
        await bridge.follow('j',{'project_id':'p','session_id':'a'},None)
        sink.assert_awaited_once()
        assert sink.call_args.args[1:] == ('done','The final answer')
    asyncio.run(run())


def test_mailbox_resync_observes_same_run_without_restarting(repository, monkeypatch):
    async def run():
        original=NS(run_id='original'); resumed=NS(run_id='original')
        async def stream(subscription):
            if subscription is original:
                raise desktop_bridge.ConversationStreamResyncRequiredError()
            yield {'kind':'conversation_run_settled','status':'done','assistant_message_id':'final'}
        manager=NS(stream=stream,subscribe=AsyncMock(return_value=resumed),start=AsyncMock())
        monkeypatch.setattr(desktop_bridge,'get_conversation_run_manager',lambda:manager)
        monkeypatch.setattr(desktop_bridge,'get_project_conversation_service',lambda:NS(get_message=lambda *_:NS(content='final',tool_calls=[])))
        sink=AsyncMock(); bridge=desktop_bridge.MobileDesktopBridge(repository,sink)
        await bridge.follow('j',{'project_id':'p','session_id':'a'},original)
        manager.subscribe.assert_awaited_once_with('p','a',expected_run_id='original')
        manager.start.assert_not_awaited()
        assert sink.call_args.args[1:] == ('done','final')
    asyncio.run(run())


def test_resync_after_settlement_uses_original_user_turn(repository, monkeypatch):
    async def run():
        async def stream(_):
            raise desktop_bridge.ConversationStreamResyncRequiredError()
            yield
        manager=NS(stream=stream,subscribe=AsyncMock(side_effect=desktop_bridge.NotFoundError('finished')))
        get_turn=lambda *args:NS(run_outcomes=[NS(status='done',error_message=None)],
                               items=[NS(role='assistant',message_id='final',tool_calls=[])])
        monkeypatch.setattr(desktop_bridge,'get_conversation_run_manager',lambda:manager)
        monkeypatch.setattr(desktop_bridge,'get_project_conversation_service',lambda:NS(
            get_message_turn=get_turn,get_message=lambda *_:NS(content='saved final',tool_calls=[])))
        sink=AsyncMock(); bridge=desktop_bridge.MobileDesktopBridge(repository,sink)
        await bridge.follow('j',{'project_id':'p','session_id':'a','user_message_id':'original-user'},NS(run_id='original'))
        assert sink.call_args.args[1:] == ('done','saved final')
    asyncio.run(run())


def test_revocation_cancels_pending_submission_and_restores_files(host):
    async def run():
        peer='telegram:12:7:7'; target={'project_id':'p','session_id':'a'}
        await host.put('peers',peer,{'bot_id':12,'allowed':True})
        ref={'reference':{'id':'file'}}
        await host.put('jobs','pending',dict(target,peer=peer,status='preparing',user_message_id='u',references=[ref]))
        await host.authorize(peer,False)
        assert not await host.get('jobs','pending')
        assert await host.get('staged',host.staging_key(peer,target)) == [ref]
        assert not await host.is_authorized(peer)
    asyncio.run(run())


def test_failed_start_restores_preparation_state(repository, monkeypatch):
    async def run():
        manager=NS(start=AsyncMock(side_effect=desktop_bridge.ConflictError('busy')))
        monkeypatch.setattr(desktop_bridge,'get_conversation_run_manager',lambda:manager)
        monkeypatch.setattr(desktop_bridge,'get_project_conversation_stream_service',lambda:NS(validate_conversation_target=lambda _:None))
        sink=AsyncMock(); bridge=desktop_bridge.MobileDesktopBridge(repository,sink); bridge.owner='ui'
        job={'project_id':'p','session_id':'a','peer':'peer','status':'preparing','user_message_id':'u','content':'hi','references':[]}
        repository.put('jobs','j',job)
        payload=dict(project_id='p',session_id='a',provider_id='provider',model_id='model',messages=[dict(role='user',message_id='u',content='hi')])
        await bridge.prepare('ui','j',payload,None)
        assert sink.call_args.args[0]['status']=='preparing'
        assert not repository.get('jobs','j')
    asyncio.run(run())


def test_stopping_one_run_does_not_block_another_preparation(repository, monkeypatch):
    async def run():
        entered=asyncio.Event(); release=asyncio.Event()
        async def stop(*args, **kwargs):
            entered.set(); await release.wait(); return True
        manager=NS(get_run_status=AsyncMock(return_value={'running':False,'run_id':'original'}),stop=stop)
        monkeypatch.setattr(desktop_bridge,'get_conversation_run_manager',lambda:manager)
        bridge=desktop_bridge.MobileDesktopBridge(repository,AsyncMock()); bridge.owner='ui'; bridge.last_seen=time.monotonic()
        task=asyncio.create_task(bridge.stop({'project_id':'p','session_id':'a'}))
        await asyncio.wait_for(entered.wait(),1)
        try:
            key=await asyncio.wait_for(bridge.submit('peer',{'project_id':'p','session_id':'b'},'hi',[]),1)
            assert repository.get('jobs',key)['session_id']=='b'
        finally:
            release.set(); await task
    asyncio.run(run())


def test_dispatch_shutdown_preserves_unfinished_receipt(host):
    async def run():
        entered=asyncio.Event()
        await host.put('inbox','pending',{'channel':'telegram:12','update':{}})
        async def dispatch(key,record):
            await host.put('inbox',key,dict(record,processing=True,peer='peer'))
            entered.set(); await asyncio.Event().wait()
        host.dispatch=dispatch
        task=asyncio.create_task(host.dispatch_loop())
        await asyncio.wait_for(entered.wait(),1)
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        assert (await host.get('inbox','pending'))['processing']
    asyncio.run(run())


def test_new_mobile_session_does_not_activate_desktop(monkeypatch):
    captured={}
    monkeypatch.setattr(context,'resolve_target',lambda *a,**k:(NS(project_id='p'),None))
    def create(pid,payload):
        captured.update(payload.model_dump(exclude_unset=True)); return NS(session_id='new')
    monkeypatch.setattr(context,'create_conversation',create)
    assert context.new_conversation({'project_id':'p'})=={'project_id':'p','session_id':'new'}
    assert captured=={'activate':False,'created_by':'user'}


def test_nested_groups_do_not_mix_siblings(monkeypatch):
    nodes=[NS(session_id=id,parent_session_id=parent,relation_kind=relation,function_type=ft,deleted_at=None)
           for id,parent,relation,ft in [('a',None,'root',None),('b','a','child',None),
               ('c','a','functional','memory_compaction'),('d','b','child',None)]]
    sessions=[NS(session_id=n.session_id) for n in nodes]
    monkeypatch.setattr(context,'get_project_conversation_service',lambda:NS(get_list_data=lambda *a,**k:(0,sessions,nodes,[],None,{})))
    assert [s.session_id for s,_ in context.session_children('p')]==['a']
    assert [s.session_id for s,_ in context.session_children('p','a','child')]==['b']
    assert [s.session_id for s,_ in context.session_children('p','b','child')]==['d']


def test_webhook_conflict_does_not_overwrite_saved_configuration(host, monkeypatch):
    async def run():
        monkeypatch.setattr(telegram_config,'decrypt_secret',lambda _: 'old-token')
        calls=[]
        class Transport:
            def __init__(self,*args): pass
            async def call(self,method,*args):
                calls.append(method)
                return {'id':12,'username':'bot','first_name':'Bot'} if method=='getMe' else {'url':'https://existing'}
        monkeypatch.setattr(telegram_config,'TelegramTransport',Transport)
        manager=MobileAccessService(host.repository)
        host.repository.save_connection('telegram:12','telegram','12',{'token':'encrypted','enabled':False},select=True)
        with pytest.raises(Exception,match='Webhook'):
            await manager.configure(token='new-token',enabled=True,api_base='https://api.telegram.org')
        assert host.repository.connections()[0]['config']=={'token':'encrypted','enabled':False}
        assert calls==['getMe','getWebhookInfo']
    asyncio.run(run())


def test_first_configuration_encrypts_token_and_status_never_returns_it(host,monkeypatch):
    async def run():
        class Transport:
            def __init__(self,*args): pass
            async def call(self,method,*args):
                return {'id':12,'username':'test_bot','first_name':'Test'} if method=='getMe' else {}
        monkeypatch.setattr(telegram_config,'TelegramTransport',Transport)
        monkeypatch.setattr(telegram_config,'encrypt_secret',lambda value:'encrypted-'+value)
        manager=MobileAccessService(host.repository)
        status=await manager.configure(token='secret-token',enabled=True,api_base='https://api.telegram.org')
        assert status['has_token'] and status['enabled']
        assert 'secret-token' not in json.dumps(status)
        assert host.repository.connections()[0]['config']['token']=='encrypted-secret-token'
    asyncio.run(run())


def test_download_target_frozen_and_caption_waits_for_full_file(host, monkeypatch):
    async def run():
        peer='telegram:12:7:7'; a={'project_id':'p','session_id':'a'}; b=dict(a,session_id='b')
        await host.put('peers',peer,{'allowed':True,'user_id':7,'chat_id':7})
        await host.put('selection',peer,a)
        downloaded=asyncio.Event()
        class Transport:
            async def download(self,file_id,path):
                await downloaded.wait()
                path.parent.mkdir(parents=True)
                path.write_bytes(b'original document')
        host.transport=Transport()
        host.desktop.submit=AsyncMock(return_value='accepted')
        message={'message_id':4,'chat':{'id':7,'type':'private'},'from':{'id':7},
                 'document':{'file_id':'file','file_name':'minutes.docx'},'caption':'please summarize'}
        assert await host.dispatch('i',{'channel':'telegram:12','update':{'update_id':1,'message':message}})
        await host.put('selection',peer,b)
        host.desktop.submit.assert_not_awaited()
        downloaded.set()
        while host.work:
            await asyncio.gather(*list(host.work))
        args=host.desktop.submit.call_args.args
        assert args[1]==a and args[2].startswith('please summarize\n\n[消息来源]')
        assert '用户 ID：7' in args[2] and '接收聊天 ID：7' in args[2]
        assert args[3][0]['reference']['fileName']=='minutes.docx'
        assert await host.get('selection',peer)==b
    asyncio.run(run())


def test_failed_download_does_not_submit_incomplete_task(host):
    async def run():
        peer='peer'; target={'project_id':'p','session_id':'a'}
        await host.put('peers',peer,{'allowed':True})
        host.desktop.submit=AsyncMock()
        failure=asyncio.create_task(asyncio.sleep(0,result=False))
        await host.submit(peer,target,'summarize both',[failure])
        host.desktop.submit.assert_not_awaited()
        assert any('部分文件' in ''.join(o['parts']) for _,o in await host.records('outbox'))
    asyncio.run(run())


def test_retry_delivery_never_resubmits_to_model(host, monkeypatch):
    async def run():
        peer='telegram:12:7:7'
        await host.put('peers',peer,{'allowed':True,'bot_id':12,'chat_id':7})
        host.desktop.submit=AsyncMock()
        host.transport.call=AsyncMock(side_effect=[TelegramError('temporary',1),{'message_id':88}])
        await host.reply(peer,'final',{'project_id':'p','session_id':'a'},rows=[],delivery_key='result')
        task=asyncio.create_task(host.delivery_loop())
        try:
            for _ in range(100):
                records=await host.records('outbox')
                if records and records[0][1]['attempts']:
                    item=records[0][1]; item['next_attempt']=0
                    await host.put('outbox','result',item); host.outgoing.set()
                if await host.get('delivered','result'):
                    break
                await asyncio.sleep(.02)
            assert await host.get('delivered','result')
            assert (await host.get('messages',peer+':88'))['target']['session_id']=='a'
            host.desktop.submit.assert_not_awaited()
        finally:
            task.cancel(); await asyncio.gather(task,return_exceptions=True)
    asyncio.run(run())


def test_transport_error_never_exposes_token(monkeypatch):
    import httpx
    from contextlib import asynccontextmanager
    from app.services.mobile import telegram_transport as transport_module
    async def run():
        token='123456:private-secret'
        class Client:
            async def post(self,url,**kwargs):
                raise httpx.ConnectError(url)
        @asynccontextmanager
        async def lease(_): yield Client()
        monkeypatch.setattr(transport_module,'lease_http_client',lease)
        monkeypatch.setattr(transport_module,'get_shared_http_client',lambda:None)
        with pytest.raises(TelegramError) as caught:
            await transport_module.TelegramTransport(token).call('getMe')
        assert token not in str(caught.value)
    asyncio.run(run())
