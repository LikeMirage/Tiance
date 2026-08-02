# Provider secret codec.
# Provider API keys are stored with a self-describing prefix:
# 1. Windows DPAPI when available.
# 2. OS keyring-backed AES-GCM when available on non-Windows platforms.
# 3. Local random-key AES-GCM when system protection is unavailable.
# Legacy unprotected SQLite payloads remain readable only for migration.

from __future__ import annotations

import base64
from binascii import Error as BinasciiError
import ctypes
import os
from pathlib import Path
import secrets
from ctypes import POINTER, Structure, byref, cast
from ctypes.wintypes import BOOL, BYTE, DWORD, LPCWSTR


_WINDOWS_DPAPI_PREFIX = "win-dpapi-user-v1:"
_SYSTEM_KEYRING_PREFIX = "system-keyring-v1:"
_LOCAL_FILE_KEY_PREFIX = "local-file-key-v1:"
_SQLITE_PLAIN_PREFIX = "sqlite-plain-v1:"
_AESGCM_NONCE_BYTES = 12
_SECRET_KEY_BYTES = 32
_SYSTEM_KEYRING_SERVICE = "Tiance API Key Store"
_SYSTEM_KEYRING_ACCOUNT = "provider-api-key-master-v1"
_LOCAL_KEY_FILENAME = "provider-api-key-local-v1.key"


def encrypt_secret(secret_value: str) -> str | None:
    normalized = secret_value.strip()
    if not normalized:
        return None

    for encoder in (
        _encrypt_with_system_protection,
        _encrypt_with_local_file_key,
    ):
        try:
            encoded = encoder(normalized)
        except Exception:
            continue
        if encoded:
            return encoded
    return None


def decrypt_secret(ciphertext: str | None) -> str:
    if not ciphertext:
        raise ValueError("API Key 密文不能为空。")
    if ciphertext.startswith(_WINDOWS_DPAPI_PREFIX):
        if os.name != "nt":
            raise RuntimeError("当前平台不支持 Windows DPAPI API Key 解密。")
        encoded = ciphertext[len(_WINDOWS_DPAPI_PREFIX):]
        try:
            protected = _decode_base64(encoded)
            return _windows_dpapi_unprotect(protected).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("API Key 密文格式无效。") from exc
    if ciphertext.startswith(_SYSTEM_KEYRING_PREFIX):
        key = _load_or_create_system_master_key()
        return _decrypt_aesgcm_payload(ciphertext, _SYSTEM_KEYRING_PREFIX, key)
    if ciphertext.startswith(_LOCAL_FILE_KEY_PREFIX):
        key = _load_or_create_local_file_key()
        return _decrypt_aesgcm_payload(ciphertext, _LOCAL_FILE_KEY_PREFIX, key)
    if ciphertext.startswith(_SQLITE_PLAIN_PREFIX):
        return _decode_unprotected_sqlite_payload(ciphertext)
    raise ValueError("API Key 密文格式无效。")


def _encrypt_with_system_protection(secret_value: str) -> str | None:
    if os.name == "nt":
        protected = _windows_dpapi_protect(secret_value.encode("utf-8"))
        return f"{_WINDOWS_DPAPI_PREFIX}{_encode_base64(protected)}"
    key = _load_or_create_system_master_key()
    return _encrypt_aesgcm_payload(secret_value, key, _SYSTEM_KEYRING_PREFIX)


def _encrypt_with_local_file_key(secret_value: str) -> str:
    key = _load_or_create_local_file_key()
    return _encrypt_aesgcm_payload(secret_value, key, _LOCAL_FILE_KEY_PREFIX)


def _encrypt_aesgcm_payload(secret_value: str, key: bytes, prefix: str) -> str:
    aesgcm = _create_aesgcm(key)
    nonce = secrets.token_bytes(_AESGCM_NONCE_BYTES)
    encrypted = aesgcm.encrypt(nonce, secret_value.encode("utf-8"), None)
    return f"{prefix}{_encode_base64(nonce + encrypted)}"


def _decrypt_aesgcm_payload(ciphertext: str, prefix: str, key: bytes) -> str:
    payload = _decode_base64(ciphertext[len(prefix):])
    if len(payload) <= _AESGCM_NONCE_BYTES:
        raise ValueError("API Key 密文格式无效。")
    nonce = payload[:_AESGCM_NONCE_BYTES]
    encrypted = payload[_AESGCM_NONCE_BYTES:]
    try:
        return _create_aesgcm(key).decrypt(nonce, encrypted, None).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("API Key 密文格式无效。") from exc


