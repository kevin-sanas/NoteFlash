"""Same-HWND blur for the isolated Qt preview, not a second inactive window.

SetWindowCompositionAttribute is an undocumented Windows API. A successful
return only means the request was accepted, not that visual acceptance passed.
"""
import ctypes
from ctypes import wintypes

from .windows import set_rounded_region


class AccentPolicy(ctypes.Structure):
    _fields_ = [(name, wintypes.DWORD) for name in
                ("state", "flags", "color", "animation")]


class CompositionData(ctypes.Structure):
    _fields_ = [("attribute", ctypes.c_int), ("data", ctypes.c_void_p),
                ("size", ctypes.c_size_t)]


class WindowBlur:
    def __init__(self, hwnd, mode="blur"):
        self.hwnd = hwnd
        self.mode = mode
        self.available = False
        self.error = None
        self._size = None
        self._setter = None
        state = {"none": 0, "blur": 3, "acrylic": 4}[mode]
        if not state:
            return
        if not hasattr(ctypes, "WinDLL"):
            self.error = "Native blur requires Windows"
            return
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._setter = getattr(self._user32, "SetWindowCompositionAttribute", None)
        if self._setter is None:
            self.error = "SetWindowCompositionAttribute is unavailable"
            return
        self._setter.argtypes = [wintypes.HWND, ctypes.POINTER(CompositionData)]
        self._setter.restype = wintypes.BOOL
        self._user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self._user32.GetWindowRect.restype = wintypes.BOOL
        # Qt paints the tint in its own RGBA surfaces. Acrylic additionally needs
        # a nonzero tint alpha; its format is AABBGGRR, not RGBA.
        policy = AccentPolicy(state, 0, 0x20FFEBD9 if state == 4 else 0, 0)
        data = CompositionData(19, ctypes.addressof(policy), ctypes.sizeof(policy))
        self.available = bool(self._setter(hwnd, ctypes.byref(data)))
        if not self.available:
            self.error = f"Native blur request failed (Win32 {ctypes.get_last_error()})"

    def sync(self, radius=14):
        if not self.available:
            return
        rectangle = wintypes.RECT()
        if self._user32.GetWindowRect(self.hwnd, ctypes.byref(rectangle)):
            size = (rectangle.right - rectangle.left, rectangle.bottom - rectangle.top)
            shape = (*size, radius)
            if shape != self._size:
                if set_rounded_region(self.hwnd, *shape):
                    self._size = shape
                    self.error = None
                else:
                    self.error = "The native rounded window region could not be applied"

    def hide(self):
        # There is no second HWND to hide. Qt owns this window's visibility.
        pass

    def close(self):
        if self.available:
            policy = AccentPolicy()
            data = CompositionData(19, ctypes.addressof(policy), ctypes.sizeof(policy))
            self._setter(self.hwnd, ctypes.byref(data))
            set_rounded_region(self.hwnd, 0, 0)
            self.available = False
