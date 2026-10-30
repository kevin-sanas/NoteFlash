"""Windows notification-area integration, isolated from the Tk event loop."""

import ctypes
import threading
from ctypes import wintypes


if hasattr(ctypes, 'WinDLL'):
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    WPARAM = ctypes.c_size_t
    LPARAM = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', WNDPROC),
                    ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                    ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
                    ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
                    ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]

    class GUID(ctypes.Structure):
        _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                    ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('hWnd', wintypes.HWND),
                    ('uID', wintypes.UINT), ('uFlags', wintypes.UINT),
                    ('uCallbackMessage', wintypes.UINT), ('hIcon', wintypes.HICON),
                    ('szTip', wintypes.WCHAR * 128), ('dwState', wintypes.DWORD),
                    ('dwStateMask', wintypes.DWORD), ('szInfo', wintypes.WCHAR * 256),
                    ('uTimeoutOrVersion', wintypes.UINT), ('szInfoTitle', wintypes.WCHAR * 64),
                    ('dwInfoFlags', wintypes.DWORD), ('guidItem', GUID),
                    ('hBalloonIcon', wintypes.HICON)]

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadIconW.restype = wintypes.HICON
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
    user32.TrackPopupMenu.restype = wintypes.UINT
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL


class TrayIcon:
    """Callbacks run on the tray thread; marshal them to the UI thread."""

    def __init__(self, callback):
        self.callback = callback
        self.error = None
        self._thread = None
        self._hwnd = None
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._added = False
        self._proc = None

    def start(self):
        if not hasattr(ctypes, 'WinDLL'):
            self.error = 'Windows notification area is unavailable on this platform'
            return False
        if self._thread and self._thread.is_alive():
            return self._added
        self.error = None
        self._ready.clear()
        self._stop_requested.clear()
        self._added = False
        self._thread = threading.Thread(target=self._run, name='NoteFlashTray', daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            self.error = 'Timed out starting notification icon'
            self._stop_requested.set()
            return False
        return self._added

    def stop(self):
        self._stop_requested.set()
        hwnd = self._hwnd
        if hwnd:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def _run(self):
        instance = kernel32.GetModuleHandleW(None)
        class_name = f'NoteFlashTray_{id(self)}'
        registered = False
        icon_data = None
        try:
            def wndproc(hwnd, msg, wparam, lparam):
                if msg == 0x8001:  # tray callback message
                    if lparam == 0x0203:  # WM_LBUTTONDBLCLK
                        self.callback('open')
                    elif lparam in (0x0205, 0x007B):  # right button / context menu
                        menu = user32.CreatePopupMenu()
                        if menu:
                            try:
                                for command, label in ((1, '打开'), (2, '设置'), (3, '退出')):
                                    user32.AppendMenuW(menu, 0, command, label)
                                point = wintypes.POINT()
                                user32.GetCursorPos(ctypes.byref(point))
                                user32.SetForegroundWindow(hwnd)
                                choice = user32.TrackPopupMenu(menu, 0x0100 | 0x0080,
                                                               point.x, point.y, 0, hwnd, None)
                                if choice in (1, 2, 3):
                                    self.callback({1: 'open', 2: 'settings', 3: 'quit'}[choice])
                            finally:
                                user32.DestroyMenu(menu)
                    return 0
                if msg == 0x0010:  # WM_CLOSE
                    user32.DestroyWindow(hwnd)
                    return 0
                if msg == 0x0002:  # WM_DESTROY
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._proc = WNDPROC(wndproc)  # Retain the native callback for the window lifetime.
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._proc
            wc.hInstance = instance
            wc.lpszClassName = class_name
            if not user32.RegisterClassW(ctypes.byref(wc)):
                raise ctypes.WinError(ctypes.get_last_error())
            registered = True
            hwnd = user32.CreateWindowExW(0, class_name, class_name, 0,
                                           0, 0, 0, 0, None, None, instance, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            self._hwnd = hwnd
            icon_data = NOTIFYICONDATAW()
            icon_data.cbSize = ctypes.sizeof(icon_data)
            icon_data.hWnd = hwnd
            icon_data.uID = 1
            icon_data.uFlags = 0x0001 | 0x0002 | 0x0004  # message, icon, tooltip
            icon_data.uCallbackMessage = 0x8001
            icon_data.hIcon = user32.LoadIconW(None, ctypes.cast(ctypes.c_void_p(32512), wintypes.LPCWSTR))
            icon_data.szTip = 'Note Flash'
            if not shell32.Shell_NotifyIconW(0, ctypes.byref(icon_data)):
                raise OSError('Shell_NotifyIconW could not add the notification icon')
            self._added = True
            self._ready.set()
            if self._stop_requested.is_set():
                user32.PostMessageW(hwnd, 0x0010, 0, 0)
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self.error = str(exc)
        finally:
            if self._added and icon_data is not None:
                shell32.Shell_NotifyIconW(2, ctypes.byref(icon_data))
            self._added = False
            if self._hwnd:
                user32.DestroyWindow(self._hwnd)
                self._hwnd = None
            if registered:
                user32.UnregisterClassW(class_name, instance)
            self._proc = None
            self._ready.set()


def set_rounded_corners(hwnd):
    """Request Windows 11 rounded corners when supported; return success."""
    if not hasattr(ctypes, 'WinDLL'):
        return False
    try:
        dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                               ctypes.c_void_p, wintypes.DWORD]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        preference = ctypes.c_int(2)  # DWMWCP_ROUND
        return dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(preference),
                                         ctypes.sizeof(preference)) == 0
    except OSError:
        return False


