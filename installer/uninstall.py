"""Manifest-based per-user uninstall, with a ready-before-quit handshake."""

from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import queue

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from note_flash.data_paths import (CONFIG_NAME, DATA_MARKER, DATA_FILES, checked_path,
    clear_owned_data, read_data_marker, read_install_config)
from note_flash.core import _write_atomic


UNINSTALL_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
STAGE_MARKER = ".note-flash-uninstall-stage.json"


def registration_key(home: Path) -> str:
    identifier = hashlib.sha256(os.path.normcase(str(home)).encode("utf-8")).hexdigest()[:16]
    return UNINSTALL_ROOT + "\\NoteFlash-" + identifier


def remove_registration(home: Path):
    import winreg
    key_path = registration_key(home)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            location, _ = winreg.QueryValueEx(key, "InstallLocation")
        if os.path.normcase(location) != os.path.normcase(str(home)):
            raise ValueError("卸载注册信息不属于当前安装，未移除该项。")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
    except FileNotFoundError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Run",
                           0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
            command, kind = winreg.QueryValueEx(key, "NoteFlash")
            expected = subprocess.list2cmdline([str(home / "NoteFlash.exe")])
            if kind == winreg.REG_SZ and command == expected:
                winreg.DeleteValue(key, "NoteFlash")
    except FileNotFoundError:
        pass


def plan_uninstall(app_home: Path, *, clear_data=False) -> dict:
    home = checked_path(app_home)
    config = read_install_config(home)
    if config is None or not {"NoteFlash.exe", "Uninstall.exe", CONFIG_NAME}.issubset(config["files"]):
        raise ValueError("没有完整的安装清单；不能卸载便携目录或未知文件夹。")
    files = [checked_path(home / name) for name in config["files"] if name != CONFIG_NAME]
    if any(path.exists() and not path.is_file() for path in files):
        raise ValueError("安装清单中存在非普通文件，未执行卸载。")
    data = Path(config["data_dir"])
    if clear_data and data.exists():
        data = checked_path(data)
        read_data_marker(data)
        for name in DATA_FILES:
            path = checked_path(data / name)
            if path.exists() and not path.is_file():
                raise ValueError("设置记录不是普通文件，未执行卸载。")
    return {"home": home, "files": files, "data_dir": data, "config": config}


def _wait_for_processes(home: Path, wait_pid=None, ready=None, timeout=120):
    """Open process handles before ready; wait normally, never terminate the app."""
    if not hasattr(ctypes, "WinDLL"):
        raise OSError("卸载等待仅支持 Windows。")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.K32EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD)]
    kernel.K32EnumProcesses.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    capacity = 1024
    while True:
        identifiers = (wintypes.DWORD * capacity)()
        used = wintypes.DWORD()
        if not kernel.K32EnumProcesses(identifiers, ctypes.sizeof(identifiers), ctypes.byref(used)):
            raise ctypes.WinError(ctypes.get_last_error())
        if used.value < ctypes.sizeof(identifiers):
            break
        capacity *= 2
    handles = []
    try:
        expected = os.path.normcase(str(home / "NoteFlash.exe"))
        pids = set(identifiers[:used.value // ctypes.sizeof(wintypes.DWORD)])
        if wait_pid is not None:
            if type(wait_pid) is not int or wait_pid <= 0 or wait_pid == os.getpid():
                raise ValueError("等待退出的进程编号无效。")
            pids.add(wait_pid)
        for pid in pids - {0, os.getpid()}:
            handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)
            if not handle:
                if pid == wait_pid and ctypes.get_last_error() != 87:
                    raise ctypes.WinError(ctypes.get_last_error())
                continue
            name = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(name))
            match = kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length))
            if pid == wait_pid or (match and os.path.normcase(name.value) == expected):
                handles.append(handle)
            else:
                kernel.CloseHandle(handle)
        if ready is not None:
            ready()
        deadline = time.monotonic() + timeout
        for handle in handles:
            remaining = max(0, round((deadline - time.monotonic()) * 1000))
            outcome = kernel.WaitForSingleObject(handle, remaining)
            if outcome == 258:
                raise TimeoutError("Note Flash 尚未退出；请先正常退出，未删除安装文件。")
            if outcome != 0:
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)


class UninstallIncompleteError(OSError):
    def __init__(self, removed, remaining, error):
        self.removed, self.remaining = removed, remaining
        super().__init__(f"卸载未完成；已移除 {len(removed)} 个登记文件，清单已保留以便重试。\n{error}")


