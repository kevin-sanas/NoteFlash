"""Explicit application data ownership, separate from managed note folders."""

from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat

from .core import WorkspaceStore, _write_atomic


CONFIG_NAME = "note-flash-install.json"
DATA_MARKER = ".note-flash-data.json"
DATA_FILES = ("state.json",)


class MigrationCleanupError(OSError):
    """The verified destination is active; only old owned-record cleanup failed."""

    def __init__(self, data_dir: Path, activated: bool, error: OSError):
        self.data_dir = data_dir
        self.activated = activated
        super().__init__(f"新数据已完整迁移到：{data_dir}\n旧记录清理未完成，请核对残留；新数据未回滚。\n{error}")


def checked_path(path: Path) -> Path:
    """Normalize without following a symlink or Windows junction ancestor."""
    path = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"不支持符号链接、目录联接或其他重解析点：{component}")
    return path


def owned_relative_path(name: str) -> str:
    """Validate a manifest/archive name once before it becomes an owned path."""
    if not isinstance(name, str) or not name or PureWindowsPath(name).drive:
        raise ValueError("安装清单含无效路径。")
    name = name.replace("\\", "/")
    parts = name.split("/")
    if (name.startswith("/") or any(part in ("", ".", "..") or part.endswith((" ", "."))
            or any(c in '<>:"|?*' or ord(c) < 32 for c in part) for part in parts)):
        raise ValueError("安装清单含无效路径。")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    if any(part.split(".", 1)[0].upper() in reserved for part in parts):
        raise ValueError("安装清单含 Windows 保留名称。")
    return name


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"配置损坏，原文件已保留：{path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"配置必须是 JSON 对象：{path}")
    return value


def _write_json(path: Path, value: dict):
    _write_atomic(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def read_install_config(app_home: Path) -> dict | None:
    home = checked_path(app_home)
    path = checked_path(home / CONFIG_NAME)
    if not path.exists():
        return None
    value = _read_json(path)
    if value.get("app") != "NoteFlash" or value.get("format") != 1:
        raise ValueError(f"不是可识别的 Note Flash 安装配置：{path}")
    for field in ("install_dir", "data_dir"):
        raw = value.get(field)
        if not isinstance(raw, str) or not raw or "\0" in raw or not Path(raw).is_absolute():
            raise ValueError(f"安装配置的 {field} 无效：{path}")
    if Path(value["install_dir"]) != home:
        raise ValueError("安装清单与当前程序目录不一致，未执行操作。")
    files = value.get("files")
    if not isinstance(files, list) or not all(isinstance(name, str) for name in files):
        raise ValueError("安装文件清单无效。")
    value["files"] = [owned_relative_path(name) for name in files]
    if len({name.casefold() for name in value["files"]}) != len(value["files"]):
        raise ValueError("安装文件清单存在重复路径。")
    if type(value.get("registered", False)) is not bool:
        raise ValueError("安装注册标记无效。")
    return value


def resolve_data_dir(app_home: Path, explicit: Path | None = None) -> Path:
    """Resolve only; calling this function never creates or migrates data."""
    if explicit is not None:
        return checked_path(explicit)
    config = read_install_config(app_home)
    if config is not None:
        return checked_path(config["data_dir"])
    local = os.environ.get("LOCALAPPDATA")
    return checked_path(Path(local) / "NoteFlash" / "Data" if local else Path(app_home) / "data")


def _reject_note_root(path: Path, notes_roots):
    if any(path == checked_path(root) for root in notes_roots):
        raise ValueError("应用数据目录不能是管理的笔记根目录；笔记文件夹保持原位。")


def read_data_marker(path: Path) -> dict:
    marker = _read_json(checked_path(path / DATA_MARKER))
    if (marker.get("app") != "NoteFlash" or marker.get("format") != 1
            or marker.get("files") != list(DATA_FILES)):
        raise ValueError(f"应用数据所有权标记无效，未清理任何内容：{path}")
    return marker


def prepare_data_dir(path: Path, notes_roots=()) -> Path:
    path = checked_path(path)
    _reject_note_root(path, notes_roots)
    state_path = checked_path(path / "state.json")
    if state_path.exists():
        state = WorkspaceStore(state_path).load()
        _reject_note_root(path, state.get("folders", []))
    marker = checked_path(path / DATA_MARKER)
    if marker.exists():
        read_data_marker(path)
    else:
        path.mkdir(parents=True, exist_ok=True)
        _write_json(marker, {"app": "NoteFlash", "format": 1, "files": list(DATA_FILES)})
    return path


def write_data_location(app_home: Path, data_dir: Path) -> None:
    home, data = checked_path(app_home), checked_path(data_dir)
    config = read_install_config(home)
    if config is None:
        config = {"app": "NoteFlash", "format": 1, "install_dir": str(home),
                  "files": [], "registered": False}
    config["data_dir"] = str(data)
    _write_json(home / CONFIG_NAME, config)


def migrate_data_dir(old: Path, new: Path, notes_roots=(), app_home: Path | None = None) -> Path:
    """Verify a copy of owned records, switch, then remove only old owned records.

    Save the editor/session first. Unknown files and all note content stay at
    their original paths. Without app_home the caller owns the final switch.
    """
    old, new = checked_path(old), checked_path(new)
    source = checked_path(old / "state.json")
    state = WorkspaceStore(source).load()
    _reject_note_root(new, (*notes_roots, *state.get("folders", [])))
    if new == old:
        return old
    if new.exists() and (not new.is_dir() or any(new.iterdir())):
        raise FileExistsError("迁移目标必须是新的专用空目录，已有数据不会覆盖。")
    if (old / DATA_MARKER).exists():
        read_data_marker(old)
    new.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        for name in DATA_FILES:
            origin, target = checked_path(old / name), new / name
            if not origin.exists():
                continue
            payload = origin.read_bytes()
            written.append(target)
            shutil.copyfile(origin, target)
            if target.read_bytes() != payload:
                raise OSError(f"迁移验证未通过，仍使用原数据：{origin}")
        WorkspaceStore(new / "state.json").load()
        written.append(new / DATA_MARKER)
        prepare_data_dir(new, notes_roots)
        if app_home is not None:
            write_data_location(app_home, new)
    except (OSError, ValueError):
        for target in reversed(written):
            target.unlink(missing_ok=True)
        if not any(new.iterdir()):
            new.rmdir()
        raise
    try:
        for name in (*DATA_FILES, DATA_MARKER):
            checked_path(old / name).unlink(missing_ok=True)
        if old.exists() and not any(old.iterdir()):
            old.rmdir()
    except OSError as error:
        raise MigrationCleanupError(new, app_home is not None, error) from error
    return new


def clear_owned_data(path: Path, notes_roots=()) -> list[Path]:
    """Delete the listed settings/highlights only; never traverse unknown items."""
    path = checked_path(path)
    _reject_note_root(path, notes_roots)
    if not path.exists():
        return []
    read_data_marker(path)
    files = [checked_path(path / name) for name in (*DATA_FILES, DATA_MARKER)]
    if any(target.exists() and not target.is_file() for target in files):
        raise ValueError("数据清单中的记录不是普通文件，未清理任何内容。")
    removed = []
    for target in files:
        if target.exists():
            target.unlink()
            removed.append(target)
    if not any(path.iterdir()):
        path.rmdir()
    return removed
