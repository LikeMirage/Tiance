from app.core.errors import BadRequestError
from app.infra.secrets import decrypt_secret, encrypt_secret
from .navigation import COMMANDS
from .telegram_transport import TelegramTransport, TelegramError


async def validate_configuration(old, *, token, enabled, api_base):
    saved_token = ''
    if old.get('token') and not token.strip():
        try:
            saved_token = decrypt_secret(old['token'])
        except Exception:
            if enabled:
                raise BadRequestError('无法读取已保存的 Token，请重新填写。') from None
    token = token.strip() or saved_token
    if enabled and not token:
        raise BadRequestError('请填写 Bot Token。')
    config = dict(old, enabled=enabled, api_base=api_base.rstrip('/'))
    if token and (enabled or token != saved_token or api_base != old.get('api_base')):
        try:
            transport = TelegramTransport(token, api_base)
            bot = await transport.call('getMe')
            if (await transport.call('getWebhookInfo')).get('url'):
                raise BadRequestError('这个机器人已有 Webhook。请先在原服务中解除，再连接天策。')
            await transport.call('setMyCommands', {'commands':[{'command':c,'description':d} for c,d in COMMANDS]})
        except (TelegramError, ValueError) as exc:
            error = BadRequestError(str(exc))
            error.error_type = getattr(exc, 'error_type', None) or type(exc).__name__
            error.http_status = getattr(exc, 'http_status', None)
            raise error from None
        encrypted = encrypt_secret(token)
        if not encrypted:
            raise BadRequestError('Token 加密保存失败，原配置未变更。')
        config.update(token=encrypted, bot={k:bot[k] for k in ('id','username','first_name') if k in bot})
    return config
