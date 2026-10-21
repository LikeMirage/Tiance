from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class DeepSeekSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["search"]
    query: str = Field(min_length=1, max_length=128)
    count: int = Field(default=10, strict=True, ge=1, le=50)
    need_content: StrictBool = False
    ori_question: str | None = Field(default=None, min_length=1, max_length=128)
    localization: str = ""

    @field_validator("query", "ori_question")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("搜索词和原始问题不能全为空白")
        return value


class DeepSeekFetchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["fetch"]
    url: str = Field(min_length=1, max_length=8192)

    @field_validator("url")
    @classmethod
    def http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or any(char.isspace() for char in value)):
            raise ValueError("url 必须是没有账号密码的 HTTP/HTTPS 网址")
        return value


DeepSeekWebRequest = Annotated[
    DeepSeekSearchRequest | DeepSeekFetchRequest,
    Field(discriminator="action"),
]
