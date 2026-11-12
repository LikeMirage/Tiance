"""Persistent, peer-scoped numeric navigation over the shared catalog actions."""
import asyncio
from contextvars import ContextVar

from app.core.errors import BadRequestError
from .scoped_navigation import ScopedNavigation

_rendering = ContextVar('wechat_menu_rendering', default=None)
CREATE = {'new', 'newcategory', 'newproject'}


class WeChatNavigation(ScopedNavigation):
    async def button(self, peer, text, action, **args):
        button = await super().button(peer, text, action, **args)
        button['presentation'] = {'role': 'operation'}
        return button

    async def entry_button(self, peer, text, action, **args):
        return await super().button(peer, text[:60], action, **args)

    async def state(self, peer):
        return await self.menus.get(peer)

    async def consume(self, peer, text, event):
        text = text.strip()
        state = await self.state(peer)
        if (state['stack'] or state['mode'] == 'conversation') and state.get('scope') != self.host.access_scope.collections():
            await self.host.put('menus', peer, {'mode': 'menu', 'stack': [], 'options': []})
            await self.action(peer, 'collections')
            return True
        if text == '0' and not event.get('media'):
            await self.action(peer, 'back')
            return True
        if text == 'menu' and not event.get('media'):
            await self.action(peer, 'collections')
            return True
        if text.startswith('/') and not event.get('media'):
            command, _, title = text.partition(' ')
            command = command[1:]
            if command in {'start', 'menu', 'projects'}:
                await self.action(peer, 'collections')
            elif command == '5':
                await self.action(peer, 'history')
            elif command == 'action':
                await self.choose(peer, title.strip())
            elif command == 'new':
                page = state['stack'][-1] if state['stack'] else {}
                action = {'categories': 'newcategory', 'projects': 'newproject', 'sessions': 'new'}.get(page.get('action'))
                if state['mode'] == 'conversation' or not action or page.get('parent'):
                    await self.report_error(peer, '当前层级不支持新建。发送 0 返回列表后再新建。')
                else:
                    args = {k: v for k, v in page.items() if k not in {'action', 'page', 'parent', 'group'}}
                    await self.action(peer, action, **args, title=title.strip() or None)
            elif command in {'sessions', 'model', 'history', 'files', 'clear', 'stop', 'status', 'map', 'groups', 'actions'}:
                await self.action(peer, command)
            else:
                await self.report_error(peer, '发送 0 返回上一级。menu 选择集；会话内发送 5 查看前5轮、00 暂停；/sessions 选择会话；/model 切换模型。')
            return True
        if state.get('pending'):
            if not text or event.get('media'):
                await self.report_error(peer, '请发送名称文字，或发送 0 取消。')
                return True
            request = state.pop('pending')
            await self.host.put('menus', peer, state)
            await self.action(peer, **request, title=text)
            return True
        if state['mode'] == 'conversation':
            action = {'5': 'history', '00': 'stop'}.get(text)
            if action and not event.get('media'):
                await self.action(peer, action)
                return True
            return False  # "2" and "000" are ordinary user messages here.
        if not event.get('media') and text.isascii() and text.isdecimal() and 1 <= int(text) <= len(state.get('options', [])):
            await self.choose(peer, state['options'][int(text) - 1])
        else:
            if text.isascii() and text.isdecimal() and not state.get('options'):
                await self.report_error(peer, '原菜单尚未建立或已失效，请按下方重新加载的菜单选择。本条数字未发送给 AI。')
            else:
                await self.report_error(peer, '当前在选择菜单，尚未发送给 AI。请发送菜单编号，或发送 0 返回。')
            frame = state['stack'][-1] if state['stack'] else {'action': 'collections'}
            await self.action(peer, **frame)
        return True

    async def choose(self, peer, key):
        data = await self.host.get('callbacks', key)
        if not data or data.get('peer') != peer:
            raise BadRequestError('该选择已失效，请发送 menu 重新选择。')
        if data['action'] == 'map' and not data.get('kind'):
            raise BadRequestError('此关系图选项已过期，请发送 menu 重新选择。')
        await self.action(peer, **{k: v for k, v in data.items() if k != 'peer'})

    async def perform_action(self, peer, action, **args):
        state = await self.state(peer)
        if action in CREATE:
            if state['mode'] == 'conversation':
                await self.report_error(peer, '请先发送 0 返回列表，再新建。')
                return
            # Conversations already have a default title in the shared creation
            # flow. Only projects and categories require a separate name input.
            if action != 'new' and not args.get('title'):
                state['pending'] = dict(action=action, **args)
                await self.host.put('menus', peer, state)
                await self.report_error(peer, '请发送新名称。发送 0 取消。')
                return
        marker = _rendering.set(asyncio.current_task())
        try:
            await super().perform_action(peer, action, **args)
        finally:
            _rendering.reset(marker)

    async def controls(self, peer, target, user_message_id=None):
        return []  # Async replies cannot replace the active menu or its numbering.

    def page_text(self, title, count, page, pages, action):
        # The reply header already names the project and current conversation.
        heading = '' if action == 'sessions' and title == '主会话' else title
        return '\n'.join(part for part in [heading, '暂无内容。' if not count else ''] if part)

    async def prepare_reply(self, peer, text, rows):
        state = await self.state(peer)
        if _rendering.get() is asyncio.current_task() and state['mode'] == 'menu' and rows:
            flat = [button for row in rows for button in row]
            # Number the displayed order, so moving controls cannot change the
            # meaning of an item between the text and its persisted callback.
            flat.sort(key=lambda button: button.get('presentation', {}).get('role') == 'operation')
            state['options'] = [button['callback_data'] for button in flat]
            await self.host.put('menus', peer, state)
            items = '\n'.join(f"{i}. {'【操作】' if button.get('presentation', {}).get('role') == 'operation' else ''}{button['text']}" for i, button in enumerate(flat, 1))
            text = '\n\n'.join(part for part in [text, items] if part)
        elif rows:
            # Permission requests are independent of navigation. Explicit action
            # codes remain peer-scoped and cannot overwrite the numeric menu.
            for row in rows:
                for button in row:
                    data = await self.host.get('callbacks', button['callback_data'], {})
                    if data.get('action') == 'permission':
                        text += f"\n{button['text']}：/action {button['callback_data']}"
        footer = '0 返回上一级 · menu 选择集'
        if state['mode'] == 'conversation':
            footer = '5 查看前5轮对话 · 00 暂停 · /actions 会话操作 · ' + footer
        return text + '\n\n' + footer, []

    async def message_target(self, peer, message):
        # WeChat numeric menus do not support switching by quoted messages.
        return await super().message_target(peer, {})
