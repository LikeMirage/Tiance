from __future__ import annotations

from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse


PROGRAM = Path(__file__).resolve().parents[1] / "program"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FOLLOWER = load("bridge_run_under_test", PROGRAM / "conversation_run.py")
runtime = types.ModuleType("tiance_runtime")
runtime.run_tool = lambda handler: None
with patch.dict(sys.modules, {"conversation_run": FOLLOWER, "tiance_runtime": runtime}):
    BRIDGE = load("bridge_main_under_test", PROGRAM / "main.py")


def event(kind, **fields):
    return {"kind": kind, **fields}


def started(user="root"):
    return event("conversation_run_started", user_message_id=user)


def settled(status="done", user="root", assistant="reply"):
    return event("conversation_run_settled", user_message_id=user,
                 assistant_message_id=assistant, status=status)


def turn(status="done", user="root", assistant="reply", *, finish=None, error=None):
    items = [{"role": "user", "message_id": user, "session_id": "session", "content": "request"}]
    if assistant:
        items.append({"role": "assistant", "message_id": assistant, "session_id": "session",
                      "content": "persisted reply", "status": "done" if finish else status,
                      "finish_reason": finish, "tool_calls": []})
    return {"project_id": "project", "session_id": "session", "user_message_id": user, "items": items,
            "run_outcomes": [{"run_id": "run-" + user, "user_message_id": user, "session_id": "session",
                              "status": status, "error_code": error, "started_at": "2026-10-30T00:00:00Z"}]}


class Backend:
    def __init__(self, streams, turns, running=False, following=None):
        self.streams = list(streams)
        self.turns = turns
        self.running = running
        self.following = following or {}
        self.requests = []
        self.elapsed = 0.0

    def open(self, request, **kwargs):
        self.requests.append(request)
        value = self.streams.pop(0)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, bytes):
            return io.BytesIO(value)
        raw = "".join("data: " + json.dumps(item) + "\n\n" for item in value)
        return io.BytesIO(raw.encode())

    def query(self, method, path, body=None, **kwargs):
        assert method == "GET", "recovery must never send another user message"
        if path.endswith("/conversations"):
            return {"items": [{"session_id": "session", "provider_id": "provider", "model_id": "model"}],
                    "session_states": {"session": {"runtime_status": "idle"}}}
        if "/stream/status?" in path:
            return {"running": self.running}
        if path.endswith("/turn"):
            user = unquote(path.split("/messages/")[1].removesuffix("/turn"))
            value = self.turns.get(user)
            if callable(value):
                value = value()
            if value is None:
                raise FOLLOWER.BridgeError("BACKEND_HTTP_ERROR", "not found", {"http_status": 404})
            return deepcopy(value)
        if "/messages?" in path:
            from urllib.parse import parse_qs
            last = parse_qs(urlparse(path).query)["after_message_id"][0]
            return {"project_id": "project", "session_id": "session", "items": self.following.get(last, [])}
        raise AssertionError(path)

    def sleep(self, delay):
        self.elapsed += delay


