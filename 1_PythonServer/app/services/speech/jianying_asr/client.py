"""Cloud protocol only. No Tiance imports, credentials store, or model bridge."""
from __future__ import annotations

import asyncio
import zlib
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4

import httpx

from .common import ASRError, Budget
from .signing import api_headers, device_id, vod_headers

API_BASE = "https://lv-pc-api-sinfonlinec.ulikecam.com"
VOD_BASE = "https://vod.bytedanceapi.com"
UPLOAD_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36 Thea/1.0.1"
BLOCK_BYTES = 1024 * 1024
POLL_INTERVAL = 2.0


class HTTPFailure(ASRError):
    def __init__(self, stage: str, status: int):
        super().__init__("HTTP_ERROR", f"{stage}失败：HTTP {status}。")
        self.status = status


def chunks(path: Path, budget: Budget):
    with path.open("rb") as source:
        while block := source.read(BLOCK_BYTES):
            budget.remaining()
            yield block


async def upload_chunks(path: Path, budget: Budget):
    for block in chunks(path, budget):
        yield block
        await asyncio.sleep(0)


def crc32_file(path: Path, budget: Budget) -> str:
    crc = 0
    for block in chunks(path, budget):
        crc = zlib.crc32(block, crc)
    return f"{crc & 0xffffffff:08x}"


