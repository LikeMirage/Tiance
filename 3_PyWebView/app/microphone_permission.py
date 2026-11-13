"""Present trusted WebView2 microphone requests in the recording composer."""

import json
import logging
import sys
import uuid
from threading import Thread
from urllib.parse import urlsplit

from app.process_security import is_desktop_auth_document


logger = logging.getLogger(__name__)


def _state(allowed):
    from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState

    return CoreWebView2PermissionState.Allow if allowed else CoreWebView2PermissionState.Deny


class MicrophonePermission:
    def __init__(self, window, settings, on_ui_thread):
        self.window = window
        self.settings = settings
        self.on_ui_thread = on_ui_thread
        self.core = None
        self.pending = {}

    def install(self, *_args):
        if sys.platform != "win32":
            return

        def bind():
            control = getattr(getattr(self.window, "native", None), "webview", None)
            core = getattr(control, "CoreWebView2", None)
            if core is None or core == self.core:
                return
            self._cancel_pending()
            self.core = core
            core.PermissionRequested += self._requested
            core.NavigationStarting += self._cancel_pending
            core.ProcessFailed += self._cancel_pending

        try:
            self.on_ui_thread(bind)
        except Exception:
            logger.exception("Unable to install the inline microphone permission handler")

    def _trusted_request(self, uri):
        current = str(self.core.Source or "")
        if not current or current == "about:blank" or not is_desktop_auth_document(current, self.settings):
            return False
        page, request = urlsplit(current), urlsplit(uri)
        return (page.scheme, page.netloc) == (request.scheme, request.netloc)

    def _requested(self, _sender, args):
        if str(args.PermissionKind) != "Microphone" or not self._trusted_request(str(args.Uri)):
            return  # Other origins and permission kinds keep the browser's own UI.
        args.SavesInProfile = False
        args.State = _state(False)
        request_id = uuid.uuid4().hex
        self.pending[request_id] = (args, args.GetDeferral())
        # evaluate_js waits for the renderer; never block the WebView2 UI thread.
        Thread(target=self._show, args=(request_id,), daemon=True).start()

    def _show(self, request_id):
        try:
            shown = self.window.evaluate_js(
                f"window.__tianceMicrophonePermissionRequest?.({json.dumps(request_id)}) === true"
            )
            if shown is True:
                return
        except Exception:
            logger.exception("Unable to present microphone permission in the composer")
        self.respond(request_id, False)

    def respond(self, request_id, allowed):
        def complete():
            pending = self.pending.pop(request_id, None)
            if pending is None:
                return False
            args, deferral = pending
            try:
                allow = allowed is True and self._trusted_request(str(args.Uri))
                args.State = _state(allow)
                # Remember an explicit grant using WebView2's permission store.
                # Cancellation is per request and must allow a later retry.
                args.SavesInProfile = allow
                return True
            finally:
                deferral.Complete()

        return self.on_ui_thread(complete)

    def _cancel_pending(self, *_args):
        # Called by native events on the UI thread, including navigation/reload.
        pending, self.pending = self.pending, {}
        for args, deferral in pending.values():
            try:
                args.State = _state(False)
                args.SavesInProfile = False
                deferral.Complete()
            except Exception:
                logger.debug("Microphone permission request was already disposed", exc_info=True)
