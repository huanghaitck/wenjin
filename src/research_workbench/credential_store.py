from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


class _Credential(ctypes.Structure):
    _fields_ = [
        ("flags", wintypes.DWORD), ("type", wintypes.DWORD),
        ("target_name", wintypes.LPWSTR), ("comment", wintypes.LPWSTR),
        ("last_written", _FileTime), ("blob_size", wintypes.DWORD),
        ("blob", ctypes.POINTER(ctypes.c_ubyte)), ("persist", wintypes.DWORD),
        ("attribute_count", wintypes.DWORD), ("attributes", ctypes.c_void_p),
        ("target_alias", wintypes.LPWSTR), ("user_name", wintypes.LPWSTR),
    ]


def _api() -> Any:
    if os.name != "nt":
        raise RuntimeError("Windows Credential Manager is only available on Windows")
    return ctypes.WinDLL("Advapi32.dll", use_last_error=True)


def save_credential(target: str, secret: str, user_name: str = "Wenjin") -> None:
    if not target.strip() or not secret:
        raise ValueError("credential target and secret are required")
    encoded = secret.encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    credential = _Credential()
    credential.type = 1
    credential.target_name = target
    credential.blob_size = len(encoded)
    credential.blob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.persist = 2
    credential.user_name = user_name
    api = _api()
    api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    if not api.CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def read_credential(target: str) -> str:
    if not target.strip() or os.name != "nt":
        return ""
    api = _api()
    pointer = ctypes.POINTER(_Credential)()
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_Credential)),
    ]
    api.CredReadW.restype = wintypes.BOOL
    if not api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return ""
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        value = ctypes.string_at(pointer.contents.blob, pointer.contents.blob_size)
        return value.decode("utf-16-le")
    finally:
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree(pointer)


def delete_credential(target: str) -> None:
    if not target.strip() or os.name != "nt":
        return
    api = _api()
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    if not api.CredDeleteW(target, 1, 0) and ctypes.get_last_error() != 1168:
        raise ctypes.WinError(ctypes.get_last_error())
