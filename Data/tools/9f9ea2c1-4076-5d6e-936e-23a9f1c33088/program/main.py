"""Independent JSON-in/JSON-out icon tool. Runtime performs no network requests."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from catalog import Catalog
from rendering import contact_sheet, rasterize, styled_svg

FIELDS = {
    "libraries": {"action"},
    "search": {"action", "queries", "libraries", "limit", "offset"},
    "preview": {"action", "icons", "columns", "color", "output_dir"},
    "export": {"action", "icons", "formats", "color", "size", "output_dir"},
}


def validate(arguments: dict) -> None:
    if not isinstance(arguments, dict) or arguments.get("action") not in FIELDS:
        raise ValueError("action must be libraries, search, preview or export")
    action = arguments["action"]
    if extra := arguments.keys() - FIELDS[action]:
        raise ValueError(f"Parameters not used by {action}: {', '.join(sorted(extra))}")
    required = {"search": "queries", "preview": "icons", "export": "icons"}.get(action)
    if required and required not in arguments:
        raise ValueError(f"{action} requires {required}")
    for field in ("queries", "libraries", "icons", "formats"):
        if field not in arguments:
            continue
        value = arguments[field]
        if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
            raise ValueError(f"{field} must be a non-empty array of non-empty strings")
        if len(set(value)) != len(value):
            raise ValueError(f"{field} must not contain duplicates")
    for field in ("limit", "offset", "columns", "size"):
        if field in arguments and (type(arguments[field]) is not int or arguments[field] < (0 if field == "offset" else 1)):
            raise ValueError(f"{field} must be {'a non-negative' if field == 'offset' else 'a positive'} integer")
    if "formats" in arguments and set(arguments["formats"]) - {"svg", "png"}:
        raise ValueError("formats supports svg and png only")
    if "color" in arguments and (not isinstance(arguments["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", arguments["color"])):
        raise ValueError("color must be #RRGGBB; omit it to keep the original palette")
    if "output_dir" in arguments and (not isinstance(arguments["output_dir"], str) or not arguments["output_dir"].strip()):
        raise ValueError("output_dir must be a non-empty directory path")


def destination(arguments: dict) -> Path:
    workspace_text = os.environ.get("TIANCE_WORKSPACE_ROOT", "").strip()
    workspace = Path(workspace_text).resolve() if workspace_text else None
    raw = arguments.get("output_dir")
    if raw is None:
        if workspace is None:
            raise ValueError("No caller workspace; pass an absolute output_dir")
        root = (workspace / "icons").resolve()
        if not root.is_relative_to(workspace):
            raise ValueError("Default icons directory resolves outside the workspace; specify output_dir explicitly")
    else:
        root = Path(raw).expanduser()
        if not root.is_absolute():
            if workspace is None:
                raise ValueError("Relative output_dir requires TIANCE_WORKSPACE_ROOT; otherwise use an absolute path")
            root = workspace / root
        root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=arguments["action"] + "-", dir=root))


def artifact(path: Path, **extra) -> dict:
    return {"path": str(path.resolve()), "size_bytes": path.stat().st_size, **extra}


def finish_manifest(catalog: Catalog, records: list[dict], folder: Path, data: dict, arguments: dict) -> dict:
    notices, sources = [], []
    for library_id in dict.fromkeys(record["library"] for record in records):
        library = catalog.libraries[library_id]
        target = folder / "licenses" / f"{library_id}.txt"
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(catalog.assets / library["license_file"], target)
        notices.append(artifact(target))
        sources.append({k: library[k] for k in ("id", "name", "version", "source", "license")})
    manifest = {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "action": arguments["action"], "options": arguments,
        "libraries": sources, "license_files": notices, **data,
    }
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**data, "output_dir": str(folder), "manifest": artifact(path), "license_files": notices}


def run(arguments: dict) -> dict:
    folder = None
    try:
        validate(arguments)
        catalog = Catalog()
        action = arguments["action"]
        if action == "libraries":
            data = {"libraries": [
                {k: library[k] for k in ("id", "name", "version", "styles", "icon_count", "source", "license")}
                for library in catalog.libraries.values()
            ], "total_icons": sum(lib["icon_count"] for lib in catalog.libraries.values())}
            return {"ok": True, "summary": "本地图库列表", "data": data}
        if action == "search":
            data = catalog.search(arguments["queries"], arguments.get("libraries", list(catalog.libraries)),
                                  arguments.get("limit", 20), arguments.get("offset", 0))
            return {"ok": True, "summary": "搜索完成；需要查看外观时，将候选 ID 传给 preview。",
                    "data": {"queries": data}}
        records = catalog.select(arguments["icons"])
        color = arguments.get("color")
        # Finish rendering first: a failed preview must never masquerade as a full contact sheet.
        if action == "preview":
            image, placements, columns = contact_sheet(catalog, records, columns=arguments.get("columns"), color=color)
            folder = destination(arguments)
            path = folder / "preview.png"
            image.save(path, format="PNG")
            data = {"preview": artifact(path, width=image.width, height=image.height),
                    "columns": columns, "items": [catalog.describe(record) | placement
                                                  for record, placement in zip(records, placements)]}
            data = finish_manifest(catalog, records, folder, data, arguments)
            return {"ok": True, "summary": f"已生成含 {len(records)} 个图标的合并预览；用图片读取工具打开 preview.path 选图。", "data": data}
        folder = destination(arguments)
        files, failures = [], []
        for record in records:
            try:
                svg = styled_svg(catalog.svg(record), color)
            except Exception as exc:
                failures.append({"id": record["id"], "formats": arguments.get("formats", ["svg", "png"]), "error": str(exc)})
                continue
            for fmt in arguments.get("formats", ["svg", "png"]):
                target = (folder / record["library"] / record["path"]).with_suffix("." + fmt)
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if fmt == "svg":
                        target.write_bytes(svg)
                        details = {"view_box": record["view_box"]}
                    else:
                        image = rasterize(svg, arguments.get("size", 512))
                        image.save(target, format="PNG")
                        details = {"width": image.width, "height": image.height}
                    files.append(catalog.describe(record) | artifact(target, format=fmt, **details))
                except Exception as exc:
                    failures.append({"id": record["id"], "format": fmt, "error": str(exc)})
        data = finish_manifest(catalog, records, folder, {"files": files, "failures": failures}, arguments)
        result = {"ok": not failures, "summary": f"已导出 {len(files)} 个文件；失败 {len(failures)} 项。", "data": data}
        if failures:
            result["error"] = "部分图标导出失败，已完成的文件仍保留，详见 data.failures。"
        return result
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if folder:
            result["data"] = {"output_dir": str(folder), "incomplete": True}
        return result


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        result = run(json.load(sys.stdin))
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)
