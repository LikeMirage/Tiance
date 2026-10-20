"""Lossless JSON changes, including list edits and object key order."""
from __future__ import annotations

from copy import deepcopy
from json import dumps
from typing import Any


def json_bytes(value: Any) -> bytes:
    return dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def make_delta(before: Any, after: Any) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []

    def visit(old: Any, new: Any, path: list[str | int]) -> None:
        if type(old) is dict and type(new) is dict:
            for key in old:
                if key not in new:
                    operations.append({"op": "remove", "path": [*path, key]})
            for key, value in new.items():
                if key not in old:
                    operations.append({"op": "set", "path": [*path, key], "value": value})
                else:
                    visit(old[key], value, [*path, key])
            resulting_keys = [key for key in old if key in new] + [key for key in new if key not in old]
            if resulting_keys != list(new):
                operations.append({"op": "order", "path": path, "keys": list(new)})
        elif type(old) is list and type(new) is list:
            # A splice also represents context compression, truncation and reordering.
            old_items = [json_bytes(value) for value in old]
            new_items = [json_bytes(value) for value in new]
            start = 0
            shared = min(len(old), len(new))
            while start < shared and old_items[start] == new_items[start]:
                start += 1
            suffix = 0
            while suffix < shared - start and old_items[-1 - suffix] == new_items[-1 - suffix]:
                suffix += 1
            if start != len(old) or start != len(new):
                operations.append({
                    "op": "splice", "path": path, "start": start,
                    "delete": len(old) - start - suffix,
                    "items": new[start:len(new) - suffix],
                })
        elif json_bytes(old) != json_bytes(new):
            operations.append({"op": "set", "path": path, "value": new})

    visit(before, after, [])
    return operations


def apply_delta(before: Any, operations: list[dict[str, Any]]) -> Any:
    root = deepcopy(before)

    def at(path: list[str | int]) -> Any:
        value = root
        for segment in path:
            if type(value) is dict and type(segment) is str and segment in value:
                value = value[segment]
            elif type(value) is list and type(segment) is int and 0 <= segment < len(value):
                value = value[segment]
            else:
                raise ValueError("Invalid audit delta path.")
        return value

    for operation in operations:
        path = operation["path"]
        op = operation["op"]
        if not isinstance(path, list):
            raise ValueError("Invalid audit delta path.")
        if op == "set":
            value = deepcopy(operation["value"])
            if not path:
                root = value
            else:
                parent, key = at(path[:-1]), path[-1]
                if type(parent) is dict and type(key) is str:
                    parent[key] = value
                elif type(parent) is list and type(key) is int and 0 <= key < len(parent):
                    parent[key] = value
                else:
                    raise ValueError("Invalid audit delta assignment.")
        elif op == "remove":
            parent = at(path[:-1])
            if not path or type(parent) is not dict or path[-1] not in parent:
                raise ValueError("Invalid audit delta removal.")
            del parent[path[-1]]
        elif op == "order":
            target, keys = at(path), operation["keys"]
            if type(target) is not dict or len(keys) != len(target) or set(keys) != set(target):
                raise ValueError("Invalid audit delta key order.")
            ordered = {key: target[key] for key in keys}
            target.clear()
            target.update(ordered)
        elif op == "splice":
            target = at(path)
            start, count, items = operation["start"], operation["delete"], operation["items"]
            if (type(target) is not list or type(start) is not int or type(count) is not int
                    or not 0 <= start <= len(target) or not 0 <= count <= len(target) - start
                    or type(items) is not list):
                raise ValueError("Invalid audit delta splice.")
            target[start:start + count] = deepcopy(items)
        else:
            raise ValueError(f"Unsupported audit delta operation: {op}")
    return root
