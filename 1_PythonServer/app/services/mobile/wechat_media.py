"""Stream iLink CDN media; preserve original bytes without whole-file copies."""
import asyncio
import base64
import hashlib
import secrets
import tempfile
from pathlib import Path
from urllib.parse import quote

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from app.core.errors import BadRequestError
from app.infra.http_client import get_shared_http_client, lease_http_client, get_http_timeout
from .wechat_transport import CDN, trusted_url


def decode_key(media):
    if media.get('aeskey'):
        key = bytes.fromhex(media['aeskey'])
    else:
        value = media.get('media', {}).get('aes_key')
        if not value:
            if media.get('kind') == 2:
                return None
            raise BadRequestError('微信文件缺少解密密钥，未保存损坏文件，请重新发送。')
        raw = base64.b64decode(value, validate=True)
        key = bytes.fromhex(raw.decode('ascii')) if len(raw) == 32 else raw
    if len(key) != 16:
        raise BadRequestError('微信文件解密密钥格式无效。')
    return key


async def download_file(media, destination):
    key = decode_key(media)
    info = media.get('media', {})
    param = info.get('encrypt_query_param')
    if not info.get('full_url') and not param:
        raise BadRequestError('微信文件没有下载地址。')
    url = trusted_url(info.get('full_url') or CDN + '/download?encrypted_query_param=' + quote(param, safe=''))
    temporary = destination.with_suffix(destination.suffix + '.part')
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor() if key else None
    unpadder = padding.PKCS7(128).unpadder() if key else None
    try:
        async with lease_http_client(get_shared_http_client()) as client:
            async with client.stream('GET', url, timeout=get_http_timeout(), follow_redirects=False) as response:
                if not response.is_success:
                    raise BadRequestError(f'微信文件下载失败 HTTP {response.status_code}。')
                with temporary.open('wb') as handle:
                    async for chunk in response.aiter_bytes(128 * 1024):
                        plain = unpadder.update(decryptor.update(chunk)) if key else chunk
                        await asyncio.to_thread(handle.write, plain)
                    if key:
                        handle.write(unpadder.update(decryptor.finalize()) + unpadder.finalize())
        await asyncio.to_thread(temporary.replace, destination)
    finally:
        temporary.unlink(missing_ok=True)


def encrypt_file(source, destination, key):
    digest = hashlib.md5()  # Wire integrity field, not an authentication primitive.
    cipher = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    pad = padding.PKCS7(128).padder()
    size = 0
    with source.open('rb') as incoming, destination.open('wb') as outgoing:
        while chunk := incoming.read(128 * 1024):
            digest.update(chunk)
            size += len(chunk)
            outgoing.write(cipher.update(pad.update(chunk)))
        outgoing.write(cipher.update(pad.finalize()) + cipher.finalize())
    return size, digest.hexdigest()


async def upload_file(transport, chat_id, path):
    key, filekey = secrets.token_bytes(16), secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix='tiance-wechat-') as directory:
        encrypted = Path(directory) / 'upload.bin'
        size, digest = await asyncio.to_thread(encrypt_file, path, encrypted, key)
        body = await transport.call('getuploadurl', {'filekey': filekey, 'media_type': 3, 'to_user_id': str(chat_id),
                    'rawsize': size, 'rawfilemd5': digest, 'filesize': encrypted.stat().st_size,
                    'no_need_thumb': True, 'aeskey': key.hex()})
        if not body.get('upload_full_url') and not body.get('upload_param'):
            raise BadRequestError('微信没有返回上传地址。')
        url = trusted_url(body.get('upload_full_url') or CDN + '/upload?encrypted_query_param=' + quote(body['upload_param'], safe='') + '&filekey=' + filekey)
        async def chunks():
            with encrypted.open('rb') as handle:
                while chunk := await asyncio.to_thread(handle.read, 128 * 1024):
                    yield chunk
        async with lease_http_client(get_shared_http_client()) as client:
            response = await client.post(url, content=chunks(), headers={'Content-Type': 'application/octet-stream',
                'Content-Length': str(encrypted.stat().st_size)}, timeout=get_http_timeout(), follow_redirects=False)
            if not response.is_success or not response.headers.get('x-encrypted-param'):
                raise BadRequestError(f'微信文件上传未完成 HTTP {response.status_code}。')
            param = response.headers['x-encrypted-param']
    return {'type': 4, 'file_item': {'file_name': path.name, 'len': str(size), 'media': {
        'encrypt_query_param': param, 'aes_key': base64.b64encode(key.hex().encode()).decode(), 'encrypt_type': 1}}}