class ConversationRunTests(unittest.TestCase):
    def call(self, backend, timeout=10):
        with patch.object(BRIDGE, "uuid4", return_value="root"), \
             patch.object(BRIDGE, "_json_request", side_effect=backend.query), \
             patch.object(BRIDGE, "DEFAULT_TIMEOUT_SECONDS", timeout), \
             patch.object(FOLLOWER, "urlopen", side_effect=backend.open), \
             patch.object(FOLLOWER, "monotonic", side_effect=lambda: backend.elapsed), \
             patch.object(FOLLOWER, "sleep", side_effect=backend.sleep):
            result = BRIDGE.run({"action": "send", "project_id": "project", "session_id": "session", "message": "hello"})
        posts = [r for r in backend.requests if r.get_method() == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(json.loads(posts[0].data)["messages"][0]["message_id"], "root")
        return result

    def test_empty_stream_is_not_success(self):
        result = self.call(Backend([[]], {}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_info"]["code"], "SESSION_RUN_UNCONFIRMED")

    def test_partial_stream_and_done_event_are_not_terminal(self):
        for ending in [[], [event("done", finish_reason="stop")]]:
            with self.subTest(ending=ending):
                b = Backend([[started(), event("delta", content="partial"), *ending]], {"root": turn("running")})
                result = self.call(b)
                self.assertEqual(result["error_info"]["code"], "SESSION_RUN_UNCONFIRMED")

    def test_saved_tool_round_does_not_finish_running_task(self):
        saved = turn("running")
        saved["items"][-1].update(status="done", tool_calls=[{"id": "tool-1"}])
        result = self.call(Backend([[started()]], {"root": saved}))
        self.assertFalse(result["ok"])

    def test_saved_reply_without_run_outcome_is_not_enough(self):
        saved = turn()
        saved["run_outcomes"] = []
        result = self.call(Backend([[started()]], {"root": saved}))
        self.assertEqual(result["error_info"]["code"], "SESSION_RUN_UNCONFIRMED")

    def test_end_status_must_agree_with_storage(self):
        result = self.call(Backend([[started(), settled("done")]], {"root": turn("error")}))
        self.assertEqual(result["error_info"]["code"], "SESSION_RUN_MISMATCH")

    def test_success_uses_persisted_reply(self):
        b = Backend([[started(), event("delta", content="different fragment"), settled()]], {"root": turn()})
        result = self.call(b)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["reply"], "persisted reply")
        self.assertEqual(result["data"]["outcome"], "done")
        self.assertEqual(result["data"]["runtime_status"], "idle")

    def test_lost_final_event_recovers_from_durable_run(self):
        result = self.call(Backend([[started()]], {"root": turn()}))
        self.assertTrue(result["ok"])

    def test_disconnect_after_accepted_post_does_not_resend(self):
        result = self.call(Backend([URLError("disconnected")], {"root": turn()}))
        self.assertTrue(result["ok"])

    def test_reconnects_existing_run(self):
        b = Backend([[started()], [started(), settled()]], {}, running=True)
        b.turns["root"] = lambda: turn("running" if len(b.requests) == 1 else "done")
        result = self.call(b)
        self.assertTrue(result["ok"])
        self.assertEqual([r.get_method() for r in b.requests], ["POST", "GET"])
        self.assertIn("/stream/active?", b.requests[-1].full_url)

    def test_error_and_cancellation_remain_distinct(self):
        failed = self.call(Backend([[started(), settled("error")]], {"root": turn("error")}))
        self.assertEqual(failed["error_info"]["code"], "SESSION_RUN_ERROR")
        cancelled = self.call(Backend([[started(), settled("cancelled", assistant=None)]],
                                      {"root": turn("cancelled", assistant=None)}))
        self.assertTrue(cancelled["ok"])
        self.assertEqual(cancelled["data"]["outcome"], "cancelled")
        self.assertIn("取消", cancelled["summary"])

    def test_foreign_end_and_wrong_assistant_are_rejected(self):
        for terminal in [settled(user="other"), settled(assistant="wrong")]:
            with self.subTest(terminal=terminal):
                result = self.call(Backend([[started(), terminal]], {"root": turn()}))
                self.assertEqual(result["error_info"]["code"], "SESSION_RUN_MISMATCH")

    def test_foreign_saved_turn_is_rejected(self):
        result = self.call(Backend([[started()]], {"root": turn(user="other")}))
        self.assertEqual(result["error_info"]["code"], "SESSION_RUN_MISMATCH")

    def test_running_other_conversation_request_is_not_adopted(self):
        b = Backend([[started()], [started("other")]], {"root": turn("running")}, running=True)
        result = self.call(b)
        self.assertEqual(result["error_info"]["code"], "SESSION_RUN_MISMATCH")

    def test_output_limit_continuation_and_replay(self):
        next_user = {"role": "user", "message_id": "child", "message_source": "output_limit", "continuation_of": "root"}
        notice = event("output_limit", action="send_message", will_recover=True, next_user_message=next_user)
        b = Backend([[started(), notice, settled("error"), notice, started("child"), settled(user="child")]],
                    {"child": turn(user="child")})
        result = self.call(b)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["user_message_id"], "root")
        self.assertEqual(result["data"]["reply_user_message_id"], "child")

    def test_lost_continuation_notice_is_recovered_from_storage(self):
        next_user = {"role": "user", "message_id": "child", "message_source": "output_limit", "continuation_of": "root"}
        b = Backend([[started()]], {"root": turn("error", finish="output_limit", error="upstream_output_limit"),
                                    "child": turn(user="child")}, following={"reply": [next_user]})
        result = self.call(b)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["reply_user_message_id"], "child")

    def test_output_limit_without_continuation_is_error(self):
        b = Backend([[started(), settled("error")]], {"root": turn("error", finish="output_limit", error="upstream_output_limit")})
        self.assertEqual(self.call(b)["error_info"]["code"], "SESSION_RUN_ERROR")

    def test_status_read_finish_race_rechecks_storage(self):
        reads = iter([turn("running"), turn()])
        result = self.call(Backend([[started()]], {"root": lambda: next(reads)}, running=False))
        self.assertTrue(result["ok"])

    def test_resume_404_finish_race_rechecks_storage(self):
        b = Backend([[started()], HTTPError("http://test", 404, "finished", {}, None)], {}, running=True)
        b.turns["root"] = lambda: turn("running" if len(b.requests) == 1 else "done")
        self.assertTrue(self.call(b)["ok"])

    def test_backend_unavailable_has_bounded_wait(self):
        b = Backend([URLError("offline")], {})
        original = b.query
        def query(method, path, **kwargs):
            if path.endswith("/conversations"):
                return original(method, path, **kwargs)
            raise FOLLOWER.BridgeError("BACKEND_UNREACHABLE", "offline")
        b.query = query
        result = self.call(b, timeout=1)
        self.assertEqual(result["error_info"]["code"], "SESSION_RUN_UNCONFIRMED")
        self.assertLessEqual(b.elapsed, 1)

    def test_multiline_sse_and_malformed_event(self):
        raw = b'data: {"kind": "conversation_run_started",\ndata: "user_message_id": "root"}\n\n'
        self.assertTrue(self.call(Backend([raw], {"root": turn()}))["ok"])
        result = self.call(Backend([b'data: {bad json}\n\n'], {}))
        self.assertEqual(result["error_info"]["code"], "BACKEND_INVALID_STREAM")


if __name__ == "__main__":
    unittest.main()
