import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from app.services.mobile.feishu_cards import build_card
from app.services.mobile.feishu_events import normalize_event
from app.services.mobile.feishu_navigation import FeishuNavigation
from app.services.mobile.feishu_transport import FeishuTransport
from app.services.mobile.navigation import MobileNavigation
from app.services.mobile.service import FeishuService
from tests.test_mobile_access import repository, host


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def test_list_entries_keep_full_titles_and_callbacks_separate_from_presentation(host):
    async def run():
        target = {'project_id': 'p', 'session_id': 's'}
        await host.put('selection', 'peer', target)
        nav = FeishuNavigation(host)
        title = '<b>会话原名</b>' + '长标题' * 30
        entry = await nav.entry_button('peer', title, 'select', target=target)
        assert entry['text'] == title
        assert entry['presentation']['current'] is True
        assert entry['presentation']['role'] == 'entry'
        stored = await host.get('callbacks', entry['callback_data'])
        assert stored == {'peer': 'peer', 'action': 'select', 'target': target, '_trail': []}
        card = build_card('主会话（1）', [[entry]], header='项目集 · 项目 A')
        assert any(node.get('content') == title + ' · 当前' for node in walk(card))
        button = next(node for node in walk(card) if node.get('tag') == 'button')
        event = normalize_event({'header': {'event_type': 'card.action.trigger', 'event_id': 'event'},
                                 'event': {'operator': {'open_id': 'user'}, 'context': {'open_chat_id': 'chat'},
                                           'action': {'value': button['value']}}})
        assert event['callback'] == entry['callback_data']
        assert button['text']['content'] == '进入'
        assert button['type'] == 'primary_text'
    asyncio.run(run())


def test_paged_card_separates_content_operations_pagination_and_navigation(host):
    async def run():
        host.put = AsyncMock(wraps=host.put)
        host.reply = AsyncMock()
        nav = FeishuNavigation(host)
        create = await nav.button('peer', '＋ 新建主会话', 'new', target={'project_id': 'p'})
        entries = [(f'会话 {i}', 'select', {'target': {'project_id': 'p', 'session_id': str(i)}})
                   for i in range(18)]
        await nav.paged('peer', '主会话', entries, 'sessions', {'target': {'project_id': 'p'}},
                        page=1, leading_rows=[[create]])
        _, text, _, rows = host.reply.call_args.args
        assert '第 2/3 页' in text
        card = build_card(text, rows)
        elements = card['elements']
        content_rows = [item for item in elements if item.get('tag') == 'column_set'
                        and item['columns'][0]['elements'][0]['tag'] == 'div']
        assert len(content_rows) == 8
        assert all(item['flex_mode'] == 'none' for item in content_rows)
        first_divider = next(i for i, item in enumerate(elements) if item['tag'] == 'hr')
        assert all(elements.index(row) < first_divider for row in content_rows)
        assert [item['elements'][0]['content'] for item in elements if item['tag'] == 'note'] == ['操作', '快捷导航']
        buttons = [item for item in walk(card) if item.get('tag') == 'button']
        assert len(buttons) == 12  # 8 entries, 2 pages, 1 create, 1 parent.
        assert {button['value']['tiance'] for button in buttons} == {b['callback_data'] for row in rows for b in row}
        footer = elements[-1]
        assert len(footer['columns']) == 1
        assert all(column['elements'][0]['type'] == 'text' for column in footer['columns'])
        page_callbacks = [call.args[2] for call in host.put.call_args_list if 'page' in call.args[2]]
        assert {item['page'] for item in page_callbacks} == {0, 2}
        assert all(item['target'] == {'project_id': 'p'} for item in page_callbacks)
    asyncio.run(run())


def test_operations_use_two_columns_and_danger_stays_distinct(host):
    async def run():
        nav = FeishuNavigation(host)
        buttons = [await nav.button('peer', text, action) for text, action in (
            ('新建分类', 'newcategory'), ('关系图', 'map'), ('暂停', 'stop'))]
        card = build_card('操作', [buttons])
        columns = [item for item in card['elements'] if item['tag'] == 'column_set']
        assert [len(item['columns']) for item in columns] == [2, 1]
        assert [item['type'] for item in walk(card) if item.get('tag') == 'button'] == ['primary', 'default', 'danger']
    asyncio.run(run())


def test_empty_card_has_no_empty_toolbar_and_existing_queued_buttons_still_work():
    empty = build_card('暂无内容。', [], header='天策')
    assert [item['tag'] for item in empty['elements']] == ['note', 'div']
    card = build_card('处理中', [[{'text': '暂停', 'callback_data': 'saved-key'}]])
    assert next(item for item in walk(card) if item.get('tag') == 'button')['value'] == {'tiance': 'saved-key'}


def test_other_platform_buttons_keep_their_wire_format_and_truncation(host):
    async def run():
        button = await MobileNavigation(host).entry_button('peer', '字' * 80, 'select', target={'project_id': 'p'})
        assert set(button) == {'text', 'callback_data'}
        assert button['text'] == '字' * 60
    asyncio.run(run())


def test_transport_keeps_context_in_card_and_file_caption():
    async def run():
        transport = FeishuTransport('app', 'secret')
        transport.send = AsyncMock(return_value={'message_id': 'm'})
        transport.send_file = AsyncMock(return_value={'message_id': 'f'})
        await transport.deliver({'chat_id': 'chat'}, '主会话（0）\n暂无内容。', [],
                                header='项目集 · 项目 A', delivery_id='d')
        args = transport.send.call_args.args
        assert args[:2] == ('chat', 'interactive')
        assert args[2]['elements'][0] == {'tag': 'note', 'elements': [{'tag': 'plain_text', 'content': '项目集 · 项目 A'}]}
        await transport.deliver({'chat_id': 'chat'}, '关系图', [], document='diagram.png',
                                header='项目集', delivery_id='d-file')
        transport.send_file.assert_awaited_once_with('chat', 'diagram.png', '项目集\n\n关系图', 'd-file')
    asyncio.run(run())


def test_feishu_delivery_serializes_navigation_card_from_outbox(repository):
    async def run():
        host = FeishuService(repository)
        host.config = {'bot': {'id': 'app'}, 'enabled': True, 'allowed_collections': ['project', 'tool', 'knowledge', 'experience', 'role', 'provider', 'theme']}
        peer = 'feishu:app:user:chat'
        await host.put('peers', peer, {'allowed': True, 'bot_id': 'app', 'chat_id': 'chat'})
        transport = FeishuTransport('app', 'secret')
        transport.request = AsyncMock(return_value={'data': {'message_id': 'message'}})
        host.transport = transport
        await host.navigation.action(peer, 'collections')
        key, _ = (await host.records('outbox'))[0]
        task = asyncio.create_task(host.delivery_loop())
        try:
            async def delivered():
                while not await host.get('delivered', key):
                    await asyncio.sleep(.01)
            await asyncio.wait_for(delivered(), timeout=3)
            payload = transport.request.call_args.kwargs['json']
            assert payload['receive_id'] == 'chat'
            assert payload['msg_type'] == 'interactive'
            card = json.loads(payload['content'])
            assert card['elements'][0]['tag'] == 'note'
            assert card['elements'][1]['text']['content'] == '选择集（7）'
            buttons = [item for item in walk(card) if item.get('tag') == 'button']
            assert sum(button['text']['content'] == '打开' for button in buttons) == 7
            for button in buttons:
                callback = await host.get('callbacks', button['value']['tiance'])
                assert callback['peer'] == peer
            assert await host.records('outbox') == []
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
