# Provider secret codec.
# The desktop application is Windows-only, so provider API keys use Windows DPAPI.

from __future__ import annotations

import base64
from binascii import Error as BinasciiError
import ctypes
import os
from ctypes import POINTER, Structure, byref, cast
from ctypes.wintypes import BOOL, BYTE, DWORD, LPCWSTR


_WINDOWS_DPAPI_PREFIX = "win-dpapi-user-v1:"


def encrypt_secret(secret_value: str) -> str | None:
    normalized = secret_value.strip()
    if not normalized:
        return None
    if os.name != "nt":
        raise RuntimeError("API Key 加密仅支持 Windows。")
    try:
        protected = _windows_dpapi_protect(normalized.encode("utf-8"))
    except Exception:
        return None
    return f"{_WINDOWS_DPAPI_PREFIX}{_encode_base64(protected)}"


def decrypt_secret(ciphertext: str | None) -> str:
    if not ciphertext:
        raise ValueError("API Key 密文不能为空。")
    if not ciphertext.startswith(_WINDOWS_DPAPI_PREFIX):
        raise ValueError("API Key 密文格式无效。")
    if os.name != "nt":
        raise RuntimeError("API Key 解密仅支持 Windows。")
    encoded = ciphertext[len(_WINDOWS_DPAPI_PREFIX):]
    try:
        protected = _decode_base64(encoded)
        return _windows_dpapi_unprotect(protected).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("API Key 密文格式无效。") from exc


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