def required_string(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ASRError("INVALID_RESPONSE", f"服务返回缺少有效的 {key}。")
    return value


class JianyingClient:
    def __init__(self, budget: Budget, *, transport=None, tdid: str | None = None, http_options: dict | None = None, request_timeout=None):
        self.budget = budget
        self.tdid = tdid or device_id()
        self.http = httpx.AsyncClient(transport=transport, follow_redirects=False, **(http_options or {}))
        self.request_timeout = request_timeout
        # Each part owns its loop and connections. Keep the synchronous tool
        # interface, but make an entire network exchange cancellable at the
        # shared deadline (HTTPX read timeouts alone restart for each chunk).
        self._loop = asyncio.new_event_loop()
        self.warnings: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            self._loop.run_until_complete(self.http.aclose())
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            finally:
                self._loop.close()

    def request(self, method: str, url: str, stage: str, *, parse=True, **kwargs):
        # Errors intentionally omit URLs, upload tokens, signatures and auth bodies.
        try:
            remaining = self.budget.remaining()
            return self._loop.run_until_complete(asyncio.wait_for(
                self._request(method, url, stage, parse=parse, **kwargs), timeout=remaining))
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            raise ASRError("TIMEOUT", f"{stage}等待超时；已停止本次网络请求。") from exc
        except httpx.TransportError as exc:
            raise ASRError("NETWORK_ERROR", f"{stage}网络连接失败（{type(exc).__name__}）。") from exc

    async def _request(self, method: str, url: str, stage: str, *, parse=True, **kwargs):
        async with self.http.stream(method, url, timeout=self.request_timeout or self.budget.remaining(), **kwargs) as response:
            if not response.is_success:
                raise HTTPFailure(stage, response.status_code)
            if not parse:
                self.budget.remaining()
                return None
            body = bytearray()
            async for block in response.aiter_bytes():
                self.budget.remaining()
                body.extend(block)
            import json
            try:
                data = json.loads(body)
            except (ValueError, UnicodeDecodeError) as exc:
                raise ASRError("INVALID_RESPONSE", f"{stage}未返回有效 JSON。") from exc
        self.budget.remaining()
        if not isinstance(data, dict):
            raise ASRError("INVALID_RESPONSE", f"{stage}返回值不是对象。")
        return data

    def api(self, route: str, payload: dict, stage: str) -> dict:
        data = self.request("POST", API_BASE + route, stage,
                            headers=api_headers(route, self.tdid), json=payload)
        if str(data.get("ret")) != "0":
            message = str(data.get("errmsg") or "未提供错误说明")
            raise ASRError("UPSTREAM_ERROR", f"{stage}失败：{message}（ret={data.get('ret')}）。")
        return data

    def upload(self, path: Path) -> str:
        crc = crc32_file(path, self.budget)
        creds = self.api("/lv/v1/upload_sign", {"biz": "pc-recognition"}, "获取上传凭据").get("data")
        if not isinstance(creds, dict):
            raise ASRError("INVALID_RESPONSE", "上传凭据为空。")
        access, secret, token = [required_string(creds, k) for k in
                                 ("access_key_id", "secret_access_key", "session_token")]
        query = urlencode({"Action": "ApplyUploadInner", "FileSize": path.stat().st_size,
                           "FileType": "object", "IsInner": "1", "SpaceName": "lv-mac-recognition",
                           "Version": "2020-11-19", "s": "5y0udbjapi"})
        auth = self.request("GET", VOD_BASE + "/?" + query, "获取上传地址",
                            headers=vod_headers(access, secret, token, query))
        try:
            address = auth["Result"]["UploadAddress"]
            info = address["StoreInfos"][0]
            host = address["UploadHosts"][0]
            uri, upload_id, auth_token = [required_string(info, k) for k in ("StoreUri", "UploadID", "Auth")]
        except (KeyError, IndexError, TypeError) as exc:
            raise ASRError("INVALID_RESPONSE", "服务未返回完整的上传地址。") from exc
        parsed = urlsplit("https://" + str(host))
        if not parsed.hostname or parsed.netloc != host or parsed.path or parsed.username or parsed.password:
            raise ASRError("INVALID_RESPONSE", "服务返回了无效上传主机。")
        target = f"https://{host}/{quote(uri, safe='/')}"
        headers = {"User-Agent": UPLOAD_UA, "Authorization": auth_token, "Content-CRC32": crc}
        upload_headers = {**headers, "Content-Length": str(path.stat().st_size)}
        result = self.request("PUT", target, "上传音频", headers=upload_headers,
                              params={"partNumber": "1", "uploadID": upload_id},
                              content=upload_chunks(path, self.budget))
        if result.get("success") != 0:
            raise ASRError("UPLOAD_FAILED", "云端未确认音频上传成功。")
        checked = self.request("POST", target, "校验上传", headers=headers,
                               params={"uploadID": upload_id}, content=f"1:{crc}".encode())
        if checked.get("success", 0) != 0:
            raise ASRError("UPLOAD_FAILED", "云端音频完整性校验失败。")
        # The CRC POST finalizes this one-part upload. The upstream client's extra
        # full-body PUT returned HTTP 400 in live tests and is deliberately omitted.
        return uri

    def submit(self, uri: str) -> str:
        data = self.api("/lv/v1/audio_subtitle/submit", {
            "adjust_endtime": 200, "audio": uri, "caption_type": 2,
            "client_request_id": str(uuid4()), "max_lines": 1,
            "songs_info": [{"end_time": 6000, "id": "", "start_time": 0}], "words_per_line": 16,
        }, "提交识别")
        if not isinstance(data.get("data"), dict):
            raise ASRError("INVALID_RESPONSE", "提交成功响应中没有任务信息。")
        return required_string(data["data"], "id")

    def poll(self, task_id: str) -> dict:
        retries = 0
        warning_index = len(self.warnings)

        def note_retry(reason):
            nonlocal retries
            retries += 1
            message = f"结果查询已重试 {retries} 次，最近原因为 {reason}。"
            if len(self.warnings) == warning_index:
                self.warnings.append(message)
            else:
                self.warnings[warning_index] = message

        while True:
            self.budget.remaining()
            try:
                data = self.api("/lv/v1/audio_subtitle/query",
                                {"id": task_id, "pack_options": {"need_attribute": True}}, "查询识别结果")
            except HTTPFailure as exc:
                if exc.status != 429 and not 500 <= exc.status < 600:
                    raise
                note_retry(f"HTTP {exc.status}")
                self.budget.sleep(5)
                continue
            except ASRError as exc:
                if exc.code != "NETWORK_ERROR":
                    raise
                note_retry(exc.code)
                self.budget.sleep(5)
                continue
            if data.get("data") is None:
                self.budget.sleep(POLL_INTERVAL)
                continue
            if not isinstance(data["data"], dict) or not isinstance(data["data"].get("utterances"), list):
                raise ASRError("INVALID_RESPONSE", "识别结果缺少 utterances 列表，不能当作空白转录。")
            return data
