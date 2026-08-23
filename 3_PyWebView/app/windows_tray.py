from __future__ import annotations

import locale
import sys
from pathlib import Path
from typing import Any, Callable


class WindowsTrayIcon:
    def __init__(
        self,
        *,
        icon_path: str | None,
        on_request_exit: Callable[[], None],
        on_show_window: Callable[[], None],
    ) -> None:
        self._icon_path = icon_path
        self._on_request_exit = on_request_exit
        self._on_show_window = on_show_window
        self._notify_icon: Any | None = None
        self._context_menu: Any | None = None
        self._owned_icon: Any | None = None
        self._show_item: Any | None = None
        self._exit_item: Any | None = None

    @property
    def installed(self) -> bool:
        return self._notify_icon is not None

    def install(self) -> bool:
        if self.installed:
            return True
        if sys.platform != "win32":
            return False

        try:
            import clr

            clr.AddReference("System.Drawing")
            clr.AddReference("System.Windows.Forms")
            from System.Drawing import Icon
            from System.Windows.Forms import (
                ContextMenuStrip,
                NotifyIcon,
                ToolStripMenuItem,
            )

            show_label, exit_label = _tray_labels()
            notify_icon = NotifyIcon()
            context_menu = ContextMenuStrip()
            show_item = ToolStripMenuItem(show_label)
            exit_item = ToolStripMenuItem(exit_label)

            show_item.Click += self._handle_show_click
            exit_item.Click += self._handle_exit_click
            notify_icon.MouseClick += self._handle_mouse_click
            notify_icon.DoubleClick += self._handle_show_click
            context_menu.Items.Add(show_item)
            context_menu.Items.Add(exit_item)
            notify_icon.ContextMenuStrip = context_menu
            notify_icon.Text = "天策"

            icon_file = Path(self._icon_path).resolve() if self._icon_path else None
            if icon_file is not None and icon_file.is_file():
                self._owned_icon = Icon(str(icon_file))
                notify_icon.Icon = self._owned_icon

            notify_icon.Visible = True
            self._notify_icon = notify_icon
            self._context_menu = context_menu
            self._show_item = show_item
            self._exit_item = exit_item
            return True
        except Exception:
            self.dispose()
            return False

    def dispose(self) -> None:
        notify_icon = self._notify_icon
        self._notify_icon = None
        if notify_icon is not None:
            try:
                notify_icon.Visible = False
                notify_icon.Dispose()
            except Exception:
                pass

        context_menu = self._context_menu
        self._context_menu = None
        if context_menu is not None:
            try:
                context_menu.Dispose()
            except Exception:
                pass

        owned_icon = self._owned_icon
        self._owned_icon = None
        if owned_icon is not None:
            try:
                owned_icon.Dispose()
            except Exception:
                pass

        self._show_item = None
        self._exit_item = None

    def _handle_show_click(self, *_: object) -> None:
        self._on_show_window()

    def _handle_mouse_click(self, _sender: object, event: object) -> None:
        if str(getattr(event, "Button", "")) == "Left":
            self._on_show_window()

    def _handle_exit_click(self, *_: object) -> None:
        self._on_request_exit()


def _tray_labels() -> tuple[str, str]:
    language = (locale.getlocale()[0] or "").casefold()
    if language == "zh" or language.startswith("zh_") or language.startswith("zh-"):
        return "显示天策", "退出天策"
    return "Show Tiance", "Exit Tiance"
