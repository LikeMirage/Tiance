from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import BadRequestError
from app.domain.project import ProjectKind
from app.infra.projects import ProjectIdentity, read_project_identity, write_project_identity


PROJECT_MARKET_ORIGIN_FILE = Path(".Tiance") / "market.json"
_ACTIVE_STATUSES = frozenset({"pending", "queued", "running", "streaming", "executing"})


def prepare_project_market_snapshot(
    project_root: Path,
    *,
    project_id: str,
    project_name: str,
    market_project_id: str,
    source: str,
    version: str,
    installed_at: str,
    project_kind: ProjectKind,
) -> None:
    """重绑定快照所属项目，并把无法恢复的运行态安全收敛。"""
    root = project_root.resolve()
    if not root.is_dir() or root.is_symlink():
        raise BadRequestError("项目快照根目录无效。")

    try:
        previous_identity = read_project_identity(root)
    except ValueError as exc:
        raise BadRequestError("项目快照中的项目身份文件无效。") from exc

    tiance_root = root / ".Tiance"
    previous_project_id = (
        previous_identity.project_id if previous_identity is not None else None
    )
    if previous_project_id is None and tiance_root.is_dir():
        previous_project_id = _infer_owned_project_id(tiance_root)
    if tiance_root.is_dir():
        _rewrite_tiance_payloads(
            tiance_root,
            previous_project_id=previous_project_id,
            project_id=project_id,
        )

    write_project_identity(
        root,
        ProjectIdentity(project_id=project_id, name=project_name),
    )
    _write_json_atomic(
        root / PROJECT_MARKET_ORIGIN_FILE,
        {
            "schema_version": 1,
            "kind": "tiance-project-market-origin",
            "source": source,
            "market_project_id": market_project_id,
            "version": version,
            "installed_at": installed_at,
            "project_kind": project_kind.value,
        },
    )


def read_project_market_origin(project_root: str | Path) -> dict[str, object] | None:
    path = Path(project_root).resolve() / PROJECT_MARKET_ORIGIN_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("kind") != "tiance-project-market-origin":
        return None
    return payload


def _rewrite_tiance_payloads(
    tiance_root: Path,
    *,
    previous_project_id: str | None,
    project_id: str,
) -> None:
    for path in sorted(tiance_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() == ".json":
            _rewrite_json_file(
                path,
                previous_project_id=previous_project_id,
                project_id=project_id,
            )
        elif path.suffix.lower() == ".jsonl":
            _rewrite_jsonl_file(
                path,
                previous_project_id=previous_project_id,
                project_id=project_id,
            )


def _rewrite_json_file(
    path: Path,
    *,
    previous_project_id: str | None,
    project_id: str,
) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BadRequestError(f"项目状态文件 '{path.name}' 不是有效 JSON。") from exc
    rewritten = _rewrite_payload(
        payload,
        previous_project_id=previous_project_id,
        project_id=project_id,
    )
    _write_json_atomic(path, rewritten)


def _rewrite_jsonl_file(
    path: Path,
    *,
    previous_project_id: str | None,
    project_id: str,
) -> None:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        payloads = [json.loads(line) for line in lines if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BadRequestError(f"项目状态文件 '{path.name}' 不是有效 JSONL。") from exc
    rewritten = [
        _rewrite_payload(
            payload,
            previous_project_id=previous_project_id,
            project_id=project_id,
        )
        for payload in payloads
    ]
    text = "".join(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        for payload in rewritten
    )
    _write_text_atomic(path, text)


def _rewrite_payload(
    value: object,
    *,
    previous_project_id: str | None,
    project_id: str,
) -> object:
    if isinstance(value, list):
        return [
            _rewrite_payload(
                item,
                previous_project_id=previous_project_id,
                project_id=project_id,
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    rewritten: dict[str, object] = {}
    for key, item in value.items():
        if key == "project_id" and previous_project_id is not None and item == previous_project_id:
            rewritten[key] = project_id
            continue
        rewritten[key] = _rewrite_payload(
            item,
            previous_project_id=previous_project_id,
            project_id=project_id,
        )

    if rewritten.get("runtime_status") in _ACTIVE_STATUSES:
        rewritten["runtime_status"] = "idle"
    if rewritten.get("status") in _ACTIVE_STATUSES:
        rewritten["status"] = "failed"
        rewritten.setdefault("completed_at", datetime.now(UTC).isoformat())
        if "error" in rewritten:
            rewritten["error"] = "项目快照导入时已停止未完成任务。"
    return rewritten


def _infer_owned_project_id(tiance_root: Path) -> str | None:
    candidates: set[str] = set()
    for path in tiance_root.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in {".json", ".jsonl"}:
            continue
        try:
            if path.suffix.lower() == ".json":
                payloads = [json.loads(path.read_text(encoding="utf-8-sig"))]
            else:
                payloads = [
                    json.loads(line)
                    for line in path.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip()
                ]
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        for payload in payloads:
            _collect_project_ids(payload, candidates)
            if len(candidates) > 1:
                return None
    return next(iter(candidates), None)


def _collect_project_ids(value: object, candidates: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_project_ids(item, candidates)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if key == "project_id" and isinstance(item, str):
            try:
                candidates.add(str(UUID(item)))
            except ValueError:
                pass
        else:
            _collect_project_ids(item, candidates)


def _write_json_atomic(path: Path, payload: object) -> None:
    _write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(text)
        atomic_replace_path(temporary_path, path)
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