def apply_glass(hwnd, enabled=True):
    """Request the documented Windows 11 Acrylic system backdrop.

    Tk's black GDI backgrounds expose the extended DWM frame. Opaque text
    widgets remain opaque for reading. API success still needs visual checking.
    """
    import sys
    if sys.platform != 'win32' or sys.getwindowsversion().build < 22621:
        return {'enabled': False, 'reason': 'Windows 11 build 22621 or newer is required'}
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    wrapper = user32.GetAncestor(hwnd, 2) or hwnd  # Tk content HWND -> top-level frame.
    dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
    dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwm.DwmSetWindowAttribute.restype = ctypes.c_long
    class MARGINS(ctypes.Structure):
        _fields_ = [('left', ctypes.c_int), ('right', ctypes.c_int),
                    ('top', ctypes.c_int), ('bottom', ctypes.c_int)]
    dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(MARGINS)]
    dwm.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
    material = ctypes.c_int(3 if enabled else 1)  # DWMSBT_TRANSIENTWINDOW / NONE.
    backdrop = dwm.DwmSetWindowAttribute(wrapper, 38, ctypes.byref(material), ctypes.sizeof(material))
    # Keep GDI text outside the glass strip: extending through Tk controls
    # makes their non-alpha-aware glyphs disappear into the backdrop.
    margins = MARGINS(*([18] * 4 if enabled else [0] * 4))
    frame = dwm.DwmExtendFrameIntoClientArea(wrapper, ctypes.byref(margins))
    set_rounded_corners(wrapper)
    return {'enabled': bool(enabled and backdrop == 0 and frame == 0),
            'backdrop_hresult': backdrop, 'frame_hresult': frame, 'hwnd': int(wrapper)}


