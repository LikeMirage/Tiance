"""Live editor pages. All methods and WebView2 callbacks run on the WinForms UI thread."""

from __future__ import annotations

import json
import logging
import ntpath
import os
from contextlib import ExitStack
from math import isfinite
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

from app.editor_web_appearance import appearance_palette, page_appearance_script


_NAVIGATION_ABORT_ERROR = "网页加载失败：ConnectionAborted"


def web_address(value: str) -> bool:
    try:
        url = urlsplit(value)
        return url.scheme in ("http", "https") and bool(url.hostname) and not url.username and not url.password
    except ValueError:
        return False


class EditorBrowser:
    def __init__(self, window, storage: str):
        self.window = window
        self.profile = str(Path(storage).with_name(Path(storage).name + "-editor-pages"))
        self.pages = {}
        self.download_paths: set[Path] = set()
        self.watching_host = False
        self.appearance = ("original",)

    def set_appearance(self, mode, colors):
        appearance = appearance_palette(mode, colors)
        if appearance != self.appearance:
            self.appearance = appearance
            for page in self.pages.values():
                page.set_appearance(appearance)

    def close(self, tab_id):
        page = self.pages.pop(tab_id, None)
        if page is not None:
            page.close()

    def _host_navigating(self, _sender, _args):
        for tab_id in list(self.pages):
            self.close(tab_id)

    def present_cover(self, tab_id, request_id):
        page = self.pages.get(tab_id)
        if not request_id or page is None or page.cover_request != request_id:
            return
        page.view.SendToBack()

    def cover(self, tab_id, request_id, wait_for_paint=False):
        """Capture the foreground page while the host prepares its overlay."""
        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
        from System import Action, Convert
        from System.IO import MemoryStream

        page = self.pages.get(tab_id)
        if page is None or not page.view.Visible:
            return
        page.cover_request = request_id
        # Keep the pixels live during capture, but route focus away from the covered page.
        if page.view.ContainsFocus:
            self.window.native.webview.Focus()
        page.view.Enabled = False
        if page.core is None:
            self.present_cover(tab_id, request_id)
            return
        stream = MemoryStream()
        transparent = page.appearance[0] != "original"
        try:
            image_format = CoreWebView2CapturePreviewImageFormat.Png if transparent else CoreWebView2CapturePreviewImageFormat.Jpeg
            capture = page.core.CapturePreviewAsync(image_format, stream)
        except Exception:
            logging.getLogger(__name__).debug("Could not start editor viewport capture", exc_info=True)
            stream.Dispose()
            self.present_cover(tab_id, request_id)
            return

        def completed():
            try:
                if self.pages.get(tab_id) is not page or page.cover_request != request_id:
                    return
                capture.GetAwaiter().GetResult()
                host = self.window.native.webview.CoreWebView2
                host.PostWebMessageAsJson(json.dumps({
                    "type": "editor-web-preview", "id": tab_id, "request": request_id,
                    ("png" if transparent else "jpeg"): Convert.ToBase64String(stream.ToArray()),
                }))
                if not wait_for_paint:
                    self.present_cover(tab_id, request_id)
            except Exception:
                logging.getLogger(__name__).debug("Editor viewport capture unavailable", exc_info=True)
                self.present_cover(tab_id, request_id)
            finally:
                stream.Dispose()

        capture.GetAwaiter().OnCompleted(Action(completed))

    def layout(self, tab_id, url, edges, workspace_root=None):
        from System.Drawing import Rectangle

        if edges is None:
            if tab_id in self.pages:
                self.pages[tab_id].cover_request = None
                self.pages[tab_id].view.Visible = False
            return
        if len(edges) != 4 or not all(isfinite(n) and 0 <= n <= 1 for n in edges):
            raise ValueError("网页显示区域无效")
        host = self.window.native.webview
        if not self.watching_host:
            host.CoreWebView2.NavigationStarting += self._host_navigating
            self.watching_host = True
        left, top, right, bottom = edges
        x, y = round(host.ClientSize.Width * left), round(host.ClientSize.Height * top)
        width, height = round(host.ClientSize.Width * right) - x, round(host.ClientSize.Height * bottom) - y
        if width <= 0 or height <= 0:
            return self.layout(tab_id, url, None)
        page = self.pages.get(tab_id)
        if page is None:
            def notify(state):
                host.CoreWebView2.PostWebMessageAsJson(json.dumps({"type": "editor-web-state", "id": tab_id, "state": state}))

            page = EditorPage(host.Parent, self.profile, url, notify, workspace_root, self.download_paths, self.appearance)
            self.pages[tab_id] = page
        elif workspace_root:
            page.workspace_root = workspace_root
        for other in self.pages.values():
            if other is not page and other.view.Visible:
                other.cover_request = None
                other.view.Visible = False
        page.view.Bounds = Rectangle(host.Left + x, host.Top + y, width, height)
        if not page.view.Visible or page.cover_request is not None:
            page.cover_request = None
            page.view.Enabled = True
            page.view.Visible = True
            page.view.BringToFront()
            page.publish()

    def command(self, tab_id, action, url):
        page = self.pages.get(tab_id)
        if page is None:
            return None
        if action == "navigate":
            page.navigate(url)
        elif action == "back" and page.core and page.core.CanGoBack:
            page.core.GoBack()
        elif action == "forward" and page.core and page.core.CanGoForward:
            page.core.GoForward()
        elif action == "reload" and page.core and page.url:
            page.core.Reload()
        return page.state()


