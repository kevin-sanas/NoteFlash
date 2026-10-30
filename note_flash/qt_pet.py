"""Desktop pet rendered directly from the user's approved transparent artwork.

The original PNG stays intact. Reference-based supplementary frames provide
real gait, blink and mouth articulation; the controller owns their timing.
"""

import math
import ctypes
import json
import os
from pathlib import Path
import time

from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .pet_behavior import PetBehavior

if os.name == 'nt':
    from ctypes import wintypes
    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _user32.WindowFromPoint.argtypes = [wintypes.POINT]
    _user32.WindowFromPoint.restype = wintypes.HWND
    _user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
    _user32.IsChild.restype = wintypes.BOOL


PET_ASSETS = Path(__file__).resolve().parent.parent / 'assets' / 'pets'
SPECIES = ('cat', 'dog', 'snake', 'raccoon')
# Seated, sleeping, walking, star eyes. Coordinates in the supplied 1262x1246
# atlas follow each silhouette rather than assuming an evenly spaced grid.
POSES = {
    'cat': ((30, 55, 240, 247), (326, 121, 288, 183), (642, 77, 325, 231), (972, 54, 276, 254)),
    'dog': ((23, 352, 260, 247), (312, 426, 310, 173), (641, 356, 310, 245), (975, 347, 273, 254)),
    'snake': ((38, 675, 230, 232), (332, 718, 275, 189), (639, 672, 314, 235), (981, 675, 254, 234)),
    'raccoon': ((25, 950, 287, 251), (316, 994, 311, 209), (633, 963, 336, 242), (975, 936, 274, 267)),
}