def uninstall_application(app_home: Path, *, clear_data=False, wait_pid=None,
                          register=True, ready=None) -> dict:
    plan = plan_uninstall(app_home, clear_data=clear_data)
    home, files = plan["home"], plan["files"]
    _wait_for_processes(home, wait_pid, ready)
    removed = []
    try:
        if clear_data:
            clear_owned_data(plan["data_dir"])
        for path in files:
            if path.exists():
                path.unlink()
                removed.append(path)
        if register and plan["config"].get("registered", False):
            remove_registration(home)
        (home / CONFIG_NAME).unlink()
        removed.append(home / CONFIG_NAME)
    except OSError as error:
        raise UninstallIncompleteError(removed, [path for path in files if path.exists()], error) from error
    directories = {parent for path in files for parent in path.parents if parent.is_relative_to(home)}
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()
    return {"uninstalled": True, "removed_files": len(removed), "clear_data": bool(clear_data),
            "data_dir": str(plan["data_dir"]), "unknown_files_preserved": True}


def _stage_helper(home: Path) -> Path:
    stage = Path(tempfile.mkdtemp(prefix="NoteFlash-uninstall-"))
    try:
        (stage / STAGE_MARKER).write_text('{"app":"NoteFlash","format":1}', encoding="utf-8")
        shutil.copyfile(home / "Uninstall.exe", stage / "Uninstall.exe")
    except OSError:
        _remove_stage(stage)
        raise
    return stage


def _remove_stage(stage: Path):
    if not (stage / STAGE_MARKER).exists():
        return
    for attempt in range(20):
        try:
            (stage / "Uninstall.exe").unlink(missing_ok=True)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)
    for name in ("ready.json", STAGE_MARKER):
        (stage / name).unlink(missing_ok=True)
    if not any(stage.iterdir()):
        stage.rmdir()


def cancel_uninstall(process):
    """Cancel only the helper started here, before the application quits."""
    if process.poll() is None:
        if os.name == "nt":
            # A onefile executable has a bootloader parent and a Python child.
            # Terminating only Popen's parent would leave the waiting worker live.
            outcome = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if outcome.returncode and process.poll() is None:
                raise OSError("卸载助手未能停止；应用保持运行，请稍后重试。")
        else:
            process.terminate()
        process.wait(timeout=5)
    stage = getattr(process, "_note_flash_stage", None)
    if stage is not None:
        _remove_stage(stage)


def start_uninstall(app_home: Path, *, clear_data=False, wait_pid=None,
                    register=True, timeout=8.0) -> subprocess.Popen:
    plan = plan_uninstall(app_home, clear_data=clear_data)
    home = plan["home"]
    if not (home / "Uninstall.exe").is_file():
        raise FileNotFoundError("卸载程序缺失；应用保持运行。")
    stage = _stage_helper(home)
    ready = stage / "ready.json"
    command = [str(stage / "Uninstall.exe"), "--uninstall", str(home),
               "--worker", "--confirmed", "--ready-file", str(ready)]
    if wait_pid is not None:
        command += ["--wait-pid", str(wait_pid)]
    if clear_data:
        command.append("--clear-data")
    if not register:
        command.append("--no-register")
    child = None
    try:
        child = subprocess.Popen(command, cwd=stage)
        child._note_flash_stage = stage
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if ready.exists():
                result = json.loads(ready.read_text(encoding="utf-8"))
                if result.get("ready") is True and result.get("install_dir") == str(home):
                    return child
                raise OSError(result.get("error", "卸载器未完成准备，应用保持运行。"))
            if child.poll() is not None:
                raise OSError("卸载器提前退出，应用保持运行。")
            time.sleep(0.03)
        raise TimeoutError("卸载器准备超时，应用保持运行。")
    except (OSError, ValueError):
        if child is not None:
            cancel_uninstall(child)
        else:
            _remove_stage(stage)
        raise


def _schedule_stage_cleanup():
    stage = Path(sys.executable).parent
    marker = stage / STAGE_MARKER
    if not getattr(sys, "frozen", False) or not marker.is_file():
        return
    if json.loads(marker.read_text(encoding="utf-8")) != {"app": "NoteFlash", "format": 1}:
        return
    quoted = lambda path: "'" + str(path).replace("'", "''") + "'"
    script = f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue\n"
    script += "for ($attempt = 0; $attempt -lt 20; $attempt++) {\n"
    script += f"  Remove-Item -LiteralPath {quoted(stage / 'Uninstall.exe')} -Force -ErrorAction SilentlyContinue\n"
    script += f"  if (-not (Test-Path -LiteralPath {quoted(stage / 'Uninstall.exe')})) {{ break }}\n"
    script += "  Start-Sleep -Milliseconds 250\n}\n"
    for name in ("ready.json", STAGE_MARKER):
        script += f"Remove-Item -LiteralPath {quoted(stage / name)} -Force -ErrorAction SilentlyContinue\n"
    script += f"Remove-Item -LiteralPath {quoted(stage)} -ErrorAction SilentlyContinue\n"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                      "-EncodedCommand", encoded], cwd=stage.parent,
                      creationflags=subprocess.CREATE_NO_WINDOW)


