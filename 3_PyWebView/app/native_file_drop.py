from __future__ import annotations

import json
import logging
import os
import sys
from json import dumps
from pathlib import Path
from threading import Thread
from typing import Any


NATIVE_FILE_DROP_EVENT = "tiance-native-file-drop"
NATIVE_FILE_DROP_MESSAGE_TYPE = "tiance-native-file-drop"
DROP_ID_EVENT_FIELD = "__tianceNativeFileDropId"
DROP_TARGET_ID_EVENT_FIELD = "__tianceNativeFileDropTargetId"
DROP_TARGET_ATTRIBUTE = "data-tiance-file-drop-target"

logger = logging.getLogger("tiance.desktop.native_file_drop")


def _build_install_drop_listener_script(*, webview2_enabled: bool) -> str:
    return f"""
(() => {{
  if (window.__tianceNativeFileDropBridgeInstalled) return;
  window.__tianceNativeFileDropBridgeInstalled = true;
  const webview2BridgeEnabled = {str(webview2_enabled).lower()};
  let nextDropSequence = 0;

  document.addEventListener("drop", (event) => {{
    const files = event.dataTransfer?.files;
    if (!files || files.length === 0) return;

    const eventTarget = event.target instanceof Element
      ? event.target
      : event.target?.parentElement;
    const dropTarget = eventTarget?.closest("[{DROP_TARGET_ATTRIBUTE}]");
    const targetId = dropTarget?.getAttribute("{DROP_TARGET_ATTRIBUTE}")?.trim();
    if (!targetId) return;

    nextDropSequence += 1;
    const dropId = `drop-${{Date.now().toString(36)}}-${{nextDropSequence.toString(36)}}`;
    event.{DROP_ID_EVENT_FIELD} = dropId;
    event.{DROP_TARGET_ID_EVENT_FIELD} = targetId;

    if (
      webview2BridgeEnabled &&
      window.chrome?.webview &&
      typeof window.chrome.webview.postMessageWithAdditionalObjects === "function"
    ) {{
      window.chrome.webview.postMessageWithAdditionalObjects(
        [
          "pywebviewEventHandler",
          JSON.stringify({{
            nodeId: "__tiance_native_file_drop__",
            event: {{
              type: "{NATIVE_FILE_DROP_MESSAGE_TYPE}",
              dropId,
              targetId,
            }},
          }}),
          dropId,
        ],
        files,
      );
    }}
  }}, true);
}})();
"""


def install_native_file_drop_bridge(window: Any) -> None:
    state: dict[str, Any] = {
        "webview": None,
        "handler": None,
        "fallback_bound": False,
    }

    def dispatch_detail(detail: dict[str, Any]) -> None:
        window.evaluate_js(
            "window.dispatchEvent(new CustomEvent("
            f"{dumps(NATIVE_FILE_DROP_EVENT)}, {{ detail: {dumps(detail, ensure_ascii=False)} }}"
            "));"
        )

    def dispatch_paths(request: dict[str, Any]) -> None:
        detail = _drop_detail_from_paths(
            request["paths"],
            drop_id=request["dropId"],
            target_id=request["targetId"],
        )
        if detail is not None:
            dispatch_detail(detail)

    def install_webview2_handler() -> bool:
        if sys.platform != "win32":
            return False

        native = getattr(window, "native", None)
        webview = getattr(native, "webview", None)
        if webview is None:
            return False
        if state["webview"] is webview:
            return True

        def handle_web_message(_sender: Any, args: Any) -> None:
            raw_message = args.get_WebMessageAsJson()
            request = _read_webview2_drop_request(
                raw_message,
                args.get_AdditionalObjects(),
            )
            if request is None:
                return
            Thread(target=dispatch_paths, args=(request,), daemon=True).start()

        try:
            webview.WebMessageReceived += handle_web_message
        except Exception:
            logger.exception("Unable to install the WebView2 file-drop message handler.")
            return False

        state.update({
            "webview": webview,
            "handler": handle_web_message,
        })
        return True

    def bind_legacy_document_drop() -> None:
        if state["fallback_bound"]:
            return
        from webview.dom import DOMEventHandler

        def handle_drop(event: dict[str, Any]) -> None:
            detail = _drop_detail(event)
            if detail is not None:
                dispatch_detail(detail)

        window.dom.document.events.drop += DOMEventHandler(handle_drop)
        state["fallback_bound"] = True

    def install_current_document(*_args: object) -> None:
        webview2_ready = install_webview2_handler()
        if not webview2_ready:
            state["fallback_bound"] = False
            bind_legacy_document_drop()
        window.evaluate_js(_build_install_drop_listener_script(webview2_enabled=webview2_ready))

    window.events.loaded += install_current_document


def _read_webview2_drop_request(
    raw_message: str,
    additional_objects: Any,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw_message)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, list) or len(payload) != 3:
        return None
    if payload[0] != "pywebviewEventHandler" or not isinstance(payload[1], str):
        return None
    try:
        bridge_payload = json.loads(payload[1])
    except (TypeError, ValueError):
        return None
    if not isinstance(bridge_payload, dict):
        return None
    event_payload = bridge_payload.get("event")
    if (
        bridge_payload.get("nodeId") != "__tiance_native_file_drop__"
        or not isinstance(event_payload, dict)
        or event_payload.get("type") != NATIVE_FILE_DROP_MESSAGE_TYPE
    ):
        return None

    drop_id = _non_empty_string(event_payload.get("dropId"))
    target_id = _non_empty_string(event_payload.get("targetId"))
    if drop_id is None or target_id is None or additional_objects is None:
        return None

    paths: list[str] = []
    for item in list(additional_objects):
        path = _non_empty_string(getattr(item, "Path", None))
        if path is not None:
            paths.append(path)
    if not paths:
        return None
    return {
        "dropId": drop_id,
        "targetId": target_id,
        "paths": paths,
    }


def _drop_detail(event: dict[str, Any]) -> dict[str, Any] | None:
    data_transfer = event.get("dataTransfer")
    if not isinstance(data_transfer, dict):
        return None
    files = data_transfer.get("files")
    if not isinstance(files, list):
        return None

    drop_id = _non_empty_string(event.get(DROP_ID_EVENT_FIELD))
    target_id = _non_empty_string(event.get(DROP_TARGET_ID_EVENT_FIELD))
    if drop_id is None or target_id is None:
        return None

    paths = [
        raw_path
        for file in files
        if isinstance(file, dict)
        if (raw_path := _non_empty_string(file.get("pywebviewFullPath"))) is not None
    ]
    return _drop_detail_from_paths(paths, drop_id=drop_id, target_id=target_id)


def _drop_detail_from_paths(
    paths: list[str],
    *,
    drop_id: str,
    target_id: str,
) -> dict[str, Any] | None:
    entries: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for raw_path in paths:
        normalized_path = os.path.abspath(os.path.expanduser(raw_path))
        comparison_path = os.path.normcase(normalized_path)
        if comparison_path in seen_paths:
            continue
        seen_paths.add(comparison_path)
        path = Path(normalized_path)
        entries.append({
            "kind": "folder" if path.is_dir() else "file",
            "name": path.name or normalized_path,
            "path": normalized_path,
        })

    if not entries:
        return None
    return {
        "dropId": drop_id,
        "targetId": target_id,
        "entries": entries,
    }


def _non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
