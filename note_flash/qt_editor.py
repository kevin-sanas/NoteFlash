"""Plain-text Qt editor with transparent painting and separate highlight data."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

RUNTIME_DEPS = Path(__file__).resolve().parents[1] / ".runtime-deps"
if RUNTIME_DEPS.is_dir() and str(RUNTIME_DEPS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DEPS))

from PySide6.QtCore import QPoint, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette, QTextCursor, QTextDocument
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QTextEdit

from .core import Document


class NoteEditor(QPlainTextEdit):
    edited = Signal()
    highlights_changed = Signal()
    palette_requested = Signal(QPoint)

    def __init__(self, doc: Document, parent=None, highlights_record=None):
        super().__init__(parent)
        self.doc = doc
        self.highlight_warning = False
        self._highlights: list[tuple[QTextCursor, str]] = []
        self._alt_alone = False
        font = QFont("Consolas")
        font.setPixelSize(18)
        self.setFont(font)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        palette = self.palette()
        for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Window):
            palette.setColor(role, QColor(0, 0, 0, 0))
        palette.setColor(QPalette.ColorRole.Text, QColor(24, 44, 80, 255))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#bad7fa"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(24, 44, 80, 255))
        self.setPalette(palette)
        self.viewport().setPalette(palette)
        self.viewport().setAutoFillBackground(False)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(
            "QPlainTextEdit { background: transparent; color: #182c50; border: none; font-family: 'Consolas'; font-size:18px;"
            " selection-background-color: #bad7fa; selection-color: #182c50; }"
        )
        self.viewport().setStyleSheet("background: transparent;")
        self.setPlainText(doc.text)
        self.restore_highlights(highlights_record)
        self.textChanged.connect(self._text_changed)

    def _text_changed(self):
        self.doc.dirty = True
        self._refresh_highlights()
        self.edited.emit()

    def save(self, force=False):
        self.doc.text = self.toPlainText()
        self.doc.save(force=force)
        self.document().setModified(False)

    def reload(self):
        self.doc.reload()
        with QSignalBlocker(self):
            self._highlights.clear()
            self.setPlainText(self.doc.text)
            self.setExtraSelections([])
        self.highlight_warning = False
        self.document().setModified(False)

    def _tracked_cursor(self, start, end):
        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        return cursor

    def _refresh_highlights(self):
        self._highlights = [(cursor, color) for cursor, color in self._highlights if cursor.hasSelection()]
        selections = []
        for cursor, color in self._highlights:
            selection = QTextEdit.ExtraSelection()
            selection.cursor = QTextCursor(cursor)
            selection.format.setBackground(QColor(color))
            selections.append(selection)
        self.setExtraSelections(selections)

    def restore_highlights(self, record) -> bool:
        self._highlights.clear()
        self.setExtraSelections([])
        self.highlight_warning = False
        if record is None or record == {}:
            return True
        digest = hashlib.sha256(self.toPlainText().encode("utf-8")).hexdigest()
        if not isinstance(record, dict) or record.get("digest") != digest or not isinstance(record.get("items"), list):
            self.highlight_warning = True
            return False
        maximum = self.document().characterCount() - 1
        restored = []
        for mark in record["items"]:
            if not isinstance(mark, dict):
                self.highlight_warning = True
                return False
            start, end, color = mark.get("start"), mark.get("end"), mark.get("color")
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= maximum
                    or not isinstance(color, str) or not QColor(color).isValid()):
                self.highlight_warning = True
                return False
            restored.append((self._tracked_cursor(start, end), QColor(color).name()))
        self._highlights = restored
        self._refresh_highlights()
        return True

    def snapshot_highlights(self) -> dict:
        marks = [
            {"start": cursor.selectionStart(), "end": cursor.selectionEnd(), "color": color}
            for cursor, color in self._highlights if cursor.hasSelection()
        ]
        marks.sort(key=lambda mark: (mark["start"], mark["end"]))
        return {"digest": hashlib.sha256(self.toPlainText().encode("utf-8")).hexdigest(), "items": marks}

    def apply_highlight(self, color: str | None):
        selection = self.textCursor()
        if self.doc.path.suffix.lower() != ".txt" or not selection.hasSelection():
            return
        if color is not None:
            if not isinstance(color, str) or not QColor(color).isValid():
                raise ValueError("无效的高亮颜色")
            color = QColor(color).name()
        start, end = selection.selectionStart(), selection.selectionEnd()
        remaining = []
        for cursor, previous_color in self._highlights:
            left, right = cursor.selectionStart(), cursor.selectionEnd()
            if right <= start or left >= end:
                remaining.append((cursor, previous_color))
                continue
            if left < start:
                remaining.append((self._tracked_cursor(left, start), previous_color))
            if right > end:
                remaining.append((self._tracked_cursor(end, right), previous_color))
        if color is not None:
            remaining.append((self._tracked_cursor(start, end), color))
        self._highlights = remaining
        self.highlight_warning = False
        self._refresh_highlights()
        self.highlights_changed.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Alt:
            if not event.isAutoRepeat():
                self._alt_alone = True
            event.accept()
            return
        self._alt_alone = False
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Alt:
            request = self._alt_alone and not event.isAutoRepeat()
            self._alt_alone = False
            event.accept()
            if request and self.doc.path.suffix.lower() == ".txt" and self.textCursor().hasSelection():
                self.palette_requested.emit(self.viewport().mapToGlobal(self.cursorRect().bottomLeft()))
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self._alt_alone = False
        super().focusOutEvent(event)

    def find_next(self, query: str) -> bool:
        if not query:
            return False
        original = self.textCursor()
        flags = QTextDocument.FindFlag.FindCaseSensitively
        if self.find(query, flags):
            return True
        self.moveCursor(QTextCursor.MoveOperation.Start)
        if self.find(query, flags):
            return True
        self.setTextCursor(original)
        return False

    def replace_selection(self, query: str, replacement: str) -> bool:
        cursor = self.textCursor()
        if not query or cursor.selectedText().replace("\u2029", "\n") != query:
            return False
        cursor.insertText(replacement)
        self.setTextCursor(cursor)
        return True

    def replace_all(self, query: str, replacement: str) -> int:
        if not query:
            return 0
        document = self.document()
        group = QTextCursor(document)
        group.beginEditBlock()
        count = 0
        position = 0
        last_cursor = None
        while True:
            cursor = document.find(query, position, QTextDocument.FindFlag.FindCaseSensitively)
            if cursor.isNull():
                break
            cursor.insertText(replacement)
            position = cursor.position()
            last_cursor = cursor
            count += 1
        group.endEditBlock()
        if last_cursor is not None:
            self.setTextCursor(last_cursor)
        return count
