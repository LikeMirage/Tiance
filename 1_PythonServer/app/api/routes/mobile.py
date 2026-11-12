from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import Literal
from app.services.mobile.service import get_mobile_service

router = APIRouter(prefix="/mobile", tags=["mobile"])


class TelegramSettings(BaseModel):
    connection_id: str | None = Field(default=None, max_length=256)
    token: str = Field(default="", max_length=512)
    enabled: bool
    api_base: str = Field(default="https://api.telegram.org", max_length=2048)


class Authorization(BaseModel):
    peer: str = Field(max_length=256)
    allowed: bool
    selected_connection_id: str | None = Field(default=None, max_length=256)


class PeerRemoval(BaseModel):
    peer: str = Field(min_length=1, max_length=256)
    selected_connection_id: str | None = Field(default=None, max_length=256)


class ConnectionRemoval(BaseModel):
    platform: Literal['telegram', 'feishu', 'wechat']
    connection_id: str = Field(min_length=1, max_length=256)


class MessageReceiptSettings(BaseModel):
    platform: Literal['telegram', 'feishu', 'wechat']
    connection_id: str = Field(min_length=1, max_length=256)
    message_receipt_enabled: bool


class AccessScopeSettings(BaseModel):
    connection_id: str = Field(min_length=1, max_length=256)
    allowed_collections: list[Literal['project', 'tool', 'knowledge', 'experience', 'role', 'provider', 'theme']] = Field(max_length=7)


class Preparation(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    payload: dict | None = None
    error: str | None = Field(default=None, max_length=4000)


class PlatformSettings(BaseModel):
    connection_id: str | None = Field(default=None, max_length=256)
    enabled: bool
    app_id: str = Field(default='', max_length=256)
    secret: str = Field(default='', max_length=1024)


class WeChatPin(BaseModel):
    pin: str = Field(min_length=4, max_length=12)


@router.post('/wechat/login')
async def wechat_login_start():
    return await get_mobile_service().wechat_login.start()


@router.post('/feishu/login')
async def feishu_login_start():
    return await get_mobile_service().feishu_login.start()


@router.get('/feishu/login/{login_id}')
async def feishu_login_status(login_id: str):
    return get_mobile_service().feishu_login.status(login_id)


@router.get('/wechat/login/{login_id}')
async def wechat_login_status(login_id: str):
    return get_mobile_service().wechat_login.status(login_id)


@router.post('/wechat/login/{login_id}/pin')
async def wechat_login_pin(login_id: str, payload: WeChatPin):
    get_mobile_service().wechat_login.submit_pin(login_id, payload.pin)
    return {'ok': True}


@router.get('/platform/{platform}')
async def platform_status(platform: Literal['feishu', 'wechat'], connection_id: str | None = Query(default=None, max_length=256)):
    return await get_mobile_service().status(connection_id, platform)


@router.put('/platform/{platform}')
async def platform_settings(platform: Literal['feishu', 'wechat'], payload: PlatformSettings):
    return await get_mobile_service().configure_platform(platform, **payload.model_dump())


@router.get('/platform/{platform}/logs')
async def platform_logs(platform: Literal['feishu', 'wechat'], connection_id: str | None = Query(default=None, max_length=256),
                        offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100)):
    return await get_mobile_service().activity(connection_id, offset, limit, platform)


@router.put('/platform/{platform}/access-scope')
async def platform_access_scope(platform: Literal['feishu', 'wechat'], payload: AccessScopeSettings):
    return await get_mobile_service().configure_scope(platform, **payload.model_dump())


@router.post('/authorization')
async def platform_authorization(payload: Authorization):
    return await get_mobile_service().authorize(**payload.model_dump())


@router.post('/peers/remove')
async def remove_peer(payload: PeerRemoval):
    return await get_mobile_service().remove_peer(**payload.model_dump())


@router.post('/connections/remove')
async def remove_connection(payload: ConnectionRemoval):
    return await get_mobile_service().remove_connection(**payload.model_dump())


@router.post('/connections/message-receipt')
async def message_receipt_settings(payload: MessageReceiptSettings):
    return await get_mobile_service().configure_message_receipt(**payload.model_dump())


@router.get("/telegram")
async def telegram_status(connection_id: str | None = Query(default=None, max_length=256)):
    return await get_mobile_service().status(connection_id)


@router.put("/telegram")
async def telegram_settings(payload: TelegramSettings):
    return await get_mobile_service().configure(**payload.model_dump())


@router.get("/telegram/logs")
async def telegram_logs(connection_id: str | None = Query(default=None, max_length=256),
                        offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100)):
    return await get_mobile_service().activity(connection_id, offset, limit)


@router.put('/telegram/access-scope')
async def telegram_access_scope(payload: AccessScopeSettings):
    return await get_mobile_service().configure_scope('telegram', **payload.model_dump())


@router.post("/telegram/authorization")
async def telegram_authorization(payload: Authorization):
    return await get_mobile_service().authorize(**payload.model_dump())


@router.get("/desktop/poll")
async def poll(owner: str = Query(min_length=1, max_length=100), after: int = Query(default=0, ge=0)):
    return await get_mobile_service().desktop.poll(owner, after)


@router.post("/desktop/release")
async def release(payload: Preparation):
    get_mobile_service().desktop.release(payload.owner)
    return {"ok": True}


@router.post("/desktop/{job_id}/prepare")
async def prepare(job_id: str, payload: Preparation):
    await get_mobile_service().desktop.prepare(payload.owner, job_id, payload.payload, payload.error)
    return {"ok": True}
