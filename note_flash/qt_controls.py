"""Small ice-blue controls shared by the Qt panel and its settings."""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QAbstractButton, QCheckBox, QFrame, QHBoxLayout, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from .qt_glass import WindowBlur


def _control_font():
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(15)
    return font


class PetCard(QAbstractButton):
    """A checkable pet choice that keeps the supplied pixel artwork crisp."""

    def __init__(self, species: str, title: str, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.species = species
        self.pixmap = QPixmap(pixmap)
        self.setText(title)
        self.setAccessibleName(title)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(_control_font())
        self.setFixedSize(106, 138)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def sizeHint(self):
        return QSize(106, 138)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        gradient = QLinearGradient(0, 0, 0, self.height())
        if self.isChecked():
            gradient.setColorAt(0, QColor(202, 230, 252, 200))
            gradient.setColorAt(1, QColor(172, 210, 243, 165))
        else:
            gradient.setColorAt(0, QColor(242, 250, 255, 125 if self.underMouse() else 95))
            gradient.setColorAt(1, QColor(217, 235, 252, 90 if self.underMouse() else 65))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor("#5598db") if self.isChecked()
                            else QColor(255, 255, 255, 190), 1.6 if self.isChecked() else 1.2))
        painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 12, 12)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#608fbd"), 1, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(QRectF(4, 4, self.width() - 8, self.height() - 8), 10, 10)
        if not self.pixmap.isNull():
            area = QSize(self.width() - 24, self.height() - 54)
            art = self.pixmap.scaled(area, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.FastTransformation)
            # Fit uses widget coordinates, independent of a source image's DPR
            # metadata. The source itself stays untouched.
            art.setDevicePixelRatio(1)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawPixmap((self.width() - art.width()) // 2,
                               8 + (area.height() - art.height()) // 2, art)
        font = _control_font()
        font.setWeight(QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor("#172b50"))
        title = painter.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width() - 16)
        painter.drawText(QRectF(8, self.height() - 35, self.width() - 16, 25),
                         Qt.AlignmentFlag.AlignCenter, title)


class SlideSwitch(QCheckBox):
    """Native checkbox semantics with an animated track, without a visual label."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._position = 0.0
        self.setFixedSize(48, 26)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(_control_font())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(48, 26)

    def hitButton(self, position):
        return self.rect().contains(position)

    def _get_position(self):
        return self._position

    def _set_position(self, value):
        self._position = value
        self.update()

    position = Property(float, _get_position, _set_position)

    def _animate(self, checked):
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        off, on = (173, 194, 216, 180), (97, 164, 230, 220)
        track = QColor(*(round(left + (right - left) * self._position) for left, right in zip(off, on)))
        painter.setBrush(track)
        painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
        painter.drawRoundedRect(QRectF(0.5, 0.5, 47, 25), 12.5, 12.5)
        painter.setBrush(QColor(255, 255, 255, 255))
        painter.setPen(QPen(QColor(255, 255, 255, 235), 1))
        painter.drawEllipse(QPointF(13 + 22 * self._position, 13), 9.5, 9.5)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#356a9d"), 1, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(QRectF(1.5, 1.5, 45, 23), 11.5, 11.5)


class ColorButton(QAbstractButton):
    """A circular swatch, optionally checkable for use in settings."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 44)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.set_color(color)

    def set_color(self, color: str):
        if not isinstance(color, str) or not QColor(color).isValid():
            raise ValueError("无效的高亮颜色")
        self.color = color
        self._color = QColor(color)
        self.setAccessibleName(f"高亮颜色 {color}")
        self.setToolTip(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        if self.underMouse() or self.isDown():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 145))
            painter.drawEllipse(QRectF(0.5, 0.5, 43, 43))
        painter.setBrush(self._color)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 1.2))
        painter.drawEllipse(QRectF(4, 4, 36, 36))
        if self.isChecked() or self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#537fac"), 1.5))
            painter.drawEllipse(QRectF(1, 1, 42, 42))
        if self.isChecked():
            check = QPainterPath()
            check.moveTo(16, 22)
            check.lineTo(20, 26)
            check.lineTo(29, 17)
            painter.setPen(QPen(QColor("#172b50"), 1.8, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(check)


class HighlightPalette(QWidget):
    """A disposable native-glass popup that emits one highlight choice."""

    color_selected = Signal(object)

    def __init__(self, colors: list[str], parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setFont(_control_font())
        self.setAccessibleName("高亮颜色")
        self.setMinimumWidth(300)
        self.blur = None
        self._blur_sync = QTimer(self)
        self._blur_sync.setSingleShot(True)
        self._blur_sync.timeout.connect(self._sync_blur)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(8)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        layout.addLayout(row)
        self.color_buttons = []
        for color in colors:
            button = ColorButton(color, self)
            button.clicked.connect(lambda checked=False, color=color: self._select(color))
            self.color_buttons.append(button)
            row.addWidget(button)
        separator = QFrame(self)
        separator.setFixedHeight(1)
        separator.setStyleSheet("background: rgba(105,144,188,90); border: none;")
        layout.addWidget(separator)
        self.clear_button = QToolButton(self)
        self.clear_button.setText("清除高亮")
        self.clear_button.setAccessibleName("清除高亮")
        self.clear_button.setToolTip("清除选区高亮")
        self.clear_button.setFixedHeight(32)
        self.clear_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.clear_button.setStyleSheet(
            "QToolButton { color:#172b50; font-family:'Microsoft YaHei UI'; font-size:15px;"
            " background:transparent; border:1px solid transparent; border-radius:7px; padding:0;"
            " min-height:30px; max-height:30px; }"
            "QToolButton:hover { background:rgba(255,255,255,145); }"
            "QToolButton:focus { border-color:#608fbd; }"
        )
        self.clear_button.clicked.connect(lambda: self._select(None))
        layout.addWidget(self.clear_button)

    def _select(self, color):
        self.color_selected.emit(color)
        self.close()

    def show_at(self, point: QPoint):
        self.layout().activate()
        self.adjustSize()
        screen = QApplication.screenAt(point) or (self.parentWidget().screen() if self.parentWidget()
                                                  else QApplication.primaryScreen())
        area = screen.availableGeometry()
        self.move(max(area.left(), min(point.x(), area.right() - self.width() + 1)),
                  max(area.top(), min(point.y(), area.bottom() - self.height() + 1)))
        self.show()
        (self.color_buttons[0] if self.color_buttons else self.clear_button).setFocus()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor(232, 246, 255, 220))
        gradient.setColorAt(1, QColor(201, 226, 249, 210))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(255, 255, 255, 235), 1.2))
        painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 12, 12)

    def showEvent(self, event):
        super().showEvent(event)
        self.blur = WindowBlur(int(self.winId()))
        self._blur_sync.start(0)

    def _sync_blur(self):
        if self.blur is not None and self.isVisible():
            self.blur.sync(radius=round(12 * self.devicePixelRatioF()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.blur is not None:
            self._blur_sync.start(0)

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.blur is not None:
            self._blur_sync.start(0)

    def hideEvent(self, event):
        self._blur_sync.stop()
        if self.blur is not None:
            self.blur.close()
            self.blur = None
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)