def _uninstall_gui(home: Path, register: bool):
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title("卸载 Note Flash")
    root.geometry("520x390")
    root.resizable(False, False)
    body = ttk.Frame(root, padding=24)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="卸载 Note Flash", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
    ttk.Label(body, text="程序文件将按安装清单移除。所有笔记和未知文件都会保留。\n"
              "如应用仍在运行，请先从托盘或宠物菜单正常退出。", wraplength=470).pack(anchor="w", pady=16)
    clear = tk.BooleanVar(value=False)
    ttk.Checkbutton(body, text="清除应用设置、标签会话与高亮记录（默认保留）", variable=clear).pack(anchor="w")
    ttk.Label(body, text="选中后将丢失软件内高亮，笔记正文仍保留。", foreground="#526780").pack(anchor="w", pady=6)
    status = tk.StringVar(value=str(home))
    ttk.Label(body, textvariable=status, wraplength=470).pack(anchor="w", pady=12)
    actions = ttk.Frame(body)
    actions.pack(side="bottom", fill="x")
    cancel = ttk.Button(actions, text="取消", command=root.destroy)
    cancel.pack(side="left")
    results = queue.Queue()
    running = False
    def poll():
        nonlocal running
        try:
            error = results.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        running = False
        cancel.configure(state="normal")
        if error is not None:
            status.set(f"卸载未完成：{error}")
            button.configure(state="normal")
        else:
            status.set("卸载完成。笔记与未登记文件已保留。")
            button.configure(text="完成", command=root.destroy, state="normal")
    def run():
        nonlocal running
        running = True
        button.configure(state="disabled")
        cancel.configure(state="disabled")
        status.set("正在等待应用正常退出并移除登记文件…")
        clear_data = clear.get()
        def worker():
            try:
                uninstall_application(home, clear_data=clear_data, register=register)
            except (OSError, ValueError) as error:
                results.put(error)
            else:
                results.put(None)
        threading.Thread(target=worker, name="NoteFlash-Uninstall", daemon=False).start()
        root.after(100, poll)
    button = ttk.Button(actions, text="确认卸载", command=run)
    button.pack(side="right")
    root.protocol("WM_DELETE_WINDOW", lambda: None if running else root.destroy())
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Note Flash 中文卸载程序")
    parser.add_argument("--uninstall", type=Path,
                        default=Path(sys.executable).parent if getattr(sys, "frozen", False) else None)
    parser.add_argument("--clear-data", action="store_true")
    parser.add_argument("--wait-pid", type=int)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--report-file", type=Path)
    parser.add_argument("--no-register", action="store_true")
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.uninstall is None:
        parser.error("开发模式请提供 --uninstall 安装目录。")
    home = checked_path(args.uninstall)
    if getattr(sys, "frozen", False) and not args.worker and Path(sys.executable).parent == home:
        stage = None
        try:
            plan_uninstall(home, clear_data=args.clear_data)
            stage = _stage_helper(home)
            command = [str(stage / "Uninstall.exe"), "--uninstall", str(home), *sys.argv[1:], "--worker"]
            subprocess.Popen(command, cwd=stage)
        except (OSError, ValueError) as error:
            if stage is not None:
                _remove_stage(stage)
            if args.confirmed:
                raise
            import tkinter as tk
            root = tk.Tk()
            root.title("卸载未完成")
            tk.Label(root, text=str(error), wraplength=450, padx=24, pady=24).pack()
            tk.Button(root, text="关闭", command=root.destroy).pack(pady=(0, 20))
            root.mainloop()
        return
    def ready():
        if args.ready_file is not None:
            _write_atomic(args.ready_file, json.dumps({"ready": True, "install_dir": str(home)}).encode("utf-8"))
    try:
        if args.confirmed:
            result = uninstall_application(home, clear_data=args.clear_data, wait_pid=args.wait_pid,
                register=not args.no_register, ready=ready)
            if args.report_file:
                _write_atomic(args.report_file, json.dumps(result, ensure_ascii=False).encode("utf-8"))
        else:
            _uninstall_gui(home, not args.no_register)
    except (OSError, ValueError) as error:
        if args.ready_file:
            _write_atomic(args.ready_file, json.dumps({"ready": False, "error": str(error)}, ensure_ascii=False).encode("utf-8"))
        if args.report_file:
            _write_atomic(args.report_file, json.dumps({"uninstalled": False, "error": str(error)}, ensure_ascii=False).encode("utf-8"))
        raise
    finally:
        if args.worker:
            _schedule_stage_cleanup()


if __name__ == "__main__":
    main()
