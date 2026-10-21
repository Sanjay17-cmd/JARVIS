"""Windows-native window operations that avoid recreating QWidget handles."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


def set_topmost_in_place(hwnd: int, enabled: bool) -> bool:
    """Change z-order without changing Qt window flags or virtual-desktop ownership."""
    if os.name != "nt":
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    set_window_pos = user32.SetWindowPos
    set_window_pos.argtypes = (
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    )
    set_window_pos.restype = wintypes.BOOL
    insert_after = ctypes.c_void_p(-1 if enabled else -2)
    flags = 0x0001 | 0x0002 | 0x0010
    if not set_window_pos(
        wintypes.HWND(hwnd),
        insert_after,
        0,
        0,
        0,
        0,
        flags,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return True
