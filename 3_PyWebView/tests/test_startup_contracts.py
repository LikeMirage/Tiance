from contextlib import closing
from dataclasses import replace
import subprocess
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app import config as shell_config
from app import backend_process as shell_backend_process
from app import backend_runtime_record
from app.backend_process import BackendProcessManager, _build_backend_environment
from app.backend_watchdog import ShellLease
from app.backend_runtime_record import (
    ManagedBackendRecord,
    ProcessIdentity,
    cleanup_orphaned_managed_backend,
)
from app.config import ShellSettings
from app.startup_page import render_startup_page
from app.startup_preferences import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    DESKTOP_WINDOW_SIZE_PREFERENCES_KEY,
    MAX_WINDOW_HEIGHT,
    MAX_WINDOW_WIDTH,
    load_network_startup_preferences,
    load_desktop_window_size_preferences,
)
from app.startup_theme import DEFAULT_STARTUP_THEME, load_startup_theme


class EmbeddedRuntimeContractTests(unittest.TestCase):
    def test_root_runtime_loads_desktop_shell_dependencies(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        embedded_python = project_root / "runtime" / "python" / "py313" / "python.exe"
        if not embedded_python.is_file():
            self.skipTest("嵌入式 Python 不在当前测试环境中")

        completed = subprocess.run(
            [
                str(embedded_python),
                "-c",
                (
                    "import sys; "
                    f"sys.path.insert(0, {str(project_root / '3_PyWebView')!r}); "
                    "import run; "
                    "assert run._is_current_embedded_python(); "
                    "run._activate_desktop_shell_dependencies(); "
                    "import psutil"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)


class ShellConfigPortSelectionTests(unittest.TestCase):
    def test_saved_fixed_port_is_used_when_environment_does_not_override(self) -> None:
        preferences = shell_config.NetworkStartupPreferences(
            backend_port_mode="fixed",
            fixed_backend_port=19009,
        )
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(shell_config, "is_port_open") as port_check,
        ):
            self.assertEqual(
                shell_config._resolve_api_port("127.0.0.1", preferences),
                19009,
            )
            port_check.assert_not_called()

    def test_environment_port_overrides_saved_fixed_port(self) -> None:
        preferences = shell_config.NetworkStartupPreferences(
            backend_port_mode="fixed",
            fixed_backend_port=19009,
        )
        with patch.dict(os.environ, {"TIANCE_API_PORT": "19010"}, clear=True):
            self.assertEqual(
                shell_config._resolve_api_port("127.0.0.1", preferences),
                19010,
            )

    def test_api_port_never_reuses_occupied_port(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "TIANCE_API_PORT_RANGE": "19000-19002",
                },
                clear=True,
            ),
            patch.object(shell_config, "is_port_open") as port_check,
        ):
            port_check.side_effect = lambda _host, port: port in {19000, 19001}

            self.assertEqual(shell_config._resolve_api_port("127.0.0.1"), 19002)

    def test_api_port_uses_first_available_port(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "TIANCE_API_PORT_RANGE": "19000-19002",
                },
                clear=True,
            ),
            patch.object(shell_config, "is_port_open") as port_check,
        ):
            port_check.side_effect = lambda _host, port: port == 19000

            self.assertEqual(shell_config._resolve_api_port("127.0.0.1"), 19001)

    def test_explicit_api_port_is_not_auto_rewritten(self) -> None:
        with (
            patch.dict(os.environ, {"TIANCE_API_PORT": "19009"}, clear=True),
            patch.object(shell_config, "is_port_open") as port_check,
        ):
            self.assertEqual(shell_config._resolve_api_port("127.0.0.1"), 19009)
            port_check.assert_not_called()