class AcrylicBackdrop:
    """A no-activate Acrylic window directly behind the Tk panel.

    Create, sync and close on the panel's Tk thread. Its normal Windows message
    pump also dispatches this native window; no additional thread is started.
    Keep the Tk foreground's native glass disabled and use constant alpha there.
    """

    def __init__(self, panel_hwnd):
        import sys
        self.available = False
        self.error = None
        self.panel_hwnd = None
        self._hwnd = None
        self._proc = None
        self._registered = False
        self._instance = None
        self._class_name = f'NoteFlashAcrylic_{id(self)}'
        self._native_result = {}
        self._shape_size = None
        if not hasattr(ctypes, 'WinDLL') or sys.getwindowsversion().build < 22621:
            self.error = 'Acrylic backdrop requires Windows 11 build 22621 or newer'
            return

        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.UnregisterClassW.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self.panel_hwnd = user32.GetAncestor(panel_hwnd, 2) or panel_hwnd
        if not user32.IsWindow(self.panel_hwnd):
            self.error = 'The panel window does not exist'
            return
        if user32.GetWindowThreadProcessId(self.panel_hwnd, None) != kernel32.GetCurrentThreadId():
            self.error = 'Create the Acrylic backdrop on the panel thread'
            return

        try:
            def wndproc(hwnd, message, wparam, lparam):
                if message == 0x0084:  # WM_NCHITTEST: pass through same-thread input.
                    return -1  # HTTRANSPARENT
                if message == 0x0021:  # WM_MOUSEACTIVATE
                    return 3  # MA_NOACTIVATE
                if message == 0x0010:  # WM_CLOSE: only the application owns its lifetime.
                    user32.ShowWindow(hwnd, 0)
                    return 0
                if message == 0x0082:  # WM_NCDESTROY: never post WM_QUIT to Tk.
                    self._hwnd = None
                    self.available = False
                return user32.DefWindowProcW(hwnd, message, wparam, lparam)

            self._instance = kernel32.GetModuleHandleW(None)
            self._proc = WNDPROC(wndproc)
            gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
            gdi32.GetStockObject.argtypes = [ctypes.c_int]
            gdi32.GetStockObject.restype = wintypes.HANDLE
            window_class = WNDCLASSW()
            window_class.lpfnWndProc = self._proc
            window_class.hInstance = self._instance
            # Black GDI pixels expose the extended DWM frame; no text is drawn
            # into this window, so GDI glyph alpha cannot affect the editor.
            window_class.hbrBackground = gdi32.GetStockObject(4)  # BLACK_BRUSH
            window_class.lpszClassName = self._class_name
            if not user32.RegisterClassW(ctypes.byref(window_class)):
                raise ctypes.WinError(ctypes.get_last_error())
            self._registered = True
            self._hwnd = user32.CreateWindowExW(
                0x00000080 | 0x08000000,  # WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                self._class_name, 'Note Flash Acrylic', 0x80000000,  # WS_POPUP, initially hidden.
                0, 0, 1, 1, None, None, self._instance, None,
            )
            if not self._hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
            dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                                ctypes.c_void_p, wintypes.DWORD]
            dwm.DwmSetWindowAttribute.restype = ctypes.c_long

            class MARGINS(ctypes.Structure):
                _fields_ = [('left', ctypes.c_int), ('right', ctypes.c_int),
                            ('top', ctypes.c_int), ('bottom', ctypes.c_int)]

            dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(MARGINS)]
            dwm.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
            material = ctypes.c_int(3)  # DWMSBT_TRANSIENTWINDOW: desktop Acrylic.
            backdrop = dwm.DwmSetWindowAttribute(self._hwnd, 38, ctypes.byref(material), ctypes.sizeof(material))
            frame = dwm.DwmExtendFrameIntoClientArea(self._hwnd, ctypes.byref(MARGINS(-1, -1, -1, -1)))
            self._native_result = {'backdrop_hresult': backdrop, 'frame_hresult': frame}
            if backdrop < 0 or frame < 0:
                raise OSError(f'Acrylic initialization failed: backdrop=0x{backdrop & 0xffffffff:08X}, '
                              f'frame=0x{frame & 0xffffffff:08X}')
            set_rounded_corners(self._hwnd)
            self.available = True
        except OSError as error:
            self.error = str(error)
            self.close()

    def sync(self):
        result = {**self._native_result, 'enabled': self.available, 'visible': False,
                  'hwnd': int(self._hwnd or 0), 'panel_hwnd': int(self.panel_hwnd or 0)}
        if not self.available or not self._hwnd:
            result['reason'] = self.error or 'The Acrylic backdrop is closed'
            return result
        if not user32.IsWindow(self.panel_hwnd):
            self.hide()
            self.error = 'The panel window no longer exists'
            result.update(enabled=False, reason=self.error)
            return result
        if not user32.IsWindowVisible(self.panel_hwnd) or user32.IsIconic(self.panel_hwnd):
            self.hide()
            return result
        rectangle = wintypes.RECT()
        if not user32.GetWindowRect(self.panel_hwnd, ctypes.byref(rectangle)):
            self.hide()
            self.error = str(ctypes.WinError(ctypes.get_last_error()))
            result.update(enabled=False, reason=self.error)
            return result
        geometry = [rectangle.left, rectangle.top,
                    rectangle.right - rectangle.left, rectangle.bottom - rectangle.top]
        # An ownerless non-topmost window inserted immediately after the panel
        # stays behind it without raising or activating the foreground panel.
        if not user32.SetWindowPos(self._hwnd, self.panel_hwnd, *geometry, 0x0010 | 0x0040):
            self.hide()
            self.error = str(ctypes.WinError(ctypes.get_last_error()))
            result.update(enabled=False, reason=self.error)
            return result
        size = tuple(geometry[2:])
        if size != self._shape_size:
            self._shape_size = size
            set_rounded_region(self.panel_hwnd, *size)
            set_rounded_region(self._hwnd, *size)
        self.error = None
        result.update(visible=True, rect=geometry)
        return result

    def hide(self):
        if self._hwnd:
            user32.ShowWindow(self._hwnd, 0)

    def close(self):
        if self._shape_size and self.panel_hwnd and user32.IsWindow(self.panel_hwnd):
            set_rounded_region(self.panel_hwnd, 0, 0)
            self._shape_size = None
        if self._hwnd:
            if not user32.DestroyWindow(self._hwnd):
                self.error = str(ctypes.WinError(ctypes.get_last_error()))
                return
            self._hwnd = None
        self.available = False
        if self._registered:
            if not user32.UnregisterClassW(self._class_name, self._instance):
                self.error = str(ctypes.WinError(ctypes.get_last_error()))
                return
            self._registered = False
        self._proc = None


