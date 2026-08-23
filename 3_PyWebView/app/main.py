from app.api import ShellApi
from app.backend_process import BackendProcessManager
from app.backend_runtime_record import cleanup_orphaned_managed_backend
from app.config import PROJECT_ROOT, load_settings
from app.installation_lock import acquire_installation_lock
from app.native_file_drop import install_native_file_drop_bridge
from app.runtime import resolve_launch_target
from app.startup_timing import (
    configure_pywebview_timing_logger,
    install_window_event_timing,
    mark,
    set_timing_enabled,
    timed_stage,
)
from app.window import build_entrypoint, build_window_options


def main() -> None:
    mark("main: entered")
    release_installation_lock = acquire_installation_lock(PROJECT_ROOT)
    backend_manager: BackendProcessManager | None = None
    shell_api: ShellApi | None = None

    try:
        with timed_stage("cleanup orphaned managed backend"):
            cleanup_orphaned_managed_backend(PROJECT_ROOT)

        with timed_stage("import pywebview"):
            try:
                import webview
            except ImportError as exc:  # pragma: no cover - runtime guidance path
                raise SystemExit(
                    "pywebview is not installed. Run `pip install -e .` in 3_PyWebView."
                ) from exc

        with timed_stage("load shell settings"):
            settings = load_settings()
        set_timing_enabled(True)
        configure_pywebview_timing_logger()
        mark(
            "shell settings loaded",
            debug=settings.debug,
            frameless=settings.frameless,
            webview2_runtime_mode=settings.webview2_runtime_mode,
        )

        backend_manager = BackendProcessManager(settings)

        with timed_stage("resolve launch target"):
            target = resolve_launch_target(settings)
        mark(
            "launch target resolved",
            kind="url" if target.url else "html",
            shell_api_allowed=target.shell_api_allowed,
            url=target.url or "<inline-html>",
        )

        with timed_stage("create shell api"):
            shell_api = ShellApi(settings, backend_manager)

        with timed_stage("configure WebView runtime"):
            _configure_webview_runtime(webview, settings)
            webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False

        with timed_stage("build window options"):
            window_options = build_window_options(settings)
            entrypoint = build_entrypoint(target)
            create_window_options = {**window_options, **entrypoint}
            if target.shell_api_allowed:
                create_window_options["js_api"] = shell_api
            else:
                create_window_options["hidden"] = False

        with timed_stage("create pywebview window"):
            window = webview.create_window(**create_window_options)

        backend_manager.set_backend_unavailable_callback(
            shell_api.close_after_backend_loss
        )

        if target.shell_api_allowed:
            with timed_stage("bind shell api"):
                shell_api.bind_window(window)
                install_native_file_drop_bridge(window)

        install_window_event_timing(window)

        with timed_stage("backend process: early ensure"):
            backend_manager.ensure_running()

        mark(
            "pywebview.start: entering",
            debug=settings.debug,
            storage_path=settings.webview_storage_path,
            icon=settings.app_icon_path or "<none>",
        )
        webview.start(
            debug=settings.debug,
            private_mode=False,
            storage_path=settings.webview_storage_path,
            icon=settings.app_icon_path,
        )
        mark("pywebview.start: returned")
    finally:
        if shell_api is not None:
            shell_api.dispose()
        if backend_manager is not None:
            backend_manager.stop()
        release_installation_lock()


def _configure_webview_runtime(webview_module, settings) -> None:
    runtime_path = settings.webview2_runtime_path
    if not runtime_path:
        mark("WebView2 runtime: system default", mode=settings.webview2_runtime_mode)
        return

    if "WEBVIEW2_RUNTIME_PATH" not in webview_module.settings:
        raise SystemExit(
            "A fixed WebView2 runtime was configured, but the installed pywebview "
            "does not support WEBVIEW2_RUNTIME_PATH. Upgrade pywebview to >= 6.1."
        )

    webview_module.settings["WEBVIEW2_RUNTIME_PATH"] = runtime_path
    mark(
        "WebView2 runtime: fixed runtime configured",
        mode=settings.webview2_runtime_mode,
        path=runtime_path,
    )

if __name__ == "__main__":
    main()
