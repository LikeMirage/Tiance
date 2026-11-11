from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from app.infra.http_client import get_shared_http_client, lease_http_client, get_http_timeout


class TelegramError(Exception):
    def __init__(self, message, retry_after=0, *, error_type=None, http_status=None):
        super().__init__(message)
        self.retry_after = retry_after
        self.error_type = error_type
        self.http_status = http_status


class TelegramSendError(TelegramError):
    def __init__(self, message, *, status, retry_after=0):
        super().__init__(message, retry_after)
        self.status = status


class _HideBotToken(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        record.msg = re.sub(r"(/(?:file/)?bot)[^/\s\"]+", r"\1<redacted>", message)
        record.args = ()
        return True


logging.getLogger("httpx").addFilter(_HideBotToken())


class TelegramTransport:
    def __init__(self, token: str, api_base="https://api.telegram.org"):
        parsed = urlsplit(api_base)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("Bot API 地址必须是 HTTP/HTTPS 服务地址，不能包含凭据或查询参数。")
        self.token = token
        self.base = api_base.rstrip("/")

    async def send_once(self, method, payload, *, document: Path | None = None):
        """No retry: a lost response does not prove that a file wasn't delivered.

        HTTPX multipart reads the file in bounded chunks; never read_bytes/base64.
        Upload inactivity timeouts follow the application's network settings.
        """
        from contextlib import nullcontext
        try:
            with document.open('rb') if document else nullcontext() as source:
                async with lease_http_client(get_shared_http_client()) as client:
                    kwargs = ({'data': payload, 'files': {'document': (document.name, source, 'application/octet-stream')}}
                              if document else {'json': payload})
                    response = await client.post(f'{self.base}/bot{self.token}/{method}',
                                                 timeout=get_http_timeout(), **kwargs)
                    data = response.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise TelegramSendError(f'Telegram 连接失败（{type(exc).__name__}），本次发送未建立连接。', status='not_sent') from None
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramSendError(f'Telegram 未确认发送结果（{type(exc).__name__}），请先检查目标聊天，勿直接重复发送。', status='unknown') from None
        except OSError:
            raise TelegramSendError('文件读取或上传中断，请核对目标聊天和文件访问权限。', status='unknown') from None
        if not isinstance(data, dict):
            raise TelegramSendError('Telegram 返回无法确认的发送结果，请先检查目标聊天。', status='unknown')
        if data.get('ok') is False:
            description = str(data.get('description', '发送失败')).replace(self.token, '<redacted>')
            raise TelegramSendError(f'Telegram：{description}', status='unknown' if response.status_code >= 500 else 'not_sent',
                                    retry_after=data.get('parameters', {}).get('retry_after', 0))
        result = data.get('result')
        if data.get('ok') is not True or not isinstance(result, dict) or 'message_id' not in result:
            raise TelegramSendError('Telegram 未返回消息 ID，请先检查目标聊天。', status='unknown')
        return result

    async def call(self, method: str, payload=None, *, poll=False):
        response = None
        try:
            async with lease_http_client(get_shared_http_client()) as client:
                # Long polling has its own HTTP wait, independent of AI execution.
                response = await client.post(f"{self.base}/bot{self.token}/{method}", json=payload or {},
                                             timeout=httpx.Timeout(40 if poll else 30, connect=10))
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramError(f"Telegram 连接失败（{type(exc).__name__}），请检查网络设置。",
                                error_type=type(exc).__name__, http_status=getattr(response, 'status_code', None)) from None
        if not data.get("ok"):
            description = str(data.get("description", "请求失败")).replace(self.token, "<redacted>")
            raise TelegramError(f"Telegram：{description}", data.get("parameters", {}).get("retry_after", 0),
                                http_status=response.status_code) from None
        return data["result"]

    async def download(self, file_id: str, destination: Path):
        info = await self.call("getFile", {"file_id": file_id})
        file_path = info.get("file_path")
        if not file_path:
            raise TelegramError("Telegram 未提供文件下载地址。")
        temporary = destination.with_suffix(destination.suffix + ".part")
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        try:
            # A local Bot API server may return its own absolute path. Only use
            # that shortcut when the explicitly configured server is local.
            if Path(file_path).is_absolute():
                if urlsplit(self.base).hostname not in {"localhost", "127.0.0.1", "::1"}:
                    raise TelegramError("Bot API 返回了服务端本地路径，天策无法从这台电脑读取。")
                import shutil
                await asyncio.to_thread(shutil.copyfile, file_path, temporary)
            else:
                if ".." in file_path.replace("\\", "/").split("/"):
                    raise TelegramError("Telegram 文件地址无效。")
                async with lease_http_client(get_shared_http_client()) as client:
                    async with client.stream("GET", f"{self.base}/file/bot{self.token}/{quote(file_path, safe='/')}",
                                             timeout=httpx.Timeout(60, connect=10)) as response:
                        response.raise_for_status()
                        with temporary.open("wb") as output:
                            async for chunk in response.aiter_bytes(128 * 1024):
                                await asyncio.to_thread(output.write, chunk)
            if info.get("file_size") is not None and temporary.stat().st_size != info["file_size"]:
                raise TelegramError("文件未下载完整，请重新发送。")
            await asyncio.to_thread(temporary.replace, destination)
        except httpx.HTTPError as exc:
            raise TelegramError(f"文件下载失败（{type(exc).__name__}），未提交给 AI。") from None
        finally:
            if temporary.exists():
                await asyncio.to_thread(temporary.unlink)


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name:
        return "file"
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    # Preserve the extension when a platform provides an unusually long name.
    suffix = Path(name).suffix[:20]
    return name if len(name) <= 150 else name[:150-len(suffix)] + suffix


def split_message(text: str, limit=3500):
    """Telegram counts UTF-16 units; never discard a long final response."""
    part, length = [], 0
    for char in text:
        size = 2 if ord(char) > 0xFFFF else 1
        if length + size > limit:
            yield "".join(part)
            part, length = [], 0
        part.append(char)
        length += size
    if part:
        yield "".join(part)