def workspace_download_path(root: str, suggested: str, in_progress: set[Path]) -> Path:
    workspace = Path(root)
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError("工作区目录不存在")
    workspace = workspace.resolve()
    directory = workspace / "下载"
    if directory.resolve().parent != workspace:
        raise ValueError("下载目录位于工作区之外")
    directory.mkdir(exist_ok=True)
    name = Path(suggested).name.rstrip(" .")
    reserved = ntpath.isreserved(name) if hasattr(ntpath, "isreserved") else PureWindowsPath(name).is_reserved()
    if not name or reserved or any(c in '<>:"/\\|?*' or ord(c) < 32 for c in name):
        raise ValueError("下载文件名无效")
    target = directory / name
    candidate = target
    n = 1
    while candidate in in_progress or os.path.lexists(candidate):
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
        n += 1
    return candidate


class EditorPage:
    def __init__(self, parent, profile, url, notify, workspace_root, download_paths, appearance=("original",)):
        from Microsoft.Web.WebView2.WinForms import CoreWebView2CreationProperties, WebView2
        from System.Windows.Forms import Timer

        self.url = url if web_address(url) else ""
        self.notify = notify
        self.error = ""
        self.loading = False
        self.appearance = appearance
        self.core = None
        self.favicon = ""
        self.favicon_revision = 0
        self.cover_request = None
        self.workspace_root = workspace_root
        self.download_paths = download_paths
        self.navigation_id = None
        self.navigation_urls = set()
        self.navigation_download = False
        self.abort_timer = Timer()
        self.abort_timer.Interval = 500
        self.abort_timer.Tick += self._report_abort
        self.view = WebView2()
        props = CoreWebView2CreationProperties()
        props.UserDataFolder = profile
        self.view.CreationProperties = props
        self.view.Visible = False
        self.view.CoreWebView2InitializationCompleted += self._initialized
        try:
            parent.Controls.Add(self.view)
            self.view.EnsureCoreWebView2Async(None)
        except Exception:
            self.close()
            raise

    def _initialized(self, _sender, event):
        if self.view.IsDisposed:
            return
        if not event.IsSuccess:
            self.error = "网页组件启动失败：" + str(event.InitializationException)
            self.publish()
            return
        core = self.view.CoreWebView2
        core.Settings.AreHostObjectsAllowed = False
        core.Settings.IsWebMessageEnabled = False
        core.NavigationStarting += self._starting
        core.NavigationCompleted += self._completed
        core.DownloadStarting += self._download_starting
        core.HistoryChanged += self.publish
        core.SourceChanged += self._source_changed
        core.DOMContentLoaded += self._apply_page_styles
        core.FaviconChanged += self._favicon_changed
        core.DocumentTitleChanged += self.publish
        core.NewWindowRequested += self._popup
        core.LaunchingExternalUriScheme += self._external_scheme
        self.core = core
        self.set_appearance(self.appearance)
        if self.url:
            core.Navigate(self.url)

    def set_appearance(self, appearance):
        from Microsoft.Web.WebView2.Core import CoreWebView2PreferredColorScheme as Scheme
        from System.Drawing import Color

        self.appearance = appearance
        self.view.DefaultBackgroundColor = Color.White if appearance[0] == "original" else Color.Transparent
        if self.core:
            scheme = {"dark": Scheme.Dark, "light": Scheme.Light, "original": Scheme.Auto}[appearance[0]]
            if self.core.Profile.PreferredColorScheme != scheme:
                self.core.Profile.PreferredColorScheme = scheme
            self._apply_page_styles()

    def _apply_page_styles(self, *_args):
        if self.core and not self.view.IsDisposed:
            script = page_appearance_script(str(self.core.Source or ""), self.appearance)
            if script:
                self.core.ExecuteScriptAsync(script)

    def navigate(self, url):
        if not web_address(url):
            raise ValueError("请输入 HTTP 或 HTTPS 网址")
        self.url = url
        self.error = ""
        if self.core:
            self.core.Navigate(url)

    def close(self):
        self.abort_timer.Tick -= self._report_abort
        self.abort_timer.Dispose()
        self.view.Dispose()

    def _source_changed(self, _sender, event):
        if event.IsNewDocument:
            self.favicon_revision += 1
            self.favicon = ""
        else:
            self._apply_page_styles()
        self.publish()

    def _favicon_changed(self, core, _event):
        from Microsoft.Web.WebView2.Core import CoreWebView2FaviconImageFormat
        from System import Action, Convert
        from System.Drawing import Bitmap, Image
        from System.Drawing.Imaging import ImageFormat
        from System.IO import MemoryStream

        self.favicon_revision += 1
        revision = self.favicon_revision
        if not core.FaviconUri:
            self.favicon = ""
            self.publish()
            return
        try:
            task = core.GetFaviconAsync(CoreWebView2FaviconImageFormat.Png)
        except Exception:
            self.favicon = ""
            self.publish()
            logging.getLogger(__name__).debug("Could not start editor favicon request", exc_info=True)
            return

        def completed():
            try:
                with ExitStack() as resources:
                    stream = task.GetAwaiter().GetResult()
                    if stream is not None:
                        resources.callback(stream.Dispose)
                    if self.view.IsDisposed or self.favicon_revision != revision:
                        return
                    # Store only a tab-sized PNG alongside the other tab metadata.
                    self.favicon = ""
                    if stream is not None:
                        # WebView2's COM stream supports reads only at buffer offset zero.
                        # GDI+ may read into nonzero offsets while decoding the PNG.
                        png = MemoryStream()
                        resources.callback(png.Dispose)
                        stream.CopyTo(png)
                        png.Position = 0
                        image = Image.FromStream(png)
                        resources.callback(image.Dispose)
                        scale = min(1, 32 / max(image.Width, image.Height))
                        icon = Bitmap(image, max(1, round(image.Width * scale)), max(1, round(image.Height * scale)))
                        resources.callback(icon.Dispose)
                        output = MemoryStream()
                        resources.callback(output.Dispose)
                        icon.Save(output, ImageFormat.Png)
                        self.favicon = "data:image/png;base64," + Convert.ToBase64String(output.ToArray())
            except Exception:
                if self.favicon_revision == revision:
                    self.favicon = ""
                logging.getLogger(__name__).debug("Could not read editor favicon", exc_info=True)
            if self.favicon_revision == revision:
                self.publish()

        task.GetAwaiter().OnCompleted(Action(completed))

    def _report_abort(self, _sender, _event):
        self.abort_timer.Stop()
        self.error = _NAVIGATION_ABORT_ERROR
        self.publish()

    def _starting(self, _sender, event):
        if not web_address(str(event.Uri)):
            event.Cancel = True
            return
        if event.NavigationId != self.navigation_id:
            self.abort_timer.Stop()
            self.navigation_id = event.NavigationId
            self.navigation_urls.clear()
            self.navigation_download = False
        self.navigation_urls.add(str(event.Uri).partition("#")[0])
        self.loading = True
        self.error = ""
        self.publish()

    def _completed(self, _sender, event):
        if event.NavigationId != self.navigation_id:
            return
        self.loading = False
        status = str(event.WebErrorStatus)
        if not event.IsSuccess and status == "ConnectionAborted":
            # WebView2 can complete a redirected navigation just before it reports
            # DownloadStarting. Give that event time to claim this specific URI.
            if not self.navigation_download:
                self.abort_timer.Start()
        elif not event.IsSuccess and status != "OperationCanceled":
            self.error = "网页加载失败：" + status
        self.publish()

    def _download_starting(self, _sender, event):
        operation = event.DownloadOperation
        if str(operation.Uri).partition("#")[0] in self.navigation_urls:
            self.navigation_download = True
            self.abort_timer.Stop()
            if self.error == _NAVIGATION_ABORT_ERROR:
                self.error = ""
                self.publish()
        if not self.workspace_root:
            return  # Outside a workspace use the normal WebView2 download destination.
        try:
            target = workspace_download_path(self.workspace_root, str(event.ResultFilePath), self.download_paths)
            event.ResultFilePath = str(target)
        except (OSError, ValueError) as exc:
            event.Cancel = True
            self.error = "无法保存下载到工作区：" + str(exc)
            self.publish()
            return
        self.download_paths.add(target)

        def release(_sender, _args):
            if str(operation.State) != "InProgress":
                self.download_paths.discard(target)
                operation.StateChanged -= release

        operation.StateChanged += release

    def _popup(self, _sender, event):
        event.Handled = True
        if event.IsUserInitiated and web_address(str(event.Uri)):
            self.navigate(str(event.Uri))

    def _external_scheme(self, _sender, event):
        event.Cancel = True

    def publish(self, *_args):
        if not self.view.IsDisposed and self.view.Visible:
            self.notify(self.state())

    def state(self):
        core = self.core
        source = str(core.Source or "") if core else ""
        return {
            "url": source if web_address(source) else self.url,
            "title": str(core.DocumentTitle or "") if core and web_address(source) else "",
            "favicon": self.favicon,
            "back": bool(core and core.CanGoBack),
            "forward": bool(core and core.CanGoForward),
            "loading": self.loading,
            "error": self.error,
        }