def _create_aesgcm(key: bytes):
    if len(key) != _SECRET_KEY_BYTES:
        raise ValueError("API Key 加密密钥格式无效。")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(key)


def _load_or_create_system_master_key() -> bytes:
    try:
        import keyring
    except Exception as exc:
        raise RuntimeError("系统安全存储不可用。") from exc

    encoded = keyring.get_password(_SYSTEM_KEYRING_SERVICE, _SYSTEM_KEYRING_ACCOUNT)
    if encoded:
        return _decode_key_material(encoded)
    key = secrets.token_bytes(_SECRET_KEY_BYTES)
    keyring.set_password(
        _SYSTEM_KEYRING_SERVICE,
        _SYSTEM_KEYRING_ACCOUNT,
        _encode_base64(key),
    )
    return key


def _load_or_create_local_file_key() -> bytes:
    key_path = _local_file_key_path()
    if key_path.exists():
        return _decode_key_material(key_path.read_text(encoding="ascii").strip())

    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(_SECRET_KEY_BYTES)
    encoded = _encode_base64(key)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        file_descriptor = os.open(key_path, flags, 0o600)
    except FileExistsError:
        return _decode_key_material(key_path.read_text(encoding="ascii").strip())
    with os.fdopen(file_descriptor, "w", encoding="ascii") as file:
        file.write(encoded)
        file.write("\n")
    return key


def _local_file_key_path() -> Path:
    from app.core.config import get_settings

    database_file = get_settings().app_database_file
    data_root = (
        database_file.parent.parent
        if database_file.parent.name.lower() == "db"
        else database_file.parent
    )
    return data_root / "secrets" / _LOCAL_KEY_FILENAME


def _decode_unprotected_sqlite_payload(ciphertext: str) -> str:
    try:
        return _decode_base64(ciphertext[len(_SQLITE_PLAIN_PREFIX):]).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("API Key 密文格式无效。") from exc


def _decode_key_material(encoded: str) -> bytes:
    key = _decode_base64(encoded)
    if len(key) != _SECRET_KEY_BYTES:
        raise ValueError("API Key 加密密钥格式无效。")
    return key


def _encode_base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode_base64(value: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (BinasciiError, UnicodeEncodeError) as exc:
        raise ValueError("API Key 密文格式无效。") from exc


if os.name == "nt":
    LPBYTE = POINTER(BYTE)

    class DATA_BLOB(Structure):
        _fields_ = [
            ("cbData", DWORD),
            ("pbData", LPBYTE),
        ]

    _crypt32 = ctypes.WinDLL("Crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)

    _crypt_protect_data = _crypt32.CryptProtectData
    _crypt_protect_data.argtypes = [
        POINTER(DATA_BLOB),
        LPCWSTR,
        POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        DWORD,
        POINTER(DATA_BLOB),
    ]
    _crypt_protect_data.restype = BOOL

    _crypt_unprotect_data = _crypt32.CryptUnprotectData
    _crypt_unprotect_data.argtypes = [
        POINTER(DATA_BLOB),
        POINTER(LPCWSTR),
        POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        DWORD,
        POINTER(DATA_BLOB),
    ]
    _crypt_unprotect_data.restype = BOOL

    _local_free = _kernel32.LocalFree
    _local_free.argtypes = [ctypes.c_void_p]
    _local_free.restype = ctypes.c_void_p


def _windows_dpapi_protect(data: bytes) -> bytes:
    input_buffer = ctypes.create_string_buffer(data)
    input_blob = DATA_BLOB(
        cbData=len(data),
        pbData=cast(input_buffer, LPBYTE),
    )
    output_blob = DATA_BLOB()
    if not _crypt_protect_data(byref(input_blob), None, None, None, None, 0, byref(output_blob)):
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        _local_free(output_blob.pbData)


def _windows_dpapi_unprotect(data: bytes) -> bytes:
    input_buffer = ctypes.create_string_buffer(data)
    input_blob = DATA_BLOB(
        cbData=len(data),
        pbData=cast(input_buffer, LPBYTE),
    )
    output_blob = DATA_BLOB()
    if not _crypt_unprotect_data(byref(input_blob), None, None, None, None, 0, byref(output_blob)):
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        _local_free(output_blob.pbData)