class PetWidget(QWidget):
    clicked = Signal()
    position_moved = Signal(int)
    position_changed = Signal(int)
    drag_started = Signal()
    drag_finished = Signal()
    menu_requested = Signal(QPoint)

    def __init__(self, species='cat', parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.scale = 1.0
        self.setFixedSize(176, 140)
        self.setWindowTitle('Note Flash · 桌面宠物')
        self.setToolTip('单击打开笔记 · 拖动调整位置 · 右键设置或退出')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.species = ''
        self.direction = 1
        self.walking = False
        self.panel_open = False
        self.auto_move = True
        self._subpixel_x = 0.0
        self._press_pos = None
        self._press_x = 0
        self._dragged = False
        self._occluded = False
        self.set_species(species if species in SPECIES else 'cat')
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._occlusion_timer = QTimer(self)
        self._occlusion_timer.setInterval(1000)
        self._occlusion_timer.timeout.connect(self._check_occlusion)
        self._sync_timer()

    def _sync_timer(self):
        if not hasattr(self, '_timer'):
            return
        if not self.isVisible():
            self._timer.stop()
            return
        moving = self.walking and not self.panel_open
        active = self._frame.action in ('typing', 'highlight', 'delete')
        visible = self.isVisible() and not self._occluded
        if not visible and not (moving or active):
            self._timer.stop()
            return
        interval = (33 if visible else 250) if moving or active else 500
        if not self._timer.isActive() or self._timer.interval() != interval:
            self._timer.start(interval)

    def set_occluded(self, occluded):
        """Set only for known full occlusion; partial coverage remains visible."""
        occluded = bool(occluded)
        if self._occluded != occluded:
            self._occluded = occluded
            self._animate()

    def _check_occlusion(self):
        if os.name != 'nt' or QGuiApplication.platformName() != 'windows' or not self.isVisible():
            return
        hwnd = int(self.winId())
        if not hwnd:
            return
        points = ((.5, .58), (.4, .62), (.6, .62), (.45, .70), (.55, .70))
        hits = []
        native_hits = []
        for fx, fy in points:
            pos = self.mapToGlobal(QPoint(round(self.width() * fx), round(self.height() * fy)))
            screen = QGuiApplication.screenAt(pos) or self.screen()
            if screen:
                origin = screen.geometry().topLeft()
                ratio = screen.devicePixelRatio()
                pos = QPoint(round(origin.x() + (pos.x() - origin.x()) * ratio),
                             round(origin.y() + (pos.y() - origin.y()) * ratio))
            hit = _user32.WindowFromPoint(wintypes.POINT(pos.x(), pos.y()))
            native_hits.append(hit)
            hits.append(hit == hwnd or bool(hit and _user32.IsChild(hwnd, hit)))
        if any(native_hits):
            self.set_occluded(not any(hits))

    def showEvent(self, event):
        super().showEvent(event)
        # Resume the current pose without replaying off-screen travel.
        self._frame = self.behavior.tick(time.monotonic())
        self._occlusion_timer.start()
        self._check_occlusion()
        self._sync_timer()
        self.update()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._occlusion_timer.stop()
        self._sync_timer()

    def set_scale(self, scale):
        center = self.x() + self.width() / 2
        self.scale = scale
        self.setFixedSize(round(176 * scale), round(140 * scale))
        if self.isWindow():
            bounds = self.screen().availableGeometry()
            x = max(bounds.left(), min(round(center - self.width()/2), bounds.right() - self.width() + 1))
            self.move(x, bounds.top() + 4)
        self.update()

    def set_species(self, species):
        if species not in SPECIES:
            return
        if not self.species:
            self._motion = json.loads((PET_ASSETS / 'motion.json').read_text(encoding='utf-8'))
            for config in self._motion['species'].values():
                for poses in (config['walk'], config['expressions']):
                    if len(poses) != 6 or any(not QRectF(0, 0, 1536, 1024).contains(QRectF(*p)) for p in poses):
                        raise ValueError('Invalid pet animation source rectangles')
        sheet = QImage(str(PET_ASSETS / 'approved-atlas.png'))
        if sheet.isNull() or (sheet.width(), sheet.height()) != (1262, 1246) or not sheet.hasAlphaChannel():
            raise ValueError('The approved transparent pet atlas is missing or has an unexpected size')
        self._base_frames = [QPixmap.fromImage(sheet.copy(QRect(*rect))) for rect in POSES[species][:2]]
        self._walk_frames = None
        self._expression_frames = None
        self.species = species
        now = time.monotonic()
        self.behavior = PetBehavior(now=now, direction=self.direction)
        self.behavior.set_wandering(self.walking, now)
        self._frame = self.behavior.set_panel_open(self.panel_open, now)
        self.setAccessibleName({'cat': '橘白小猫', 'dog': '像素小狗', 'snake': '像素小蛇', 'raccoon': '像素小浣熊'}[species])
        self._sync_timer()
        self.update()

    @property
    def _sheet(self):
        """Provide the settings cards' atlas without retaining it in the pet."""
        return QPixmap.fromImage(QImage(str(PET_ASSETS / 'approved-atlas.png')))

    def _load_motion_frames(self, kind):
        filename = self._motion['walk_file' if kind == 'walk' else 'expression_file']
        sheet = QImage(str(PET_ASSETS / filename))
        if sheet.isNull() or not sheet.hasAlphaChannel() or (sheet.width(), sheet.height()) != (1536, 1024):
            raise ValueError('The supplementary pet animation atlas is missing or invalid')
        return [QPixmap.fromImage(sheet.copy(QRect(*rect))) for rect in self._motion['species'][self.species][kind]]

    def set_direction(self, direction):
        self.direction = -1 if direction < 0 else 1
        self._frame = self.behavior.set_direction(self.direction, time.monotonic())
        self.update()

    def can_wander(self):
        return not self.panel_open and self._press_pos is None and not (
            self._frame.action in ('typing', 'highlight', 'delete'))

    def set_walking(self, walking):
        self.walking = bool(walking)
        self._frame = self.behavior.set_wandering(self.walking, time.monotonic())
        self._sync_timer()
        self.update()

    def set_panel_open(self, is_open):
        self.panel_open = bool(is_open)
        self._frame = self.behavior.set_panel_open(self.panel_open, time.monotonic())
        self._sync_timer()
        self.update()

    def react(self, event):
        if event not in ('typing', 'highlight', 'delete'):
            return
        self._frame = self.behavior.react(event, time.monotonic())
        self._sync_timer()
        self.update()

    def _animate(self):
        now = time.monotonic()
        self._frame = self.behavior.tick(now)
        self.direction = self._frame.direction
        if self.auto_move and self.isWindow() and self._press_pos is None and self._frame.delta_x:
            self._subpixel_x += self._frame.delta_x
            pixels = int(self._subpixel_x)
            self._subpixel_x -= pixels
            bounds = self.screen().availableGeometry()
            target = self.x() + pixels
            x = max(bounds.left(), min(target, bounds.right() - self.width() + 1))
            self.move(x, bounds.top() + 4)
            if x != target:
                self._subpixel_x = 0
                self._frame = self.behavior.turn(now)
        self._sync_timer()
        if self.isVisible() and not self._occluded:
            self.update()

    def _current_action(self):
        if self._frame.action == 'attentive':
            return 'open'
        if self._frame.action == 'delete' and self._frame.phase == 'burp':
            return 'burp'
        return self._frame.action

    def _pose(self):
        """Select independently timed drawings, keeping a shared foot anchor."""
        action, phase = self._frame.action, self._frame.phase
        elapsed, local = self._frame.action_elapsed, self._frame.local_elapsed
        config = self._motion['species'][self.species]
        if action == 'rest':
            frame = self._base_frames[1]
            return frame, QRectF(frame.rect()), .43
        if action == 'walk':
            cursor = (elapsed * 1000) % sum(self._motion['walk_ms'])
            index = 5
            for i, duration in enumerate(self._motion['walk_ms']):
                if cursor < duration:
                    index = i
                    break
                cursor -= duration
            if self._walk_frames is None:
                self._walk_frames = self._load_motion_frames('walk')
            frame = self._walk_frames[index]
            return frame, QRectF(frame.rect()), config['walk_scale']
        expression = None
        if action in ('attentive', 'idle'):
            if elapsed % 4.7 > 4.5:
                expression = 0
        elif action == 'typing':
            expression = 0 if elapsed % 3.4 > 3.23 else 1
        elif action == 'highlight':
            expression = 0 if phase == 'start' else 5 if phase == 'loop' else None
        elif action == 'delete':
            if phase == 'eat':
                expression = 1 if local < .15 else 2
            elif phase == 'chew':
                expression = 2 if int(local / .15) % 2 else 3
            elif phase == 'burp':
                expression = 4 if local < .6 else 0
        if expression is None:
            frame = self._base_frames[0]
            return frame, QRectF(frame.rect()), .43
        if self._expression_frames is None:
            self._expression_frames = self._load_motion_frames('expressions')
        frame = self._expression_frames[expression]
        return frame, QRectF(frame.rect()), config['expression_scale']

    def paintEvent(self, event):
        action = self._current_action()
        now = time.monotonic()
        elapsed = self._frame.local_elapsed
        sheet, source, scale = self._pose()
        width, height = round(source.width() * scale), round(source.height() * scale)
        x, bottom = (176 - width) / 2, 131
        bounce, stretch = 0, 1.0
        if action == 'rest':
            stretch = 1 + math.sin(now * 2) * .012
        elif action == 'highlight' and self._frame.phase == 'loop':
            bounce = max(0, math.sin(min(elapsed, .4) * math.pi / .4)) * 6
        elif action == 'burp':
            bounce = max(0, 1 - elapsed / .20) * 2
        painter = QPainter(self)
        painter.scale(self.scale, self.scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.save()
        painter.translate(88, bottom - bounce)
        painter.scale(self.direction if action == 'walk' else 1, stretch)
        painter.drawPixmap(QRectF(-width / 2, -height, width, height), sheet, source)
        painter.restore()

        # Effects are separate from the character artwork. The file disappears
        # into its mouth only after recycle_path has reported success.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if action == 'rest':
            painter.setPen(QColor(211, 237, 255, 210))
            font = QFont('Segoe UI'); font.setPixelSize(15); font.setBold(True)
            painter.setFont(font)
            painter.drawText(round(x + width - 7), round(bottom - height - 8 - math.sin(now * 2) * 2), 'z')
        elif action == 'delete' and self._frame.phase == 'eat' and elapsed > .12:
            progress = min(1.0, (elapsed - .12) / .65)
            size = 24 * (1 - progress * .85)
            mouth_y = bottom - height * .40
            painter.save()
            painter.translate(16 + (88 - 16) * progress,
                              30 + (mouth_y - 30) * progress)
            painter.rotate(-18 * (1 - progress))
            painter.setOpacity(1 - max(0, progress - .85) / .15)
            painter.setPen(QPen(QColor('#5f83ad'), 1.2)); painter.setBrush(QColor('#eff8ff'))
            painter.drawRoundedRect(QRectF(-size / 2, -size / 2, size * .8, size), 2, 2)
            for line in (-.18, .02, .22):
                painter.drawLine(QPoint(round(-size * .32), round(size * line)),
                                 QPoint(round(size * .15), round(size * line)))
            painter.restore()
        elif action == 'burp':
            progress = min(1, elapsed / self.behavior.DELETE_PHASES['burp'])
            painter.setOpacity(1 - progress * progress)
            painter.setPen(QPen(QColor('#9cb8cf'), 1)); painter.setBrush(QColor(241, 250, 255, 220))
            bubble = QRectF(123, 24 - progress * 15, 46, 27)
            painter.drawRoundedRect(bubble, 12, 12)
            font = QFont('Microsoft YaHei UI'); font.setPixelSize(14); painter.setFont(font)
            painter.setPen(QColor('#4a6d8d')); painter.drawText(bubble, Qt.AlignmentFlag.AlignCenter, '嗝~')
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._press_x = self.x()
            self._dragged = False
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        pos = event.globalPosition().toPoint()
        delta = pos.x() - self._press_pos.x()
        if not self._dragged and (abs(delta) > 4 or abs(pos.y() - self._press_pos.y()) > 4):
            self._dragged = True
            self.drag_started.emit()
        if self._dragged:
            screen = QGuiApplication.screenAt(pos) or self.screen()
            if screen:
                bounds = screen.geometry()
                x = max(bounds.left(), min(self._press_x + delta, bounds.right() - self.width() + 1))
                previous = self.pos()
                self.move(x, bounds.top() + 4)
                if self.pos() != previous:
                    self.position_moved.emit(self.x())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            dragged = self._dragged
            self._press_pos = None
            self._dragged = False
            event.accept()
            if dragged:
                # Commit while consumers still suppress drag-related focus loss;
                # the final signal can then recheck focus with our state cleared.
                self.position_changed.emit(self.x())
                self.drag_finished.emit()
            else:
                self.clicked.emit()
        else:
            super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        self._timer.stop()
        self._occlusion_timer.stop()
        super().closeEvent(event)