class BackendProcessOwnershipTests(unittest.TestCase):
    def test_occupied_selected_port_is_never_reused(self) -> None:
        settings = _shell_settings(Path.cwd())
        manager = BackendProcessManager(settings)

        with patch.object(shell_backend_process, "is_port_open", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "became occupied"):
                manager.ensure_running()

    def test_disabled_management_requires_an_existing_backend(self) -> None:
        settings = replace(_shell_settings(Path.cwd()), manage_backend=False)
        manager = BackendProcessManager(settings)

        with patch.object(shell_backend_process, "is_port_open", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "management is disabled"):
                manager.ensure_running()

    def test_exited_managed_backend_is_discarded_before_retry(self) -> None:
        manager = BackendProcessManager(_shell_settings(Path.cwd()))
        manager._process = _ExitedProcess(returncode=17)

        with patch.object(shell_backend_process, "is_port_open", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "became occupied"):
                manager.ensure_running()

        self.assertIsNone(manager._process)

    def test_managed_backend_allows_configured_frontend_dev_origin(self) -> None:
        settings = replace(
            _shell_settings(Path.cwd()),
            dev_url="http://127.0.0.1:18100",
        )
        lease = ShellLease(
            instance_id="instance",
            token="token",
            heartbeat_url="http://127.0.0.1:19000/heartbeat",
        )

        with patch.dict(os.environ, {}, clear=True):
            environment = _build_backend_environment(settings, lease)

        origins = environment["ALLOWED_ORIGINS"].split(",")
        self.assertIn("http://127.0.0.1:18100", origins)
        self.assertIn("http://localhost:18100", origins)


class ManagedBackendCleanupTests(unittest.TestCase):
    def test_verified_orphaned_backend_is_terminated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            record = _managed_backend_record(project_root)
            backend_runtime_record._write_record(
                backend_runtime_record._record_path(project_root),
                record,
            )

            with (
                patch.object(
                    backend_runtime_record,
                    "_query_process_identity",
                    return_value=ProcessIdentity(
                        executable_path=record.executable_path,
                        creation_time=record.creation_time,
                        command_line=(str(project_root / "1_PythonServer" / "run.py"),),
                    ),
                ),
                patch.object(
                    backend_runtime_record,
                    "_probe_instance_id",
                    return_value=record.instance_id,
                ),
                patch.object(
                    backend_runtime_record,
                    "_terminate_process_tree",
                    return_value=True,
                ) as terminate,
            ):
                cleanup_orphaned_managed_backend(project_root)

            terminate.assert_called_once_with(record.pid)
            self.assertFalse(backend_runtime_record._record_path(project_root).exists())

    def test_process_with_different_identity_is_never_terminated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            record = _managed_backend_record(project_root)
            backend_runtime_record._write_record(
                backend_runtime_record._record_path(project_root),
                record,
            )

            with (
                patch.object(
                    backend_runtime_record,
                    "_query_process_identity",
                    return_value=ProcessIdentity(
                        executable_path=record.executable_path,
                        creation_time=record.creation_time + 1,
                        command_line=(str(project_root / "1_PythonServer" / "run.py"),),
                    ),
                ),
                patch.object(backend_runtime_record, "_terminate_process_tree") as terminate,
            ):
                cleanup_orphaned_managed_backend(project_root)

            terminate.assert_not_called()

    def test_process_with_different_instance_id_is_never_terminated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            record = _managed_backend_record(project_root)
            backend_runtime_record._write_record(
                backend_runtime_record._record_path(project_root),
                record,
            )

            with (
                patch.object(
                    backend_runtime_record,
                    "_query_process_identity",
                    return_value=ProcessIdentity(
                        executable_path=record.executable_path,
                        creation_time=record.creation_time,
                        command_line=(str(project_root / "1_PythonServer" / "run.py"),),
                    ),
                ),
                patch.object(
                    backend_runtime_record,
                    "_probe_instance_id",
                    return_value="another-instance",
                ),
                patch.object(backend_runtime_record, "_terminate_process_tree") as terminate,
            ):
                cleanup_orphaned_managed_backend(project_root)

            terminate.assert_not_called()

    def test_unrelated_python_process_is_never_terminated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            record = _managed_backend_record(project_root)
            backend_runtime_record._write_record(
                backend_runtime_record._record_path(project_root),
                record,
            )

            with (
                patch.object(
                    backend_runtime_record,
                    "_query_process_identity",
                    return_value=ProcessIdentity(
                        executable_path=record.executable_path,
                        creation_time=record.creation_time,
                        command_line=(str(project_root / "another-script.py"),),
                    ),
                ),
                patch.object(backend_runtime_record, "_terminate_process_tree") as terminate,
            ):
                cleanup_orphaned_managed_backend(project_root)

            terminate.assert_not_called()