def set_rounded_region(hwnd, width, height, radius=14):
    """Clip a layered window to visible rounded corners; zero size resets it."""
    gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
    gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
    gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject.restype = wintypes.BOOL
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int
    region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius * 2, radius * 2) if width and height else None
    success = bool(user32.SetWindowRgn(hwnd, region, True))
    if region and not success:
        gdi32.DeleteObject(region)
    return success


def prepare_panel_window(hwnd):
    """Hide the caption while retaining native resize edges and taskbar entry."""
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    wrapper = user32.GetAncestor(hwnd, 2) or hwnd
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    style = user32.GetWindowLongPtrW(wrapper, -16)
    user32.SetWindowLongPtrW(wrapper, -16, style & ~0x00C00000)
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos(wrapper, None, 0, 0, 0, 0, 0x0027)
    return int(wrapper)


def drag_panel(hwnd):
    user32.ReleaseCapture()
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
    user32.SendMessageW.restype = LRESULT
    user32.SendMessageW(hwnd, 0x00A1, 2, 0)


def is_startup_enabled(command: str) -> bool:
    """Return whether the current user's Run entry matches this command."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            value, kind = winreg.QueryValueEx(key, 'NoteFlash')
    except FileNotFoundError:
        return False
    return kind == winreg.REG_SZ and value == command


def set_startup_enabled(enabled: bool, command: str):
    """Set or remove the current user's Run entry when explicitly requested."""
    import winreg
    path = r'Software\Microsoft\Windows\CurrentVersion\Run'
    if enabled:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, 'NoteFlash', 0, winreg.REG_SZ, command)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, 'NoteFlash')
        except FileNotFoundError:
            pass
