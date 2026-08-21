# 异常处理模块
# 定义应用级异常层次结构和 FastAPI 异常处理器，统一 JSON 错误响应格式

from typing import Any

import httpx
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

HTTP_422_UNPROCESSABLE_ENTITY = 422


class AppError(Exception):
    """应用级异常基类，携带状态码、错误码和可选的详细信息"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "app_error",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


class BadRequestError(AppError):
    """400 错误：请求参数无效"""

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(
            message,
            code="bad_request",
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details,
        )


class NotFoundError(AppError):
    """404 错误：资源不存在"""

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(
            message,
            code="not_found",
            status_code=status.HTTP_404_NOT_FOUND,
            details=details,
        )


class ConflictError(AppError):
    """409 错误：资源状态冲突"""

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(
            message,
            code="conflict",
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class UpstreamProviderError(AppError):
    """502 错误：上游 LLM 供应商返回异常"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "upstream_provider_error",
        details: Any = None,
    ) -> None:
        super().__init__(
            message,
            code=code,
            status_code=status.HTTP_502_BAD_GATEWAY,
            details=details,
        )


def upstream_http_error_message(error: httpx.HTTPStatusError) -> str:
    """Return the provider response body unchanged, or the local HTTP exception."""

    response_text = _safe_response_text(error.response)
    return response_text if response_text else local_exception_message(error)


def local_exception_message(error: Exception) -> str:
    """Preserve the local exception text, or its concrete type when text is empty."""

    return str(error) or type(error).__name__


def to_upstream_provider_error(error: httpx.HTTPStatusError) -> UpstreamProviderError:
    return UpstreamProviderError(
        upstream_http_error_message(error),
        code="upstream_http_error",
        details={"upstream_status_code": error.response.status_code},
    )


def format_upstream_http_error(error: httpx.HTTPStatusError) -> str:
    """Return the original provider response body without business interpretation."""

    return upstream_http_error_message(error)


def _safe_response_text(response: httpx.Response) -> str:
    try:
        return response.text
    except httpx.ResponseNotRead:
        return ""


def register_exception_handlers(application) -> None:
    """向 FastAPI 应用注册所有自定义异常处理器"""

    application.add_exception_handler(AppError, app_error_handler)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return _error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else _default_http_message(exc.status_code)
    return _error_response(
        status_code=exc.status_code,
        code=_http_error_code(exc.status_code),
        message=message,
        details=None if isinstance(exc.detail, str) else exc.detail,
        headers=exc.headers,
    )


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
        code="request_validation_error",
        message="请求参数无效。",
        details=exc.errors(),
    )


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "detail": message,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if details is not None:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def _http_error_code(status_code: int) -> str:
    if status_code == status.HTTP_404_NOT_FOUND:
        return "not_found"
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "unauthorized"
    if status_code == status.HTTP_403_FORBIDDEN:
        return "forbidden"
    if status_code == status.HTTP_409_CONFLICT:
        return "conflict"
    if status_code == HTTP_422_UNPROCESSABLE_ENTITY:
        return "request_validation_error"
    if status_code >= 500:
        return "server_error"
    return "request_error"


def _default_http_message(status_code: int) -> str:
    if status_code == status.HTTP_404_NOT_FOUND:
        return "资源不存在。"
    if status_code == HTTP_422_UNPROCESSABLE_ENTITY:
        return "请求参数无效。"
    if status_code >= 500:
        return "服务器内部错误。"
    return "请求处理失败。"
