"""Local text files and workspace state. Uses only the Python standard library."""

from __future__ import annotations

import codecs
from dataclasses import dataclass, field
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any


class ExternalChangeError(OSError):
    """The file on disk no longer matches the version opened by the editor."""


class StateCorruptionError(ValueError):
    """Workspace state cannot be read; keep the original file for recovery."""


class MoveIncompleteError(OSError):
    """The destination is complete, but source or staging cleanup failed."""

    def __init__(self, source: Path, destination: Path, reason: OSError):
        self.source = source
        self.destination = destination
        self.destination_complete = True
        super().__init__(
            f"内容已完整复制到：{destination}\n"
            f"清理未完成，来源可能仍有部分或全部残留：{source}\n"
            f"请使用目标中的完整副本，并核对残留；未自动删除目标。\n{reason}"
        )


def _read_bytes(path: Path) -> tuple[bytes, tuple[int, int, str]]:
    with path.open("rb") as stream:
        raw = stream.read()
        stat = os.fstat(stream.fileno())
    return raw, (stat.st_mtime_ns, stat.st_size, hashlib.sha256(raw).hexdigest())


def _read_text(path: Path) -> tuple[str, str, str, bytes, tuple[int, int, str]]:
    raw, signature = _read_bytes(path)
    bom = b""
    if raw.startswith(codecs.BOM_UTF8):
        encoding = "utf-8-sig"
        text = raw.decode(encoding)
    elif raw.startswith(codecs.BOM_UTF16_LE):
        encoding, bom = "utf-16-le", codecs.BOM_UTF16_LE
        text = raw[len(bom):].decode(encoding)
    elif raw.startswith(codecs.BOM_UTF16_BE):
        encoding, bom = "utf-16-be", codecs.BOM_UTF16_BE
        text = raw[len(bom):].decode(encoding)
    else:
        encoding = "utf-8"
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            encoding = "gb18030"
            text = raw.decode(encoding)
    match = re.search(r"\r\n|\r|\n", text)
    newline = match.group() if match else os.linesep
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, encoding, newline, bom, signature


def _write_atomic(path: Path, payload: bytes) -> None:
    """Keep the previous file intact if writing the replacement fails."""
    mode = path.stat().st_mode if path.exists() else None
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".note-flash-", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # On Windows the original read-only flag already prevents replacement;
        # copying it onto the staging file would also prevent failure cleanup.
        if mode is not None and os.name != "nt":
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class Document:
    """An open note; editor text uses LF while disk encoding is retained."""

    path: Path
    text: str
    encoding: str
    newline: str
    signature: Any
    dirty: bool = False
    highlights: list[dict] = field(default_factory=list)
    _bom: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path).expanduser().resolve()

    @classmethod
    def open(cls, path: Path) -> Document:
        path = Path(path).expanduser().resolve()
        text, encoding, newline, bom, signature = _read_text(path)
        return cls(path, text, encoding, newline, signature, _bom=bom)

    def has_external_change(self) -> bool:
        try:
            return _read_bytes(self.path)[1] != self.signature
        except FileNotFoundError:
            return True

    def save(self, force: bool = False) -> None:
        # Read first even when forced: a removed note must not be recreated.
        current_signature = _read_bytes(self.path)[1]
        if not force and current_signature != self.signature:
            raise ExternalChangeError(f"文件已被其他程序修改，请先选择处理方式：{self.path}")
        payload = self._bom + self.text.replace("\n", self.newline).encode(self.encoding)
        _write_atomic(self.path, payload)
        self.signature = _read_bytes(self.path)[1]
        self.dirty = False

    def reload(self) -> None:
        text, encoding, newline, bom, signature = _read_text(self.path)
        self.text = text
        self.encoding = encoding
        self.newline = newline
        self._bom = bom
        self.signature = signature
        self.dirty = False
        self.highlights.clear()


