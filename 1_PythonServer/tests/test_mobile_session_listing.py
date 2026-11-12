import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from app.domain.project.conversation_hierarchy import visible_conversation_parents
from app.services.mobile import context
from tests.test_collection_default_roles import services
from tests.test_mobile_access import host, repository


def node(session_id, parent=None, kind="root", function=None, deleted=None):
    return NS(session_id=session_id, parent_session_id=parent, relation_kind=kind,
              function_type=function, deleted_at=deleted)


def snapshot(monkeypatch, sessions, nodes):
    monkeypatch.setattr(context, "get_project_conversation_service", lambda: NS(
        get_list_data=lambda *a, **k: (0, sessions, nodes, [], None, {})))


def test_membership_and_order_come_from_sessions_not_branch_graph(monkeypatch):
    # Ordinary list order is pinned first, then newest. Graph order is unrelated.
    sessions = [NS(session_id=s) for s in ["pinned", "new", "old", "child"]]
    nodes = [node("old"), node("child", "old", "child"), node("pinned"), node("deleted")]
    snapshot(monkeypatch, sessions, nodes)
    assert [s.session_id for s, _ in context.session_children("p")] == ["pinned", "new", "old"]
    assert context.session_children("p")[1][1] is None
    assert [s.session_id for s, _ in context.session_children("p", "old", "child")] == ["child"]


def test_all_recursive_leaf_groups_and_surviving_ancestry(monkeypatch):
    nodes = [node("root"), node("removed", "root", "child", deleted="deleted")]
    groups = ["child", "fork", *context.GROUPS.keys() - {"child", "fork"}]
    for group in groups:
        nodes.append(node(group, "removed", group if group in {"child", "fork"} else "functional",
                          None if group in {"child", "fork"} else group))
    nodes.extend([node("nested", "child", "child"), node("orphan", "missing", "fork")])
    sessions = [NS(session_id=n.session_id) for n in nodes if not n.deleted_at]
    snapshot(monkeypatch, sessions, nodes)
    assert [s.session_id for s, _ in context.session_children("p")] == ["root", "orphan"]
    for group in groups:
        assert [s.session_id for s, _ in context.session_children("p", "root", group)] == [group]
    assert [s.session_id for s, _ in context.session_children("p", "child", "child")] == ["nested"]


def test_broken_relationships_cannot_make_sessions_unreachable():
    nodes = [node("a", "b", "child"), node("b", "a", "child"),
             node("self", "self", "fork"), node("unknown", "a", "functional", "unknown")]
    sessions = [NS(session_id=n.session_id) for n in nodes]
    parents = visible_conversation_parents(sessions, nodes)
    assert parents == {"b": ("a", "child")}
    assert nodes[0].parent_session_id == "b"  # display projection must not alter storage


def test_new_unbranched_session_is_immediately_listed(services, monkeypatch):
    projects, conversations, roles, creation = services
    project = creation.create_project(name="手机会话目录")
    first = conversations.list_sessions(project.project_id)[0]
    new = conversations.create_session(project.project_id, title="新建主会话", set_active=False)
    nodes, _ = conversations.list_branch_graph(project.project_id)
    assert new.session_id not in {n.session_id for n in nodes}
    monkeypatch.setattr(context, "get_project_conversation_service", lambda: conversations)
    assert [s.session_id for s, _ in context.session_children(project.project_id)] == [new.session_id, first.session_id]


@pytest.mark.parametrize("count", [0, 1, 8, 9, 10, 17])
def test_session_pages_count_only_sessions_and_reach_every_item(host, monkeypatch, count):
    async def run():
        peer = "telegram:12:7:7"
        target = {"project_id": "p"}
        # Real sessions may have no graph nodes at all.
        sessions = [NS(session_id=f"s{i}", title=f"会话{i}") for i in range(count, 0, -1)]
        snapshot(monkeypatch, sessions, [])
        host.reply = AsyncMock()
        await host.put("selection", peer, {"project_id": "elsewhere", "session_id": "keep"})
        seen = []
        action_args = {"target": target}
        page = 0
        while True:
            await host.navigation.action(peer, "sessions", **action_args)
            _, title, actual_target, rows = host.reply.call_args.args
            assert title.startswith(f"主会话（{count}）")
            assert actual_target == target
            callbacks = [await host.get("callbacks", button["callback_data"])
                         for row in rows for button in row]
            listed = [c["target"]["session_id"] for c in callbacks if c["action"] == "select"
                      and c['target']['project_id'] == target['project_id']]
            seen.extend(listed)
            assert len(listed) == min(8, max(0, count - page * 8))
            assert len([c for c in callbacks if c["action"] == "new"]) == 1
            if count > 8:
                assert f"第 {page+1}/{(count+7)//8} 页" in title
            next_page = next((c for c in callbacks if c["action"] == "sessions" and c.get("page") == page+1), None)
            if next_page is None:
                break
            action_args = {k:v for k,v in next_page.items() if k not in {"peer", "action"}}
            page += 1
        assert seen == [s.session_id for s in sessions]
        assert len(seen) == len(set(seen))
        assert await host.get("selection", peer) == {"project_id": "elsewhere", "session_id": "keep"}
    asyncio.run(run())