class StartupPreferencesContractTests(unittest.TestCase):
    def test_network_startup_preferences_read_saved_fixed_port(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            database_file = project_root / "Data" / "db" / "tiance.db"
            database_file.parent.mkdir(parents=True)
            with closing(sqlite3.connect(database_file)) as connection:
                connection.execute(
                    """
                    CREATE TABLE network_settings (
                        settings_id TEXT PRIMARY KEY,
                        version INTEGER NOT NULL,
                        settings_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO network_settings (settings_id, version, settings_json)
                    VALUES ('default', 1, ?)
                    """,
                    (
                        json.dumps(
                            {
                                "backend_port_mode": "fixed",
                                "fixed_backend_port": 19021,
                            }
                        ),
                    ),
                )
                connection.commit()

            preferences = load_network_startup_preferences(project_root)

            self.assertEqual(preferences.backend_port_mode, "fixed")
            self.assertEqual(preferences.fixed_backend_port, 19021)

    def test_window_snapshot_is_read_with_supported_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            database_file = project_root / "Data" / "db" / "tiance.db"
            _write_window_snapshot(
                database_file,
                {
                    "version": 1,
                    "width": 1600,
                    "height": 1000,
                    "maximized": True,
                },
            )

            preferences = load_desktop_window_size_preferences(project_root)

            self.assertEqual(preferences.width, 1600)
            self.assertEqual(preferences.height, 1000)
            self.assertTrue(preferences.maximized)

    def test_window_snapshot_rejects_unknown_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            database_file = project_root / "Data" / "db" / "tiance.db"
            _write_window_snapshot(
                database_file,
                {
                    "version": 2,
                    "width": 1600,
                    "height": 1000,
                    "maximized": True,
                },
            )

            preferences = load_desktop_window_size_preferences(project_root)

            self.assertEqual(preferences.width, DEFAULT_WINDOW_WIDTH)
            self.assertEqual(preferences.height, DEFAULT_WINDOW_HEIGHT)
            self.assertFalse(preferences.maximized)

    def test_window_snapshot_uses_backend_dimension_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            database_file = project_root / "Data" / "db" / "tiance.db"
            _write_window_snapshot(
                database_file,
                {
                    "version": 1,
                    "width": 99999,
                    "height": 99999,
                    "maximized": False,
                },
            )

            preferences = load_desktop_window_size_preferences(project_root)

            self.assertEqual(preferences.width, MAX_WINDOW_WIDTH)
            self.assertEqual(preferences.height, MAX_WINDOW_HEIGHT)


class StartupThemeContractTests(unittest.TestCase):
    def test_theme_snapshot_is_read_with_supported_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            themes_root = Path(temporary_directory)
            _write_theme_snapshot(themes_root, settings_version=1, manifest_version=2)

            with patch.dict(os.environ, {"THEMES_DATA_DIR": str(themes_root)}):
                theme = load_startup_theme()

            self.assertEqual(theme.mode, "light")
            self.assertEqual(theme.accent, "#123456")

    def test_theme_snapshot_rejects_unknown_settings_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            themes_root = Path(temporary_directory)
            _write_theme_snapshot(themes_root, settings_version=2, manifest_version=2)

            with patch.dict(os.environ, {"THEMES_DATA_DIR": str(themes_root)}):
                theme = load_startup_theme()

            self.assertEqual(theme, DEFAULT_STARTUP_THEME)

    def test_theme_snapshot_rejects_unknown_manifest_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            themes_root = Path(temporary_directory)
            _write_theme_snapshot(themes_root, settings_version=1, manifest_version=1)

            with patch.dict(os.environ, {"THEMES_DATA_DIR": str(themes_root)}):
                theme = load_startup_theme()

            self.assertEqual(theme, DEFAULT_STARTUP_THEME)


class StartupPageTests(unittest.TestCase):
    def test_static_assets_render_to_inline_startup_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            frontend_dist = Path(temporary_directory)
            (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
            settings = _shell_settings(frontend_dist)

            page = render_startup_page(settings)

            self.assertIn("http://127.0.0.1:18100", page)
            self.assertIn("http://127.0.0.1:18000/app/", page)
            self.assertIn('new URL("/@vite/client", startup.devUrl)', page)
            self.assertIn("haveSameOrigin(startup.devUrl, startup.apiUrl)", page)
            self.assertLess(
                page.index("canReachDevFrontend()"),
                page.index("canReach(startup.appUrl"),
            )
            self.assertNotIn("__TIANCE_", page)
            self.assertNotIn("backendStartEnsured", page)
            self.assertIn("const backendResult = await ensureBackendRunning();", page)
            self.assertIn("后端服务启动失败：${backendError}", page)
            self.assertIn('"textMuted"', page)
            self.assertIn('class="wordmark__text" data-text="Tiance"', page)
            self.assertIn("@keyframes wordmark-sweep", page)
            self.assertNotIn('class="ring"', page)


class _ExitedProcess:
    def __init__(self, *, returncode: int) -> None:
        self.returncode = returncode
        self.pid = 4321

    def poll(self) -> int:
        return self.returncode


def _managed_backend_record(project_root: Path) -> ManagedBackendRecord:
    return ManagedBackendRecord(
        schema_version=1,
        project_root=str(project_root.resolve()),
        pid=4321,
        executable_path=str(project_root / "python.exe"),
        creation_time=123456789,
        instance_id="managed-instance",
        api_url="http://127.0.0.1:18000",
    )


def _write_window_snapshot(database_file: Path, payload: dict[str, object]) -> None:
    database_file.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database_file)) as connection:
        connection.execute("CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO app_metadata (key, value) VALUES (?, ?)",
            (DESKTOP_WINDOW_SIZE_PREFERENCES_KEY, json.dumps(payload)),
        )
        connection.commit()


