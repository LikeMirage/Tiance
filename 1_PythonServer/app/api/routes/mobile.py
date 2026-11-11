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


@router.post('/authorization')
async def platform_authorization(payload: Authorization):
    return await get_mobile_service().authorize(payload.peer, payload.allowed)


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


@router.post("/telegram/authorization")
async def telegram_authorization(payload: Authorization):
    return await get_mobile_service().authorize(payload.peer, payload.allowed)


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