class WorkspaceStore:
    """UTF-8 JSON state, separate from note content."""

    def __init__(self, state_path: Path):
        self.path = Path(state_path).expanduser().resolve()

    def load(self) -> dict:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return {}
        try:
            state = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise StateCorruptionError(f"工作区状态损坏，原文件已保留：{self.path}") from error
        if not isinstance(state, dict):
            raise StateCorruptionError(f"工作区状态必须是 JSON 对象，原文件已保留：{self.path}")

        def require(condition, field_name):
            if not condition:
                raise StateCorruptionError(
                    f"工作区状态字段格式错误（{field_name}），原文件已保留：{self.path}"
                )

        def valid_path(value):
            return isinstance(value, str) and bool(value) and "\0" not in value

        # Validate the persisted UI contract once, at the file boundary. Missing
        # optional fields and unknown keys are left untouched for the UI.
        if "folders" in state:
            require(isinstance(state["folders"], list), "folders")
            require(all(valid_path(path) for path in state["folders"]), "folders")
        if "tabs" in state:
            require(isinstance(state["tabs"], list), "tabs")
            for index, tab in enumerate(state["tabs"]):
                label = f"tabs[{index}]"
                require(isinstance(tab, dict), label)
                require(valid_path(tab.get("path")), label + ".path")
                if "cursor" in tab:
                    require(
                        isinstance(tab["cursor"], str)
                        and re.fullmatch(r"[1-9][0-9]*\.[0-9]+", tab["cursor"]),
                        label + ".cursor",
                    )
        if "active" in state:
            require(state["active"] is None or valid_path(state["active"]), "active")
        if "panel_size" in state:
            size = state["panel_size"]
            require(isinstance(size, list) and len(size) == 2, "panel_size")
            require(all(type(value) is int and value > 0 for value in size), "panel_size")
        if "colors" in state:
            require(isinstance(state["colors"], list), "colors")
            require(all(
                isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color)
                for color in state["colors"]
            ), "colors")
        if "species" in state:
            require(state["species"] in ("cat", "dog", "snake", "raccoon"), "species")
        for name in ("wander", "sidebar", "wrap"):
            if name in state:
                require(type(state[name]) is bool, name)
        if "pet_x" in state:
            require(type(state["pet_x"]) is int, "pet_x")
        if "pet_scale" in state:
            require(type(state["pet_scale"]) is int and 50 <= state["pet_scale"] <= 200, "pet_scale")
        if "highlights" in state:
            require(isinstance(state["highlights"], dict), "highlights")
            for path, record in state["highlights"].items():
                label = f"highlights[{path}]"
                require(valid_path(path) and isinstance(record, dict), label)
                digest = record.get("digest")
                require(
                    isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest),
                    label + ".digest",
                )
                require(isinstance(record.get("items"), list), label + ".items")
                for index, mark in enumerate(record["items"]):
                    item_label = f"{label}.items[{index}]"
                    require(isinstance(mark, dict), item_label)
                    start, end, color = mark.get("start"), mark.get("end"), mark.get("color")
                    require(
                        type(start) is int and type(end) is int and 0 <= start < end,
                        item_label + ".start/end",
                    )
                    require(
                        isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color),
                        item_label + ".color",
                    )
        return state

    def save(self, state: dict) -> None:
        if not isinstance(state, dict):
            raise TypeError("工作区状态必须是字典")
        payload = json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        # Refuse to overwrite corrupt state, including after a failed startup load.
        self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.path, payload)


def create_note(folder: Path, name: str) -> Path:
    """Create one empty TXT/MD note without overwriting an existing path."""
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³")
    if (
        not name
        or name != name.strip()
        or name.endswith(".")
        or any(character in '<>:"/\\|?*' or ord(character) < 32 for character in name)
        or name.split(".", 1)[0].upper() in reserved
        or Path(name).suffix.lower() not in {".txt", ".md"}
    ):
        raise ValueError("请输入有效的 TXT 或 Markdown 文件名（以 .txt 或 .md 结尾）")
    path = Path(folder).expanduser().resolve() / name
    with path.open("xb"):
        pass
    return path


def move_path(source: Path, destination: Path) -> None:
    """Rename on one volume, or publish a complete copy before source removal."""
    source = Path(source).expanduser().resolve(strict=True)
    destination = Path(destination).expanduser().resolve()
    if source == destination:
        return
    if destination.exists():
        raise FileExistsError(f"目标名称已经存在，未覆盖：{destination}")
    is_directory = source.is_dir()
    if is_directory and destination.is_relative_to(source):
        raise ValueError("文件夹不能移入自身")
    try:
        source.rename(destination)
        return
    except OSError as error:
        if error.errno != errno.EXDEV and getattr(error, "winerror", None) != 17:
            raise

    destination_complete = False
    try:
        # Staging belongs to this operation. A failed copy cannot leave a
        # partial note at the requested destination or alter the source.
        with tempfile.TemporaryDirectory(prefix=".note-flash-move-", dir=destination.parent) as directory:
            staged = Path(directory) / "content"
            if is_directory:
                shutil.copytree(source, staged, symlinks=True, copy_function=shutil.copy2)
            else:
                shutil.copy2(source, staged)
            if destination.exists():
                raise FileExistsError(f"目标名称已经存在，未覆盖：{destination}")
            staged.rename(destination)
            destination_complete = True
        if is_directory:
            shutil.rmtree(source)
        else:
            source.unlink()
    except OSError as error:
        if destination_complete:
            raise MoveIncompleteError(source, destination, error) from error
        raise


