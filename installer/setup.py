"""Chinese per-user installer with separate program and application-data paths."""

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from note_flash import __version__
from note_flash.core import _write_atomic
from note_flash.data_paths import (CONFIG_NAME, DATA_MARKER, checked_path, owned_relative_path,
                                  prepare_data_dir, resolve_data_dir)
from installer.uninstall import registration_key, remove_registration


def register_application(home: Path, size: int):
    import winreg
    command = subprocess.list2cmdline([str(home / "Uninstall.exe"), "--uninstall", str(home)])
    values = {"InstallLocation": str(home), "DisplayName": "Note Flash · 桌面笔记",
              "DisplayVersion": __version__, "Publisher": "Note Flash",
              "DisplayIcon": str(home / "NoteFlash.exe"), "UninstallString": command,
              "QuietUninstallString": command + " --confirmed", "NoModify": 1,
              "NoRepair": 1, "EstimatedSize": max(1, (size + 1023) // 1024)}
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, registration_key(home),
                           0, winreg.KEY_SET_VALUE) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD if type(value) is int else winreg.REG_SZ, value)


def install_bundle(bundle: Path, destination: Path, data_dir: Path | None = None, *,
                   register=True, progress=None) -> Path:
    destination = checked_path(destination)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise FileExistsError("安装目录必须为空；已有文件和笔记不会被覆盖。")
    data = checked_path(data_dir) if data_dir is not None else resolve_data_dir(destination)
    if data.is_relative_to(destination) or destination.is_relative_to(data):
        raise ValueError("应用数据与安装目录必须互相独立，不能相同或互为父子目录。")
    with zipfile.ZipFile(bundle) as archive:
        entries, names = [], set()
        for member in archive.infolist():
            name = owned_relative_path(member.filename.rstrip("/") if member.is_dir() else member.filename)
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("安装资源不允许符号链接或重解析点。")
            key = name.casefold()
            if key in names or key == CONFIG_NAME.casefold():
                raise ValueError("安装资源含重复路径或保留配置文件。")
            names.add(key)
            entries.append((member, name))
        files = [name for member, name in entries if not member.is_dir()]
        if not {"NoteFlash.exe", "Uninstall.exe"}.issubset(files):
            raise ValueError("安装资源缺少 NoteFlash.exe 或 Uninstall.exe。")
        file_keys = {name.casefold() for name in files}
        if any(parent.as_posix().casefold() in file_keys for name in files
               for parent in Path(name).parents if str(parent) != "."):
            raise ValueError("安装资源把同一路径同时用作文件和目录。")
        marker_existed = (data / DATA_MARKER).exists()
        prepared = prepare_data_dir(data)
        destination.mkdir(parents=True, exist_ok=True)
        written = []
        registration_started = False
        try:
            total = sum(member.file_size for member, _ in entries if not member.is_dir())
            completed = 0
            for member, name in entries:
                target = destination / name
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                written.append(target)
                with archive.open(member) as source, target.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                        completed += len(chunk)
                        if progress is not None:
                            progress(completed, total)
            config = {"app": "NoteFlash", "format": 1, "install_dir": str(destination),
                      "data_dir": str(data), "files": [*files, CONFIG_NAME], "registered": bool(register)}
            written.append(destination / CONFIG_NAME)
            _write_atomic(destination / CONFIG_NAME, json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8"))
            if register:
                registration_started = True
                register_application(destination, total)
        except (OSError, ValueError, zipfile.BadZipFile):
            if registration_started:
                remove_registration(destination)
            for target in reversed(written):
                target.unlink(missing_ok=True)
            directories = {parent for path in written for parent in path.parents if parent.is_relative_to(destination)}
            for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
                if path.exists() and not any(path.iterdir()):
                    path.rmdir()
            if not marker_existed:
                (prepared / DATA_MARKER).unlink(missing_ok=True)
                if not any(prepared.iterdir()):
                    prepared.rmdir()
            raise
    return destination / "NoteFlash.exe"


def _install_gui(bundle: Path, register: bool):
    import tkinter as tk
    from tkinter import filedialog, ttk
    with zipfile.ZipFile(bundle) as archive:
        required_mb = sum(member.file_size for member in archive.infolist()) / (1024 * 1024)
    root = tk.Tk()
    root.title("安装 Note Flash")
    root.geometry("610x560")
    root.resizable(False, False)
    body = ttk.Frame(root, padding=26)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="欢迎安装 Note Flash", font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
    ttk.Label(body, text=f"本地笔记与像素伙伴 · 所需程序空间约 {required_mb:.1f} MB\n无需另装 Python。下载位置与下面的安装位置互相独立。",
              justify="left").pack(anchor="w", pady=(8, 18))
    local = Path(os.environ.get("LOCALAPPDATA", Path.cwd()))
    destination = tk.StringVar(value=str(local / "Programs" / "NoteFlash"))
    data = tk.StringVar(value=str(local / "NoteFlash" / "Data"))
    for caption, variable in (("软件安装目录（空目录）", destination), ("应用数据目录（设置、会话与高亮）", data)):
        ttk.Label(body, text=caption).pack(anchor="w", pady=(8, 4))
        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True, ipady=4)
        def browse(variable=variable, caption=caption):
            chosen = filedialog.askdirectory(parent=root, title=f"选择{caption}")
            if chosen:
                variable.set(chosen)
        ttk.Button(row, text="浏览…", command=browse).pack(side="right", padx=(8, 0))
    ttk.Label(body, text="TXT / Markdown 笔记文件夹由应用内单独添加，保持原位。\n安装不会开启开机启动；卸载时默认保留设置和高亮。", justify="left").pack(anchor="w", pady=16)
    bar = ttk.Progressbar(body, maximum=100)
    bar.pack(fill="x")
    status = tk.StringVar(value="请选择目录后开始安装。")
    ttk.Label(body, textvariable=status, wraplength=550).pack(anchor="w", pady=8)
    actions = ttk.Frame(body)
    actions.pack(side="bottom", fill="x")
    ttk.Button(actions, text="取消", command=root.destroy).pack(side="left")
    def install():
        button.configure(state="disabled")
        status.set("正在安装程序文件…")
        root.update_idletasks()
        def progress(done, total):
            bar["value"] = done / total * 100 if total else 100
            root.update_idletasks()
        try:
            executable = install_bundle(bundle, Path(destination.get()), Path(data.get()),
                                         register=register, progress=progress)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            status.set(f"安装未完成：{error}")
            button.configure(state="normal")
            return
        bar["value"] = 100
        status.set(f"安装完成。应用数据：{data.get()}")
        def launch():
            subprocess.Popen([str(executable), "--open"], cwd=executable.parent)
            root.destroy()
        button.configure(text="打开 Note Flash", command=launch, state="normal")
    button = ttk.Button(actions, text="安装", command=install)
    button.pack(side="right")
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Note Flash 中文安装程序")
    parser.add_argument("--target", type=Path, help="安装到指定空目录")
    parser.add_argument("--data-dir", type=Path, help="独立的应用数据目录")
    parser.add_argument("--no-register", action="store_true", help="隔离验证时不修改注册表")
    parser.add_argument("--bundle", type=Path, help="仅开发时指定应用压缩包")
    args = parser.parse_args()
    resource = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundle = args.bundle or resource / "application.zip"
    if args.target:
        install_bundle(bundle, args.target, args.data_dir, register=not args.no_register)
    else:
        _install_gui(bundle, not args.no_register)


if __name__ == "__main__":
    main()
