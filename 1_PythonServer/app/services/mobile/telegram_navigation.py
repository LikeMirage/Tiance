"""Telegram content entries and colored operation buttons."""
from .scoped_navigation import ScopedNavigation


class TelegramNavigation(ScopedNavigation):
    async def button(self, peer, text, action, **args):
        button = await super().button(peer, text, action, **args)
        return dict(button, style='primary')

    async def entry_button(self, peer, text, action, **args):
        # Content entries keep the client's default background; controls use blue.
        return await super().button(peer, text[:60], action, **args)
