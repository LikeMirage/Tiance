from __future__ import annotations

import logging
import sys
from threading import Lock
from typing import Any

from app.windows_clipboard import normalize_existing_paths


logger = logging.getLogger("tiance.desktop.file_drag")
_drag_lock = Lock()


def start_file_drag(window: Any, paths: list[str]) -> bool:
    """Offer real files as CF_HDROP, without changing the clipboard or moving sources."""
    if sys.platform != "win32":
        return False
    native = getattr(window, "native", None)
    if native is None or not callable(getattr(native, "DoDragDrop", None)):
        return False
    normalized = normalize_existing_paths(paths)
    if not normalized or not _drag_lock.acquire(blocking=False):
        return False
    try:
        # pywebview dispatches API calls on worker threads; OLE dragging needs the UI STA.
        from System import Action
        from System.Collections.Specialized import StringCollection
        from System.Windows.Forms import Control, DataObject, DragDropEffects, MouseButtons

        started = False

        def run() -> None:
            nonlocal started
            # An async bridge response must not start a new drag after the user lets go.
            if not int(Control.MouseButtons) & int(MouseButtons.Left):
                return
            files = StringCollection()
            for path in normalized:
                files.Add(path)
            data = DataObject()
            data.SetFileDropList(files)
            native.DoDragDrop(data, DragDropEffects.Copy)
            # None is also a normal result (Escape or an application rejecting the drop).
            started = True

        if native.InvokeRequired:
            native.Invoke(Action(run))
        else:
            run()
        return started
    except Exception:
        logger.exception("Unable to start native file drag.")
        return False
    finally:
        _drag_lock.release()
