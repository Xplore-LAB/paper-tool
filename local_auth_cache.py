"""Remembered Zotero keys, encrypted for the current Windows user only."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path

CACHE = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.cache') / 'paper-tool' / 'auth'

class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

def crypt(data, decrypt=False):
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    api = ctypes.WinDLL('crypt32', use_last_error=True)
    function = api.CryptUnprotectData if decrypt else api.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))

def path_for(server_id):
    return CACHE / (hashlib.sha256(server_id.encode()).hexdigest() + '.dpapi')

def load(server_id):
    if os.name != 'nt':
        return ''
    try:
        return crypt(path_for(server_id).read_bytes(), True).decode()
    except (OSError, ValueError, UnicodeError):
        return ''

def save(server_id, key):
    if os.name == 'nt':
        encrypted = crypt(key.encode())
        CACHE.mkdir(parents=True, exist_ok=True)
        target = path_for(server_id)
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(encrypted)
        temporary.replace(target)
