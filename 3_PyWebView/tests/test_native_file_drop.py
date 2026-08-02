from pathlib import Path

from json import dumps

from app.native_file_drop import (
    DROP_ID_EVENT_FIELD,
    DROP_TARGET_ID_EVENT_FIELD,
    _drop_detail,
    _read_webview2_drop_request,
)


def test_drop_detail_returns_native_paths_without_browser_coordinates(tmp_path: Path) -> None:
    dropped_file = tmp_path / "拖入文件.md"
    dropped_file.write_text("content", encoding="utf-8")

    detail = _drop_detail({
        DROP_ID_EVENT_FIELD: "drop-1",
        DROP_TARGET_ID_EVENT_FIELD: "composer",
        "dataTransfer": {
            "files": [
                {
                    "name": dropped_file.name,
                    "pywebviewFullPath": str(dropped_file),
                }
            ]
        }
    })

    assert detail == {
        "dropId": "drop-1",
        "targetId": "composer",
        "entries": [{
            "kind": "file",
            "name": dropped_file.name,
            "path": str(dropped_file.resolve()),
        }]
    }


def test_drop_detail_rejects_events_without_native_paths() -> None:
    assert _drop_detail({
        DROP_ID_EVENT_FIELD: "drop-1",
        DROP_TARGET_ID_EVENT_FIELD: "composer",
        "dataTransfer": {"files": [{"name": "missing.md"}]},
    }) is None


def test_drop_detail_requires_drop_and_target_ids(tmp_path: Path) -> None:
    dropped_file = tmp_path / "missing-id.md"
    dropped_file.write_text("content", encoding="utf-8")

    assert _drop_detail({
        "dataTransfer": {
            "files": [{"pywebviewFullPath": str(dropped_file)}],
        },
    }) is None


def test_webview2_drop_request_keeps_metadata_and_paths_atomic(tmp_path: Path) -> None:
    dropped_file = tmp_path / "atomic.md"
    dropped_file.write_text("content", encoding="utf-8")

    request = _read_webview2_drop_request(
        dumps([
            "pywebviewEventHandler",
            dumps({
                "nodeId": "__tiance_native_file_drop__",
                "event": {
                    "type": "tiance-native-file-drop",
                    "dropId": "drop-2",
                    "targetId": "composer",
                },
            }),
            "drop-2",
        ]),
        [_AdditionalFile(str(dropped_file))],
    )

    assert request == {
        "dropId": "drop-2",
        "targetId": "composer",
        "paths": [str(dropped_file)],
    }


class _AdditionalFile:
    def __init__(self, path: str) -> None:
        self.Path = path