def search_files(roots: list[Path], query: str, *, cancelled=None) -> tuple[list[dict], list[str]]:
    """Search literal names and text. Body locations are one-based; names use 0."""
    results: list[dict] = []
    errors: list[str] = []
    if not query:
        return results, errors
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    seen: set[Path] = set()
    for raw_root in roots:
        root = Path(raw_root).expanduser().resolve()
        if not root.is_dir():
            errors.append(f"文件夹不存在或不可访问：{root}")
            continue
        for directory, folders, files in os.walk(root, onerror=lambda error: errors.append(str(error))):
            if cancelled is not None and cancelled():return results, errors
            folders.sort(key=str.casefold)
            for name in sorted(files, key=str.casefold):
                if cancelled is not None and cancelled():return results, errors
                if Path(name).suffix.lower() not in {".txt", ".md"}:
                    continue
                path = (Path(directory) / name).resolve()
                if path in seen:
                    continue
                seen.add(path)
                if pattern.search(name):
                    results.append({"path": str(path), "line": 0, "column": 0, "snippet": name})
                try:
                    text = _read_text(path)[0]
                except (OSError, UnicodeError) as error:
                    errors.append(f"{path}：{error}")
                    continue
                for line_number, line in enumerate(text.split("\n"), 1):
                    if cancelled is not None and cancelled():return results, errors
                    for match in pattern.finditer(line):
                        if cancelled is not None and cancelled():return results, errors
                        start = max(0, match.start() - 50)
                        end = min(len(line), max(start + 160, match.end()))
                        snippet = ("…" if start else "") + line[start:end] + ("…" if end < len(line) else "")
                        results.append({
                            "path": str(path), "line": line_number,
                            "column": match.start() + 1, "snippet": snippet,
                        })
    return results, errors


def recycle_path(path: Path) -> None:
    """Move a path to the Windows Recycle Bin, never use a delete fallback."""
    path = Path(path).expanduser().resolve(strict=True)
    if sys.platform != "win32":
        raise OSError("回收站操作仅支持 Windows")
    import ctypes
    from ctypes import wintypes
    import uuid

    # SHFileOperation's ALLOWUNDO is only best effort. IFileOperation supports
    # RECYCLEONDELETE, which explicitly requests recycling instead of erasure.
    guid_type = ctypes.c_ubyte * 16
    class_id = guid_type.from_buffer_copy(uuid.UUID("3ad05575-8857-4850-9277-11b85bdb8e09").bytes_le)
    operation_id = guid_type.from_buffer_copy(uuid.UUID("947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8").bytes_le)
    shell_item_id = guid_type.from_buffer_copy(uuid.UUID("43826d1e-e718-42ee-bc55-a1e261c37bfe").bytes_le)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(guid_type), ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(guid_type), ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    shell32.SHCreateItemFromParsingName.argtypes = [
        wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(guid_type),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell32.SHCreateItemFromParsingName.restype = ctypes.c_long

    class RecycleInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("size", ctypes.c_longlong),
            ("items", ctypes.c_longlong),
        ]

    shell32.SHQueryRecycleBinW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(RecycleInfo)]
    shell32.SHQueryRecycleBinW.restype = ctypes.c_long

    def check(result: int) -> None:
        if result < 0:
            raise OSError(f"无法移入回收站（Windows 0x{result & 0xFFFFFFFF:08X}）：{path}")

    def method(pointer, index, result_type, *argument_types):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)(table[index])

    # IFileOperation requires an STA; a conflicting apartment fails explicitly.
    check(ole32.CoInitializeEx(None, 0x2))
    operation = ctypes.c_void_p()
    item = ctypes.c_void_p()
    try:
        # In a restricted Windows session the shell may remove a source while
        # its Recycle Bin is inaccessible. Refuse before queuing any deletion.
        recycle_info = RecycleInfo()
        recycle_info.cbSize = ctypes.sizeof(recycle_info)
        check(shell32.SHQueryRecycleBinW(path.anchor, ctypes.byref(recycle_info)))
        check(ole32.CoCreateInstance(
            ctypes.byref(class_id), None, 1, ctypes.byref(operation_id), ctypes.byref(operation)
        ))
        check(shell32.SHCreateItemFromParsingName(
            str(path), None, ctypes.byref(shell_item_id), ctypes.byref(item)
        ))
        # FOFX_RECYCLEONDELETE | FOFX_EARLYFAILURE | FOFX_ADDUNDORECORD |
        # FOF_SILENT | FOF_NOCONFIRMATION | FOF_NOERRORUI. No permanent fallback.
        flags = 0x00080000 | 0x00100000 | 0x20000000 | 0x4 | 0x10 | 0x400
        check(method(operation, 5, ctypes.c_long, wintypes.DWORD)(operation, flags))
        check(method(operation, 18, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(operation, item, None))
        check(method(operation, 21, ctypes.c_long)(operation))
        aborted = wintypes.BOOL()
        check(method(operation, 22, ctypes.c_long, ctypes.POINTER(wintypes.BOOL))(
            operation, ctypes.byref(aborted)
        ))
        if aborted.value or path.exists():
            raise OSError(f"回收站操作已取消或未完成：{path}")
    finally:
        if item:
            method(item, 2, wintypes.ULONG)(item)
        if operation:
            method(operation, 2, wintypes.ULONG)(operation)
        ole32.CoUninitialize()