def _write_theme_snapshot(
    themes_root: Path,
    *,
    settings_version: int,
    manifest_version: int,
) -> None:
    theme_id = "test-theme"
    themes_root.mkdir(parents=True, exist_ok=True)
    (themes_root / "theme-settings.json").write_text(
        json.dumps({"schemaVersion": settings_version, "activeThemeId": theme_id}),
        encoding="utf-8",
    )
    theme_directory = themes_root / theme_id
    theme_directory.mkdir()
    (theme_directory / "theme.json").write_text(
        json.dumps(
            {
                "schemaVersion": manifest_version,
                "id": theme_id,
                "name": "Test",
                "mode": "light",
                "tokens": {
                    "color": {
                        "surface": {"base": "#ffffff", "titlebar": "#eeeeee"},
                        "text": {"primary": "#111111", "muted": "#666666"},
                        "border": {"separator": "#dddddd"},
                        "accent": {"base": "#123456", "rgb": "18, 52, 86"},
                        "state": {"dangerText": "#ff0000", "dangerBorder": "#aa0000"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _shell_settings(frontend_dist: Path) -> ShellSettings:
    return ShellSettings(
        title="Tiance",
        debug=True,
        api_host="127.0.0.1",
        api_port=18000,
        api_url="http://127.0.0.1:18000",
        manage_backend=True,
        dev_url="http://127.0.0.1:18100",
        app_url="http://127.0.0.1:18000/app/",
        frontend_dist_path=str(frontend_dist),
        allow_remote_shell_api=False,
        frameless=True,
        easy_drag=False,
        shadow=False,
        width=1440,
        height=900,
        start_maximized=False,
        min_width=1080,
        min_height=720,
        background_color="#1e1e1e",
        webview2_runtime_mode="auto",
        webview2_runtime_path=None,
        webview_storage_path=str(frontend_dist / "profile"),
        app_icon_path=None,
    )


if __name__ == "__main__":
    unittest.main()
