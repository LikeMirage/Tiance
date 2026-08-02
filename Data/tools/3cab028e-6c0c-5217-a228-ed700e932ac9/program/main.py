from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from tiance_runtime import run_tool


BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}
SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "iframe"}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}
USER_AGENT = "Tiance-Web-Material-Archiver/1.0"


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class FetchError(Exception):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    content_type: str
    truncated: bool


@dataclass(frozen=True)
class ArchiveOptions:
    fetch: bool
    save_html: bool
    extract_markdown: bool
    save_search_content: bool
    download_pdf_resources: bool
    deduplicate: bool
    max_items: int
    max_file_bytes: int
    request_timeout_seconds: int


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.skip_depth = 0
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if tag == "title":
            self.in_title = True
            return
        if self.skip_depth:
            return
        if tag in BLOCK_TAGS:
            self._append("\n")
        if tag == "li":
            self._append("- ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if tag == "title":
            self.in_title = False
            return
        if self.skip_depth:
            return
        if tag in BLOCK_TAGS:
            self._append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        self._append(data)

    def _append(self, text: str) -> None:
        if text:
            self.parts.append(text)

    def title(self) -> str:
        return normalize_spaces(" ".join(self.title_parts))

    def text(self) -> str:
        text = "".join(self.parts)
        lines = [normalize_spaces(line) for line in text.splitlines()]
        compact_lines: list[str] = []
        last_blank = True
        for line in lines:
            if not line:
                if not last_blank:
                    compact_lines.append("")
                last_blank = True
                continue
            compact_lines.append(line)
            last_blank = False
        return "\n".join(compact_lines).strip()


def ok(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": False, "error": f"{code}: {message}", "error_info": {"code": code, "message": message, "details": details or {}}, "warnings": []}


def workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def read_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def resolve_dir(value: Any, root: Path, default_relative: str) -> Path:
    raw = str(value or "").strip() or default_relative
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolError("PATH_OUTSIDE_WORKSPACE", "输出目录必须位于工作区内。", {"output_path": str(resolved), "workspace_root": str(root)}) from exc
    return resolved


def read_options(payload: dict[str, Any]) -> ArchiveOptions:
    return ArchiveOptions(
        fetch=read_bool(payload.get("fetch"), True),
        save_html=read_bool(payload.get("save_html"), True),
        extract_markdown=read_bool(payload.get("extract_markdown"), True),
        save_search_content=read_bool(payload.get("save_search_content"), True),
        download_pdf_resources=read_bool(payload.get("download_pdf_resources"), True),
        deduplicate=read_bool(payload.get("deduplicate"), True),
        max_items=read_int(payload.get("max_items"), 20, 1, 100),
        max_file_bytes=read_int(payload.get("max_file_bytes"), 52_428_800, 1024, 524_288_000),
        request_timeout_seconds=read_int(payload.get("request_timeout_seconds"), 30, 5, 300),
    )


def allocate_archive_dir(root: Path, payload: dict[str, Any]) -> tuple[Path, str | None]:
    output_root = resolve_dir(payload.get("output_root"), root, "web_materials")
    archive_name = sanitize_filename(str(payload.get("archive_name") or "").strip())
    if not archive_name:
        archive_name = datetime.now().strftime("archive_%Y%m%d_%H%M%S")
    archive_dir = output_root / archive_name
    warning = None
    if archive_dir.exists():
        base = archive_dir
        for index in range(2, 1000):
            candidate = base.with_name(f"{base.name}_{index}")
            if not candidate.exists():
                archive_dir = candidate
                warning = f"归档目录已存在，已改用 {archive_dir.name}。"
                break
        else:
            raise ToolError("OUTPUT_EXISTS", "无法为归档目录生成唯一名称。", {"output_root": str(output_root), "archive_name": archive_name})
    archive_dir.mkdir(parents=True, exist_ok=False)
    return archive_dir, warning


def collect_items(payload: dict[str, Any], options: ArchiveOptions) -> list[dict[str, Any]]:
    raw_items: list[Any] = []
    if payload.get("url"):
        raw_items.append({"url": payload.get("url")})
    if isinstance(payload.get("urls"), list):
        raw_items.extend({"url": item} for item in payload.get("urls") or [])
    if isinstance(payload.get("items"), list):
        raw_items.extend(payload.get("items") or [])
    search_result = payload.get("search_result")
    if isinstance(search_result, dict):
        data = search_result.get("data") if isinstance(search_result.get("data"), dict) else search_result
        results = data.get("results") if isinstance(data.get("results"), list) else []
        raw_items.extend(results)

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = normalize_item(raw)
        primary_url = item.get("url")
        resources = item.get("resources") if isinstance(item.get("resources"), list) else []
        if not primary_url and not resources and not item.get("provided_content"):
            continue
        dedupe_key = str(primary_url or item.get("title") or len(items)).strip().lower()
        if options.deduplicate and dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        items.append(item)
        if len(items) >= options.max_items:
            break
    if not items:
        raise ToolError("INVALID_ARGUMENT", "至少提供一个 URL、搜索结果条目或 search_result.results。")
    return items


def normalize_item(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {"url": raw}
    url = first_text(source, ["url", "link", "original", "serpapi_link"])
    title = first_text(source, ["title", "name", "question", "displayed_title"]) or title_from_url(url)
    provided_content = first_text(source, ["raw_content", "content", "snippet", "description", "summary"])
    resources = normalize_resources(source.get("resources"))
    return {
        "title": title,
        "url": url,
        "source": first_text(source, ["source", "section", "tool"]),
        "provided_content": provided_content,
        "resources": resources,
        "raw_item": compact_json_value(source),
    }


def first_text(source: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, dict):
            for nested_key in ("text", "title", "name", "link", "url"):
                nested = value.get(nested_key)
                if nested:
                    return str(nested).strip()
    return ""


def normalize_resources(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    resources: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        url = first_text(item, ["link", "url"])
        if not url:
            continue
        resources.append(
            {
                "url": url,
                "title": first_text(item, ["title", "name"]) or title_from_url(url),
                "file_format": first_text(item, ["file_format", "format", "type"]),
            }
        )
    return resources


def compact_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"raw_content"}:
                compact[key] = truncate_string(str(item or ""), 2000)
            else:
                compact[key] = compact_json_value(item)
        return compact
    if isinstance(value, list):
        return [compact_json_value(item) for item in value[:50]]
    if isinstance(value, str):
        return truncate_string(value, 2000)
    return value


def process_item(
    item: dict[str, Any],
    index: int,
    archive_dir: Path,
    options: ArchiveOptions,
) -> dict[str, Any]:
    item_title = str(item.get("title") or f"item_{index}")
    item_dir = archive_dir / "items" / f"{index:03d}_{sanitize_filename(item_title)[:80]}"
    item_dir.mkdir(parents=True, exist_ok=False)
    files_dir = item_dir / "files"
    files: list[dict[str, Any]] = []
    item_warnings: list[str] = []
    errors: list[dict[str, Any]] = []
    fetched: dict[str, Any] | None = None
    saved_at = datetime.now().isoformat(timespec="seconds")

    if options.save_search_content and item.get("provided_content"):
        content_path = item_dir / "search_content.md"
        content_text = markdown_document(
            title=f"{item_title} - 搜索内容",
            url=str(item.get("url") or ""),
            body=str(item.get("provided_content") or ""),
            saved_at=saved_at,
        )
        write_text(content_path, content_text)
        files.append(file_record(content_path, archive_dir, "search_content"))

    primary_url = str(item.get("url") or "").strip()
    if primary_url and options.fetch:
        try:
            fetch_result = fetch_url(primary_url, options)
            fetched = {
                "url": fetch_result.url,
                "final_url": fetch_result.final_url,
                "status_code": fetch_result.status_code,
                "content_type": fetch_result.content_type,
                "truncated": fetch_result.truncated,
            }
            files.extend(save_fetched_primary(fetch_result, item_title, item_dir, archive_dir, options, item_warnings))
        except FetchError as exc:
            errors.append({"url": primary_url, "message": exc.message, "details": exc.details})

    if options.fetch and options.download_pdf_resources:
        for resource_index, resource in enumerate(item.get("resources") or [], start=1):
            resource_url = str(resource.get("url") or "").strip()
            if not resource_url:
                continue
            if not looks_like_pdf_resource(resource):
                continue
            try:
                fetch_result = fetch_url(resource_url, options)
                files_dir.mkdir(exist_ok=True)
                filename = make_download_filename(resource.get("title") or item_title, resource_url, ".pdf")
                target = unique_path(files_dir / f"{resource_index:02d}_{filename}")
                target.write_bytes(fetch_result.body)
                files.append(file_record(target, archive_dir, "pdf_resource", fetch_result))
            except FetchError as exc:
                errors.append({"url": resource_url, "message": exc.message, "details": exc.details})

    metadata = {
        "index": index,
        "title": item_title,
        "url": primary_url,
        "source": item.get("source"),
        "saved_at": saved_at,
        "fetched": fetched,
        "files": files,
        "errors": errors,
        "warnings": item_warnings,
        "resources": item.get("resources") or [],
        "original_item": item.get("raw_item"),
    }
    write_json(item_dir / "metadata.json", metadata)
    return {
        "index": index,
        "title": item_title,
        "url": primary_url,
        "item_dir": relative_path(item_dir, archive_dir),
        "files": files,
        "errors": errors,
        "warnings": item_warnings,
        "ok": not errors or bool(files),
    }


def fetch_url(url: str, options: ArchiveOptions) -> FetchResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise FetchError("只支持 http/https URL。", {"url": url})
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urlopen(request, timeout=options.request_timeout_seconds) as response:
            status_code = int(getattr(response, "status", response.getcode()))
            headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
            body, truncated = read_limited(response, options.max_file_bytes)
            content_type = headers.get("content-type", "")
            return FetchResult(
                url=url,
                final_url=str(response.geturl()),
                status_code=status_code,
                headers=headers,
                body=body,
                content_type=content_type,
                truncated=truncated,
            )
    except HTTPError as exc:
        detail_body = ""
        try:
            detail_body = exc.read(500).decode("utf-8", errors="replace")
        except Exception:
            detail_body = ""
        raise FetchError(f"HTTP {exc.code}。", {"url": url, "response_preview": detail_body}) from exc
    except URLError as exc:
        raise FetchError(f"请求失败：{exc.reason}", {"url": url}) from exc
    except TimeoutError as exc:
        raise FetchError("请求超时。", {"url": url, "timeout_seconds": options.request_timeout_seconds}) from exc


def read_limited(response: Any, max_file_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    truncated = False
    while True:
        chunk = response.read(min(65_536, max_file_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_file_bytes:
            allowed = len(chunk) - (total - max_file_bytes)
            if allowed > 0:
                chunks.append(chunk[:allowed])
            truncated = True
            break
        chunks.append(chunk)
    return b"".join(chunks), truncated


def save_fetched_primary(
    fetch_result: FetchResult,
    item_title: str,
    item_dir: Path,
    archive_dir: Path,
    options: ArchiveOptions,
    warnings: list[str],
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    content_kind = classify_content(fetch_result)
    if fetch_result.truncated:
        warnings.append(f"{fetch_result.url} 超过单文件大小上限，已保存截断内容。")

    if content_kind == "html":
        if options.save_html:
            raw_path = item_dir / "raw.html"
            raw_path.write_bytes(fetch_result.body)
            files.append(file_record(raw_path, archive_dir, "raw_html", fetch_result))
        if options.extract_markdown:
            html_text, encoding = decode_response_text(fetch_result)
            title, text = extract_html_text(html_text)
            body = text or "(未提取到正文)"
            markdown_path = item_dir / "content.md"
            markdown = markdown_document(
                title=title or item_title,
                url=fetch_result.final_url,
                body=body,
                saved_at=datetime.now().isoformat(timespec="seconds"),
                extra={"encoding": encoding},
            )
            write_text(markdown_path, markdown)
            files.append(file_record(markdown_path, archive_dir, "content_markdown"))
        return files

    if content_kind == "pdf":
        files_dir = item_dir / "files"
        files_dir.mkdir(exist_ok=True)
        target = unique_path(files_dir / make_download_filename(item_title, fetch_result.final_url, ".pdf"))
        target.write_bytes(fetch_result.body)
        files.append(file_record(target, archive_dir, "pdf", fetch_result))
        return files

    if content_kind == "text":
        text, encoding = decode_response_text(fetch_result)
        raw_path = item_dir / raw_text_filename(fetch_result)
        write_text(raw_path, text)
        files.append(file_record(raw_path, archive_dir, "raw_text", fetch_result))
        if options.extract_markdown:
            markdown_path = item_dir / "content.md"
            write_text(
                markdown_path,
                markdown_document(
                    title=item_title,
                    url=fetch_result.final_url,
                    body=text,
                    saved_at=datetime.now().isoformat(timespec="seconds"),
                    extra={"encoding": encoding},
                ),
            )
            files.append(file_record(markdown_path, archive_dir, "content_markdown"))
        return files

    files_dir = item_dir / "files"
    files_dir.mkdir(exist_ok=True)
    target = unique_path(files_dir / make_download_filename(item_title, fetch_result.final_url, extension_from_fetch(fetch_result)))
    target.write_bytes(fetch_result.body)
    files.append(file_record(target, archive_dir, "binary", fetch_result))
    return files


def classify_content(fetch_result: FetchResult) -> str:
    content_type = (fetch_result.content_type or "").split(";", 1)[0].strip().lower()
    path = urlparse(fetch_result.final_url or fetch_result.url).path.lower()
    if content_type == "application/pdf" or path.endswith(".pdf") or fetch_result.body.startswith(b"%PDF"):
        return "pdf"
    if content_type in {"text/html", "application/xhtml+xml"} or path.endswith((".html", ".htm")):
        return "html"
    if content_type.startswith("text/") or content_type in {"application/json", "application/xml", "application/rss+xml"}:
        return "text"
    return "binary"


def decode_response_text(fetch_result: FetchResult) -> tuple[str, str]:
    charset = charset_from_content_type(fetch_result.content_type)
    candidates = [charset] if charset else []
    candidates.extend(["utf-8-sig", "utf-8", "gb18030"])
    seen: set[str] = set()
    for encoding in candidates:
        if not encoding or encoding in seen:
            continue
        seen.add(encoding)
        try:
            return fetch_result.body.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
        except LookupError:
            continue
    return fetch_result.body.decode("utf-8", errors="replace"), "utf-8-replace"


def charset_from_content_type(content_type: str) -> str:
    for part in content_type.split(";"):
        if "charset=" in part.lower():
            return part.split("=", 1)[1].strip().strip('"')
    return ""


def extract_html_text(html_text: str) -> tuple[str, str]:
    parser = TextExtractor()
    parser.feed(html_text)
    parser.close()
    return parser.title(), parser.text()


def markdown_document(
    *,
    title: str,
    url: str,
    body: str,
    saved_at: str,
    extra: dict[str, Any] | None = None,
) -> str:
    lines = [
        f"# {title or 'Untitled'}",
        "",
        f"- URL: {url}" if url else "- URL: ",
        f"- Saved at: {saved_at}",
    ]
    for key, value in (extra or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Content", "", body.strip(), ""])
    return "\n".join(lines)


def looks_like_pdf_resource(resource: dict[str, Any]) -> bool:
    file_format = str(resource.get("file_format") or "").strip().lower()
    url = str(resource.get("url") or "").strip().lower()
    return file_format == "pdf" or ".pdf" in urlparse(url).path.lower()


def write_summary(archive_dir: Path, records: list[dict[str, Any]], warnings: list[str]) -> Path:
    lines = [
        "# Web Materials Archive",
        "",
        f"- Created at: {datetime.now().isoformat(timespec='seconds')}",
        f"- Items: {len(records)}",
        f"- Successful items: {sum(1 for item in records if item.get('ok'))}",
        f"- Failed items: {sum(1 for item in records if item.get('errors') and not item.get('files'))}",
        "",
        "## Items",
        "",
    ]
    for record in records:
        title = str(record.get("title") or f"item {record.get('index')}")
        item_dir = str(record.get("item_dir") or "")
        files = record.get("files") if isinstance(record.get("files"), list) else []
        lines.append(f"{record.get('index')}. [{title}]({item_dir}/metadata.json)")
        if record.get("url"):
            lines.append(f"   - URL: {record['url']}")
        for file in files[:10]:
            rel = file.get("relative_path") if isinstance(file, dict) else None
            kind = file.get("kind") if isinstance(file, dict) else None
            if rel:
                lines.append(f"   - {kind}: {rel}")
        if record.get("errors"):
            lines.append(f"   - Errors: {len(record['errors'])}")
        lines.append("")
    if warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
    summary_path = archive_dir / "_summary.md"
    write_text(summary_path, "\n".join(lines).rstrip() + "\n")
    return summary_path


def file_record(path: Path, archive_dir: Path, kind: str, fetch_result: FetchResult | None = None) -> dict[str, Any]:
    data = path.read_bytes()
    record = {
        "kind": kind,
        "path": str(path),
        "relative_path": relative_path(path, archive_dir),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    if fetch_result is not None:
        record.update(
            {
                "url": fetch_result.url,
                "final_url": fetch_result.final_url,
                "status_code": fetch_result.status_code,
                "content_type": fetch_result.content_type,
                "truncated": fetch_result.truncated,
            }
        )
    return record


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def truncate_string(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...[truncated]"


def sanitize_filename(value: str) -> str:
    text = normalize_spaces(value)
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"_+", "_", text).strip(" ._")
    if not text:
        text = "untitled"
    if text.upper() in WINDOWS_RESERVED_NAMES:
        text = f"{text}_file"
    return text[:120]


def title_from_url(url: str) -> str:
    parsed = urlparse(url or "")
    path = unquote(parsed.path.rstrip("/").split("/")[-1])
    return path or parsed.netloc or "untitled"


def make_download_filename(title: Any, url: str, default_extension: str) -> str:
    parsed = urlparse(url)
    path_name = unquote(Path(parsed.path).name)
    extension = Path(path_name).suffix or default_extension
    base = Path(path_name).stem if path_name and "." in path_name else sanitize_filename(str(title or "download"))
    return sanitize_filename(base) + extension


def raw_text_filename(fetch_result: FetchResult) -> str:
    content_type = (fetch_result.content_type or "").split(";", 1)[0].strip().lower()
    if content_type == "application/json":
        return "raw.json"
    if content_type in {"application/xml", "application/rss+xml"}:
        return "raw.xml"
    return "raw.txt"


def extension_from_fetch(fetch_result: FetchResult) -> str:
    content_type = (fetch_result.content_type or "").split(";", 1)[0].strip().lower()
    extension = mimetypes.guess_extension(content_type) if content_type else None
    return extension or Path(urlparse(fetch_result.final_url or fetch_result.url).path).suffix or ".bin"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise ToolError("OUTPUT_EXISTS", "无法生成唯一文件名。", {"path": str(path)})


def run(payload: dict[str, Any]) -> dict[str, Any]:
    archive_dir: Path | None = None
    try:
        root = workspace_root()
        options = read_options(payload)
        archive_dir, archive_warning = allocate_archive_dir(root, payload)
        warnings: list[str] = []
        if archive_warning:
            warnings.append(archive_warning)
        items = collect_items(payload, options)
        records = [
            process_item(item, index, archive_dir, options)
            for index, item in enumerate(items, start=1)
        ]
        summary_path = write_summary(archive_dir, records, warnings)
        metadata = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "archive_dir": str(archive_dir),
            "items": records,
            "warnings": warnings,
            "options": {
                "fetch": options.fetch,
                "save_html": options.save_html,
                "extract_markdown": options.extract_markdown,
                "save_search_content": options.save_search_content,
                "download_pdf_resources": options.download_pdf_resources,
                "max_items": options.max_items,
                "max_file_bytes": options.max_file_bytes,
                "request_timeout_seconds": options.request_timeout_seconds,
            },
        }
        write_json(archive_dir / "metadata.json", metadata)
        failed_count = sum(1 for item in records if item.get("errors") and not item.get("files"))
        file_count = sum(len(item.get("files") or []) for item in records)
        return ok(
            f"网页资料保存完成：{len(records)} 条资料，生成 {file_count} 个文件，失败 {failed_count} 条。",
            {
                "archive_dir": str(archive_dir),
                "summary_path": str(summary_path),
                "metadata_path": str(archive_dir / "metadata.json"),
                "item_count": len(records),
                "file_count": file_count,
                "failed_count": failed_count,
                "items": records,
            },
            warnings,
        )
    except ToolError as exc:
        if archive_dir and archive_dir.exists():
            shutil.rmtree(archive_dir, ignore_errors=True)
        return fail(exc.code, exc.message, exc.details)
    except Exception as exc:
        if archive_dir and archive_dir.exists():
            shutil.rmtree(archive_dir, ignore_errors=True)
        return fail("UNEXPECTED_ERROR", str(exc) or exc.__class__.__name__)


if __name__ == "__main__":
    run_tool(run)
