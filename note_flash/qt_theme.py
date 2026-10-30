"""Shared ice-blue glass styling and compact, vector-drawn Qt icons."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


APP_STYLE = """
QWidget { color: #172b50; font-family: 'Microsoft YaHei UI', 'Microsoft YaHei', 'Segoe UI'; font-size: 16px; background: transparent; }
QLabel { background: transparent; border: none; }
QPlainTextEdit, QTextEdit { background: transparent; }
QToolButton { border: none; border-radius: 7px; padding: 4px 7px; min-height: 24px; background: transparent; }
QToolButton:hover { background: rgba(255,255,255,95); }
QToolButton:pressed { background: rgba(97,158,228,70); }
QToolButton:focus { border: 1px solid #6799cb; }
QToolButton[compactIcon="true"] { padding: 0; min-height: 36px; min-width: 36px; max-height: 36px; max-width: 36px;
 background: rgba(240,249,255,65); }
QToolButton[compactIcon="true"]:hover { background: rgba(255,255,255,150); }
QToolButton[compactIcon="true"]:pressed { background: rgba(139,191,240,140); }
QToolButton[compactIcon="true"]:focus { border: none; background: rgba(255,255,255,170); }
QPushButton { border: 1px solid rgba(255,255,255,185); border-radius: 7px;
 padding: 8px 16px; min-height: 22px; background: rgba(235,247,255,90); }
QPushButton:hover { background: rgba(255,255,255,165); border-color: rgba(255,255,255,225); }
QPushButton:pressed { background: rgba(164,209,247,160); }
QPushButton:focus { border: 1px solid #528bc5; }
QPushButton[primary="true"] { color: #ffffff; background: #3984d1; border: 1px solid #a9d2f5; }
QPushButton[primary="true"]:hover { background: #2d76c3; border-color: #d9efff; }
QPushButton[primary="true"]:pressed { background: #2366af; }
QPushButton[primary="true"]:focus { border: 2px solid #d6edff; }
QPushButton:disabled { color: #71849b; background: rgba(222,234,246,100); }
QLineEdit { border: 1px solid rgba(118,164,215,95); border-radius: 6px;
 padding: 9px 12px; background: rgba(243,250,255,150); selection-background-color: #a8cfff; }
QLineEdit:focus { border: 1px solid #6fa6e9; background: rgba(247,252,255,125); }
QTabBar::tab { border: none; border-top-left-radius: 8px; border-top-right-radius: 8px;
 background: rgba(179,211,247,70); padding: 6px 10px; margin-right: 3px; min-width: 75px; }
QTabBar::tab:selected { background: rgba(248,252,255,128); }
QTabBar::tab:hover { background: rgba(233,246,255,120); }
QTreeWidget { border: none; background: transparent; outline: none; show-decoration-selected: 1;
 selection-background-color: #bfd7f0; selection-color: #172b50; }
QTreeWidget::item { min-height: 38px; border-radius: 5px; padding: 1px 4px; }
QTreeWidget::item:hover { background: rgba(221,239,255,75); }
QTreeWidget::item:selected { background: #bfd7f0; color: #172b50; border: none; border-radius: 0; }
QTreeWidget::branch:selected { background: #bfd7f0; border: none; border-radius: 0; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 1px; }
QScrollBar::handle:vertical { background: rgba(76,112,155,70); border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 7px; }
QScrollBar::handle:horizontal { background: rgba(76,112,155,70); border-radius: 3px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QMenu { background: #eef6ff; border: 1px solid #b8cee8; border-radius: 6px; padding: 5px; }
QMenu::item { padding: 7px 23px; border-radius: 4px; }
QMenu::item:selected { background: #c9e2ff; }
QDialog { background: transparent; }
QMessageBox, QColorDialog, QFileDialog { background: #e8f2fc; }
QComboBox { background: rgba(255,255,255,145); border: 1px solid #b8cee8; border-radius: 7px; padding: 9px 12px; min-height: 22px; }
QComboBox QAbstractItemView { background: #edf5ff; selection-background-color: #cadff5; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { padding: 9px; border-bottom: 1px solid rgba(113,151,194,45); }
QListWidget::item:selected { background: rgba(161,204,250,85); }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 18px; height: 18px; }
QSlider::groove:horizontal { height: 4px; background: rgba(120,154,193,90); border-radius: 2px; }
QSlider::sub-page:horizontal { background: #80addb; border-radius: 2px; }
QSlider::handle:horizontal { background: #f5fbff; border: 1px solid #6f9dca; width: 18px; margin: -7px 0; border-radius: 9px; }
"""


def icon(kind: str) -> QIcon:
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#28466a"), 1.6))
    if kind in ("close", "plus", "sidebar", "minimize", "refresh"):
        painter.setPen(QPen(QColor("#28466a"), 1.8))
        if kind == "close":
            painter.drawLine(6,6,14,14); painter.drawLine(14,6,6,14)
        elif kind == "plus":
            painter.drawLine(4,10,16,10); painter.drawLine(10,4,10,16)
        elif kind == "minimize":
            painter.drawLine(4,10,16,10)
        elif kind == "refresh":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(4,4,12,12),35*16,290*16)
            painter.drawLine(15,3,16,8); painter.drawLine(11,7,16,8)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(3,4,14,12),2,2); painter.drawLine(8,4,8,16)
    elif kind == "maximize":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(4, 4, 12, 12), 1, 1)
    elif kind == "restore":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(8, 4, 16, 4)
        painter.drawLine(16, 4, 16, 12)
        painter.drawRoundedRect(QRectF(4, 7, 9, 9), 1, 1)
    elif kind == "folder":
        painter.setBrush(QColor("#ffe2a1"))
        path = QPainterPath()
        path.moveTo(2, 6); path.lineTo(2, 4); path.lineTo(8, 4); path.lineTo(10, 6)
        path.lineTo(18, 6); path.lineTo(18, 17); path.lineTo(2, 17); path.closeSubpath()
        painter.drawPath(path)
        painter.setPen(QPen(QColor("#fff8df"), 1))
        painter.drawLine(3, 8, 17, 8)
    elif kind == "search":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(3, 3, 10, 10)); painter.drawLine(12, 12, 17, 17)
    elif kind == "gear":
        # Eight connected teeth give the icon a gear silhouette, rather than rays.
        outline = QPolygonF()
        for tooth in range(8):
            for offset, radius in ((-0.50, 6.0), (-0.31, 8.2), (0.31, 8.2), (0.50, 6.0)):
                angle = (tooth + offset) * math.pi / 4
                outline.append(QPointF(10 + radius * math.cos(angle), 10 + radius * math.sin(angle)))
        painter.setPen(QPen(QColor("#28466a"), 1.25, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QColor(235, 247, 255, 100))
        painter.drawPolygon(outline)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(7.5, 7.5, 5, 5))
    else:
        painter.setBrush(QColor(247, 252, 255, 155))
        path = QPainterPath()
        path.moveTo(5, 2); path.lineTo(12, 2); path.lineTo(16, 6); path.lineTo(16, 18)
        path.lineTo(5, 18); path.closeSubpath(); painter.drawPath(path)
        painter.drawLine(12,2,12,6); painter.drawLine(12,6,16,6)
        painter.drawLine(8,10,13,10); painter.drawLine(8,13,13,13)
    painter.end()
    return QIcon(pixmap)

