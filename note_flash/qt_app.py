"""Qt frontend with per-control glass and local file operations."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import subprocess
import sys
import threading

from PySide6.QtCore import Qt, QRect, QRectF, QPoint, QTimer, Signal, QObject, QEvent, QSize, QUrl
from PySide6.QtGui import QColor, QPainter, QPen, QLinearGradient, QShortcut, QKeySequence, QTextCursor, QIcon, QDesktopServices
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QToolButton, QPushButton, QTabBar, QStackedWidget, QTreeWidget, QTreeWidgetItem,
    QFileDialog, QMessageBox, QMenu, QDialog, QCheckBox,
    QColorDialog, QListWidget, QListWidgetItem, QSizeGrip, QSystemTrayIcon, QSlider, QButtonGroup)

from .core import Document, ExternalChangeError, MoveIncompleteError, WorkspaceStore, create_note, move_path, recycle_path, search_files
from .qt_editor import NoteEditor
from .qt_pet import PetWidget, POSES
from .windows import is_startup_enabled, set_startup_enabled
from .qt_glass import WindowBlur
from . import __version__
from .data_paths import migrate_data_dir, MigrationCleanupError
from installer.uninstall import start_uninstall, cancel_uninstall


ROOT = Path(__file__).resolve().parent.parent
INK = "#172b50"
MUTED = "#294568"
COLORS = ["#ffe8a3", "#ccebdc", "#cedff4", "#f4d1dc", "#e4d7f5"]

from .qt_theme import APP_STYLE as STYLE, icon
from .qt_controls import PetCard, SlideSwitch, HighlightPalette


class IconButton(QToolButton):
    """A 22px icon inside a stable 36px hit target, without text padding."""
    def __init__(self, kind, name, tooltip=None, parent=None):
        super().__init__(parent)
        self.setProperty("compactIcon", True)
        self.setIcon(icon(kind)); self.setIconSize(QSize(22,22)); self.setFixedSize(36,36)
        self.setAccessibleName(name); self.setToolTip(tooltip or name)


class GlassSurface(QWidget):
    """Paint only a translucent material; children keep their own full alpha."""
    def __init__(self, top: QColor, bottom: QColor, radius=10, parent=None):
        super().__init__(parent)
        self.top, self.bottom, self.radius = top, bottom, radius
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, self.top); gradient.setColorAt(1, self.bottom)
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(246,252,255,150),1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5), self.radius, self.radius)


class Header(QWidget):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window().windowHandle().startSystemMove()
            event.accept()


class SearchSignals(QObject):
    ready = Signal(int, list, list)


class NoteTabBar(QTabBar):
    """Use the app's neutral close icon instead of the platform red square."""
    def tabInserted(self, index):
        super().tabInserted(index)
        button = QToolButton(self)
        button.setIcon(icon("close")); button.setIconSize(QSize(20,20))
        button.setFixedSize(30,30); button.setStyleSheet("padding:0;min-height:0;")
        button.setToolTip("关闭标签"); button.setAccessibleName("关闭标签")
        button.clicked.connect(lambda: self.tabCloseRequested.emit(next(
            i for i in range(self.count()) if self.tabButton(i,QTabBar.ButtonPosition.RightSide) is button)))
        self.setTabButton(index, QTabBar.ButtonPosition.RightSide, button)


class GlassDialog(QDialog):
    """Shared readable dialog chrome with the same native glass as the panel."""
    def __init__(self, parent, title, description="", width=560):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(title); self.setMinimumWidth(width)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        self.blur = None
        self._blur_sync = QTimer(self)
        self._blur_sync.setSingleShot(True)
        self._blur_sync.timeout.connect(lambda: self.blur.sync(
            radius=round(14*self.devicePixelRatioF())) if self.blur else None)
        layout = QVBoxLayout(self); layout.setContentsMargins(26,22,26,24); layout.setSpacing(18)
        header = Header(self); row = QHBoxLayout(header); row.setContentsMargins(0,0,0,0)
        heading = QLabel(title); heading.setStyleSheet("font-size:28px;font-weight:600;"); row.addWidget(heading,1)
        close = IconButton("close","关闭")
        close.clicked.connect(self.reject); row.addWidget(close); layout.addWidget(header)
        if description:
            hint = QLabel(description); hint.setWordWrap(True); hint.setStyleSheet(f"color:{MUTED};font-size:14px;")
            layout.addWidget(hint)
        self.body = QVBoxLayout(); self.body.setSpacing(12); layout.addLayout(self.body)

    def paintEvent(self, event):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient=QLinearGradient(0,0,self.width(),self.height())
        gradient.setColorAt(0,QColor(233,246,255,224)); gradient.setColorAt(1,QColor(207,228,250,215))
        painter.setBrush(gradient); painter.setPen(QPen(QColor(255,255,255,225),1.2))
        painter.drawRoundedRect(QRectF(1,1,self.width()-2,self.height()-2),14,14)

    def showEvent(self, event):
        super().showEvent(event)
        self.layout().activate()
        self.adjustSize()
        self.blur=WindowBlur(int(self.winId()))
        self._blur_sync.start(0)
        center=self.parentWidget().frameGeometry().center()
        area=self.parentWidget().screen().availableGeometry()
        self.move(max(area.left(),min(center.x()-self.width()//2,area.right()-self.width()+1)),
                  max(area.top(),min(center.y()-self.height()//2,area.bottom()-self.height()+1)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.blur:
            # Qt delivers this event before the HWND has its final geometry.
            # Reading GetWindowRect here cached a 447px mask for a 482px dialog.
            self._blur_sync.start(0)

    def hideEvent(self, event):
        self._blur_sync.stop()
        if self.blur:self.blur.close();self.blur=None
        super().hideEvent(event)


def prompt_text(parent, title, label, text=""):
    dialog=GlassDialog(parent,title)
    field=QLineEdit(text); field.setObjectName("nameInput")
    caption=QLabel(label); caption.setBuddy(field)
    dialog.body.addWidget(caption); dialog.body.addWidget(field)
    actions=QHBoxLayout(); actions.addStretch()
    cancel=QPushButton("取消"); cancel.clicked.connect(dialog.reject); actions.addWidget(cancel)
    confirm=QPushButton("创建" if title=="新建笔记" else "保存名称")
    confirm.setObjectName("confirmName"); confirm.setProperty("primary",True); confirm.setDefault(True)
    confirm.setEnabled(bool(text.strip())); field.textChanged.connect(lambda value:confirm.setEnabled(bool(value.strip())))
    confirm.clicked.connect(dialog.accept); actions.addWidget(confirm); dialog.body.addLayout(actions)
    field.selectAll(); field.setFocus()
    accepted=dialog.exec()==QDialog.DialogCode.Accepted
    result=field.text(); dialog.deleteLater()
    return result,accepted


class NoteWindow(QWidget):
    def __init__(self, state_dir: Path, *, preview=False, tray=True, material="blur"):
        super().__init__()
        self.preview = preview
        self.app_home=Path(sys.executable).parent if getattr(sys,"frozen",False) else ROOT
        self.store = WorkspaceStore(Path(state_dir) / "state.json")
        self.startup_error = None
        try:
            self.state = self.store.load()
        except (OSError, ValueError) as exc:
            self.state = {}
            self.startup_error = str(exc)
        self.roots = [Path(p) for p in self.state.get("folders", [])]
        self.highlights = self.state.get("highlights", {})
        self.colors = self.state.get("colors", COLORS.copy())
        self.entries: dict[str, dict] = {}
        self.dialog_count = 0
        self._pet_dragging = False
        self.closing = False
        self.backdrop = None
        self.active = None
        self.search_serial = 0
        self.search_workers = []
        self.search_signals = SearchSignals(self)
        self.search_signals.ready.connect(self._search_ready)
        self.setWindowTitle("Note Flash · Glass Preview" if preview else "Note Flash")
        self.app_icon=QIcon(str(ROOT/"assets"/"branding"/"note-flash.ico"))
        self.setWindowIcon(self.app_icon)
        QApplication.instance().setWindowIcon(self.app_icon)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setStyleSheet(STYLE)
        self.setMinimumSize(720, 440)
        self.resize(*self.state.get("panel_size", [1000, 700]))
        self.pet = PetWidget(self.state.get("species", "cat"))
        self.pet.setWindowIcon(self.app_icon)
        self.pet.set_scale(self.state.get("pet_scale",100)/100)
        self.pet.move(int(self.state.get("pet_x", 470)), 4)
        self.pet.clicked.connect(self.toggle_panel)
        self.pet.drag_started.connect(lambda:setattr(self,"_pet_dragging",True))
        self.pet.position_moved.connect(self.follow_pet)
        self.pet.position_changed.connect(lambda x: self.persist())
        self.pet.drag_finished.connect(self.finish_pet_drag)
        self.pet.menu_requested.connect(self.pet_menu)
        self._build_ui()
        self._restore_session()
        self.backdrop = WindowBlur(int(self.winId()), material)
        self.sync_timer = QTimer(self)
        self.sync_timer.setSingleShot(True)
        self.sync_timer.timeout.connect(self.sync_backdrop)
        self.sync_timer.start(0)
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(2000)
        self.watch_timer.timeout.connect(self.watch_files)
        self.wander_timer = QTimer(self)
        self.wander_timer.setSingleShot(True)
        self.wander_timer.timeout.connect(self.wander)
        self.wander_timer.start(0)
        self.direction = 1
        self.tray = None
        if tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.app_icon, self)
            menu = QMenu(self)
            menu.addAction("打开笔记", self.show_panel)
            menu.addAction("设置", self.settings)
            menu.addSeparator(); menu.addAction("彻底退出", self.quit)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.show_panel() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
            self.tray.setToolTip("Note Flash")
            self.tray.show()
        self._shortcuts = []
        for key, callback in [("Ctrl+S", self.save_current), ("Ctrl+F", self.find_dialog),
                              ("Ctrl+H", self.find_dialog), ("Ctrl+N", self.new_note),
                              ("Ctrl+W", self.close_current), ("F3", self.find_next)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)
        self.pet.show()
        if self.startup_error:
            QTimer.singleShot(0, lambda: self.error("状态读取失败", self.startup_error))

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(11, 10, 11, 8)
        outer.setSpacing(0)
        header = Header()
        head = QHBoxLayout(header)
        head.setContentsMargins(0, 0, 0, 0); head.setSpacing(7)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索笔记…")
        self.search.setFixedWidth(245)
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.returnPressed.connect(self.start_search)
        self.search.textChanged.connect(lambda value: self.show_current_page() if not value else None)
        head.addWidget(self.search, 0, Qt.AlignmentFlag.AlignTop)
        self.tabbar = NoteTabBar()
        self.tabbar.setExpanding(False)
        self.tabbar.setDrawBase(False)
        self.tabbar.setTabsClosable(False)
        self.tabbar.setMovable(False)
        self.tabbar.setUsesScrollButtons(True)
        self.tabbar.currentChanged.connect(self.tab_changed)
        self.tabbar.tabBarClicked.connect(lambda i: self.show_current_page())
        self.tabbar.tabCloseRequested.connect(self.close_tab)
        head.addWidget(self.tabbar, 1)
        new = IconButton("plus","新建笔记","新建笔记 · Ctrl+N"); new.clicked.connect(self.new_note)
        head.addWidget(new)
        sidebar_button = IconButton("sidebar","显示或收起文件夹"); sidebar_button.clicked.connect(self.toggle_sidebar)
        head.addWidget(sidebar_button)
        settings = IconButton("gear","设置"); settings.clicked.connect(self.settings)
        head.addWidget(settings)
        minimize = IconButton("minimize","收起面板"); minimize.clicked.connect(self.hide_panel)
        head.addWidget(minimize)
        self.maximize_button=IconButton("maximize","最大化")
        self.maximize_button.clicked.connect(self.toggle_maximized);head.addWidget(self.maximize_button)
        close = IconButton("close","关闭面板","收起，宠物继续运行"); close.clicked.connect(self.hide_panel)
        head.addWidget(close)
        outer.addWidget(header)
        content = QHBoxLayout(); content.setSpacing(7); content.setContentsMargins(0,0,0,0)
        self.sidebar = GlassSurface(QColor(177,210,248,46), QColor(164,202,244,22), radius=9)
        self.sidebar.setFixedWidth(245)
        side = QVBoxLayout(self.sidebar); side.setContentsMargins(6,13,5,8); side.setSpacing(6)
        caption = QHBoxLayout(); caption.addWidget(QLabel("文件夹")); caption.addStretch()
        add = IconButton("plus","添加本地文件夹"); add.clicked.connect(self.add_folder); caption.addWidget(add)
        side.addLayout(caption)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True); self.tree.setIndentation(17)
        self.tree.setUniformRowHeights(True); self.tree.setRootIsDecorated(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemExpanded.connect(self.expand_folder)
        self.tree.itemDoubleClicked.connect(self.tree_open)
        self.tree.itemActivated.connect(self.tree_open)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        side.addWidget(self.tree,1)
        foot = QHBoxLayout()
        create = QToolButton(); create.setIcon(icon("plus")); create.setText("新建"); create.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); create.clicked.connect(self.new_note); foot.addWidget(create)
        foot.addStretch()
        refresh = IconButton("refresh","刷新文件树"); refresh.clicked.connect(self.refresh_tree); foot.addWidget(refresh)
        side.addLayout(foot)
        content.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        self.stack.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.stack.setAutoFillBackground(False)
        content.addWidget(self.stack,1)
        outer.addLayout(content,1)
        self.empty = GlassSurface(QColor(252,255,255,109), QColor(237,247,255,62), radius=10)
        blank = QVBoxLayout(self.empty); blank.setContentsMargins(27,23,27,23)
        title = QLabel("打开你的笔记"); title.setStyleSheet("font-size: 22px; font-weight: 650;")
        blank.addWidget(title)
        hint = QLabel("添加本地文件夹，编辑 TXT 或 Markdown。"); hint.setStyleSheet(f"color:{MUTED};")
        blank.addWidget(hint)
        add_folder = QPushButton("添加文件夹"); add_folder.setFixedWidth(120); add_folder.clicked.connect(self.add_folder)
        blank.addWidget(add_folder); blank.addStretch()
        self.stack.addWidget(self.empty)
        self.results_page = GlassSurface(QColor(252,255,255,110), QColor(238,248,255,60), radius=10)
        results_layout = QVBoxLayout(self.results_page); results_layout.setContentsMargins(24,20,20,12)
        heading = QLabel("搜索结果"); heading.setStyleSheet("font-size:22px; font-weight:650;"); results_layout.addWidget(heading)
        self.results_count = QLabel(); results_layout.addWidget(self.results_count)
        self.results = QListWidget(); self.results.itemActivated.connect(self.open_result); self.results.itemClicked.connect(self.open_result)
        results_layout.addWidget(self.results,1)
        self.stack.addWidget(self.results_page)
        footer = QHBoxLayout(); footer.setContentsMargins(6,4,0,0)
        branding=QVBoxLayout();branding.setSpacing(3);branding.setContentsMargins(0,2,12,0)
        github=QPushButton("GitHub");github.setObjectName("githubButton")
        github.setAccessibleName("在浏览器打开 NoteFlash GitHub 仓库")
        github.setIcon(QIcon(str(ROOT/"assets"/"branding"/"github-mark.svg")));github.setIconSize(QSize(20,20))
        github.setFixedSize(112,34);github.setCursor(Qt.CursorShape.PointingHandCursor)
        github.setStyleSheet("QPushButton { padding:0;min-width:110px;max-width:110px;min-height:32px;max-height:32px;"
                            "border:1px solid rgba(255,255,255,220);border-radius:17px;"
                            "color:#172b50;background:rgba(244,251,255,170);font-weight:600; }"
                            "QPushButton:hover { background:rgba(255,255,255,230); }")
        github.clicked.connect(lambda:QDesktopServices.openUrl(QUrl("https://github.com/kevin-sanas/NoteFlash")))
        branding.addWidget(github)
        version=QLabel(f"版本 {__version__}");version.setObjectName("versionLabel")
        version.setAlignment(Qt.AlignmentFlag.AlignHCenter);version.setStyleSheet(f"color:{MUTED};font-size:12px;")
        branding.addWidget(version);footer.addLayout(branding)
        self.status = QLabel("本地文件 · 输入停顿后自动保存")
        self.status.setStyleSheet(f"color:{MUTED}; font-size:13px;")
        self.status.setMinimumWidth(0)
        footer.addWidget(self.status,1)
        self.caret_label = QLabel("Plain Text"); self.caret_label.setStyleSheet(f"color:{MUTED}; font-size:13px;")
        footer.addWidget(self.caret_label)
        save = QToolButton(); save.setText("保存"); save.setToolTip("Ctrl+S"); save.clicked.connect(self.save_current); footer.addWidget(save)
        grip = QSizeGrip(self); grip.setFixedSize(13,13); footer.addWidget(grip,0,Qt.AlignmentFlag.AlignBottom)
        outer.addLayout(footer)
        self.sidebar.setVisible(self.state.get("sidebar",True))
        self.refresh_tree()

    def paintEvent(self,event):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient=QLinearGradient(0,0,self.width(),self.height())
        gradient.setColorAt(0,QColor(225,242,255,170)); gradient.setColorAt(0.5,QColor(209,230,252,160)); gradient.setColorAt(1,QColor(220,239,255,166))
        painter.setBrush(gradient); painter.setPen(QPen(QColor(248,253,255,210),1.5))
        painter.drawRoundedRect(QRectF(1,1,self.width()-2,self.height()-2),14,14)
        painter.setPen(QPen(QColor(255,255,255,82),1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(5,5,self.width()-10,self.height()-10),10,10)

    def sync_backdrop(self):
        if self.backdrop and self.backdrop.available:
            self.backdrop.sync(radius=round(14 * self.devicePixelRatioF()))

    def moveEvent(self,event):
        super().moveEvent(event)
        if hasattr(self,"sync_timer"):self.sync_timer.start(0)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,"sync_timer"):self.sync_timer.start(0)

    def event(self,event):
        if event.type()==QEvent.Type.WindowDeactivate and hasattr(self,"preview") and not self.preview:
            QTimer.singleShot(170,self.check_focus)
        return super().event(event)

    def check_focus(self):
        if (not self.isVisible() or self.dialog_count or self._pet_dragging or self.pet._press_pos is not None
                or QApplication.activeModalWidget() or QApplication.activePopupWidget()):
            return
        if QApplication.activeWindow() is None:
            self.hide_panel()

    @contextmanager
    def dialog(self):
        self.dialog_count+=1
        try:
            yield
        finally:
            self.dialog_count-=1

    def error(self,title,detail):
        self.status.setText(str(detail))
        with self.dialog():
            QMessageBox.warning(self,title,str(detail))

    def current_key(self):
        index=self.tabbar.currentIndex()
        return self.tabbar.tabData(index) if index>=0 else None

    def current_entry(self):
        return self.entries.get(self.current_key())

    def follow_pet(self, x):
        if not self.isVisible() or self.isMaximized():return
        area=self.pet.screen().availableGeometry()
        left=max(area.left(),min(x+self.pet.width()//2-self.width()//2,area.right()-self.width()+1))
        top=max(area.top(),min(self.y(),area.bottom()-self.height()+1))
        self.move(left,top)

    def finish_pet_drag(self):
        if self.isVisible() and not QApplication.activeModalWidget():self.activateWindow()
        self._pet_dragging=False
        self.wander()

    def position_panel(self):
        if self.isMaximized():return
        screen=self.pet.screen().availableGeometry()
        x=max(screen.left(), min(self.pet.x()+self.pet.width()//2-self.width()//2,screen.right()-self.width()+1))
        y=max(screen.top(),min(self.pet.y()+self.pet.height()+8,screen.bottom()-self.height()+1))
        self.move(x,y)

    def toggle_maximized(self):
        if self.isMaximized():self.showNormal()
        else:self.showMaximized()
        label="还原" if self.isMaximized() else "最大化"
        self.maximize_button.setIcon(icon("restore" if self.isMaximized() else "maximize"))
        self.maximize_button.setAccessibleName(label);self.maximize_button.setToolTip(label)

    def show_panel(self):
        self.position_panel()
        self.show(); self.raise_(); self.activateWindow()
        self.pet.set_panel_open(True); self.pet.set_walking(False)
        self.sync_backdrop()
        self.watch_files();self.watch_timer.start()
        entry=self.current_entry()
        if entry: entry["editor"].setFocus()

    def hide_panel(self):
        if not self.save_all() or not self.persist(): return False
        if self.backdrop: self.backdrop.hide()
        self.hide(); self.pet.set_panel_open(False)
        self.watch_timer.stop();self.wander()
        return True

    def toggle_panel(self):
        self.hide_panel() if self.isVisible() else self.show_panel()

    def closeEvent(self,event):
        if self.closing: event.accept()
        else:
            self.hide_panel(); event.ignore()

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible()); self.persist()

    def refresh_tree(self):
        self.tree.clear()
        for path in self.roots:
            item=QTreeWidgetItem([path.name or str(path)]); item.setIcon(0,icon("folder"))
            item.setData(0,Qt.ItemDataRole.UserRole,str(path)); self.tree.addTopLevelItem(item)
            if path.is_dir(): QTreeWidgetItem(item,["…"])
            else: item.setText(0,item.text(0)+"（无法访问）")

    def expand_folder(self,item):
        raw=item.data(0,Qt.ItemDataRole.UserRole)
        if not raw or not item.childCount() or item.child(0).data(0,Qt.ItemDataRole.UserRole): return
        item.takeChildren()
        try:
            paths=sorted(Path(raw).iterdir(),key=lambda p:(not p.is_dir(),p.name.casefold()))
            for path in paths:
                if path.is_symlink() or (not path.is_dir() and path.suffix.lower() not in (".txt",".md")): continue
                child=QTreeWidgetItem(item,[path.name]); child.setData(0,Qt.ItemDataRole.UserRole,str(path))
                child.setIcon(0,icon("folder" if path.is_dir() else "document"))
                if path.is_dir(): QTreeWidgetItem(child,["…"])
        except OSError as exc: self.error("文件夹读取失败",exc)

    def tree_open(self,item,column=0):
        value=item.data(0,Qt.ItemDataRole.UserRole)
        if value and Path(value).is_file(): self.open_file(Path(value))

    def selected_path(self):
        item=self.tree.currentItem()
        value=item.data(0,Qt.ItemDataRole.UserRole) if item else None
        return Path(value) if value else None

    def add_folder(self):
        with self.dialog(): chosen=QFileDialog.getExistingDirectory(self,"选择笔记所在文件夹")
        if not chosen:return
        path=Path(chosen).resolve()
        if path not in self.roots:self.roots.append(path)
        self.refresh_tree();self.persist()

    def new_note(self):
        folder=self.selected_path()
        if folder and not folder.is_dir():folder=folder.parent
        if not folder:folder=self.roots[0] if self.roots else None
        if folder is None:
            self.add_folder();folder=self.roots[0] if self.roots else None
        if folder is None:return
        with self.dialog(): name,okay=prompt_text(self,"新建笔记","文件名（.txt 或 .md）：",text="新笔记.txt")
        if not okay or not name:return
        try:path=create_note(folder,name)
        except (OSError,ValueError) as exc:self.error("新建失败",exc);return
        self.refresh_tree();self.open_file(path)

    def open_file(self,path,quiet=False):
        key=str(Path(path).resolve())
        if key in self.entries:
            self.tabbar.setCurrentIndex(self.index_for(key));self.show_current_page();return self.entries[key]
        try:doc=Document.open(Path(key))
        except (OSError,ValueError) as exc:
            if quiet:raise
            self.error("打开失败",exc);return None
        page=GlassSurface(QColor(252,255,255,110),QColor(232,246,255,56),radius=10)
        layout=QVBoxLayout(page);layout.setContentsMargins(25,18,18,13);layout.setSpacing(11)
        toolbar=QHBoxLayout();toolbar.setSpacing(7)
        title=QLabel(doc.path.stem);title.setStyleSheet("font-size:28px;font-weight:600;");toolbar.addWidget(title,1)
        find=IconButton("search","查找与替换","查找 / 替换 · Ctrl+F");find.clicked.connect(self.find_dialog);toolbar.addWidget(find)
        wrap=QCheckBox("换行");wrap.setChecked(self.state.get("wrap",True));toolbar.addWidget(wrap)
        layout.addLayout(toolbar)
        editor=NoteEditor(doc,parent=page,highlights_record=self.highlights.get(key))
        editor.setLineWrapMode(NoteEditor.LineWrapMode.WidgetWidth if wrap.isChecked() else NoteEditor.LineWrapMode.NoWrap)
        wrap.toggled.connect(lambda value:self.set_wrap(editor,value))
        layout.addWidget(editor,1)
        timer=QTimer(self);timer.setSingleShot(True);timer.setInterval(800)
        entry={"doc":doc,"editor":editor,"page":page,"title":title,"timer":timer,"conflict":False,"meta_dirty":False}
        self.entries[key]=entry
        timer.timeout.connect(lambda:self.save_entry(entry,interactive=False))
        editor.edited.connect(lambda:self.edited(entry))
        editor.highlights_changed.connect(lambda:self.highlights_changed(entry))
        editor.palette_requested.connect(lambda position:self.palette_menu(entry,position))
        editor.cursorPositionChanged.connect(self.update_caret)
        self.stack.addWidget(page)
        index=self.tabbar.addTab(doc.path.name);self.tabbar.setTabData(index,key)
        self.tabbar.setCurrentIndex(index);self.active=key;self.show_current_page()
        return entry

    def index_for(self,key):
        return next((i for i in range(self.tabbar.count()) if self.tabbar.tabData(i)==key),-1)

    def tab_changed(self,index):
        key=self.tabbar.tabData(index) if index>=0 else None
        if self.active and self.active!=key and self.active in self.entries:self.save_entry(self.entries[self.active],False)
        self.active=key;self.show_current_page()

    def show_current_page(self):
        entry=self.current_entry()
        self.stack.setCurrentWidget(entry["page"] if entry else self.empty)
        if entry:
            warning=" · 旧高亮未恢复，文件内容已变化" if entry["editor"].highlight_warning else ""
            label="未保存，点击保存处理" if entry["doc"].dirty or entry["conflict"] else "已保存"
            self.status.setText(label+warning+" · "+entry["doc"].encoding)
            self.status.setToolTip(str(entry["doc"].path))
        self.update_caret()

    def update_caret(self):
        entry=self.current_entry()
        if entry:
            cursor=entry["editor"].textCursor()
            self.caret_label.setText(f"Ln {cursor.blockNumber()+1}, Col {cursor.positionInBlock()+1}     Plain Text")

    def set_wrap(self,editor,value):
        editor.setLineWrapMode(NoteEditor.LineWrapMode.WidgetWidth if value else NoteEditor.LineWrapMode.NoWrap)
        self.state["wrap"]=value;self.persist()

    def edited(self,entry):
        self.tabbar.setTabText(self.index_for(str(entry["doc"].path)),"● "+entry["doc"].path.name)
        self.status.setText("正在编辑 · 等待自动保存")
        self.pet.react("typing");entry["timer"].start()

    def highlights_changed(self,entry):
        entry["meta_dirty"]=True
        self.pet.react("highlight");self.save_entry(entry,False)

    def palette_menu(self,entry,position):
        previous=getattr(self,"highlight_palette",None)
        if previous:previous.close();previous.deleteLater()
        self.highlight_palette=HighlightPalette(self.colors,self)
        self.highlight_palette.color_selected.connect(entry["editor"].apply_highlight)
        self.highlight_palette.show_at(position)

    def save_entry(self,entry,interactive=True):
        doc=entry["doc"];editor=entry["editor"]
        if not doc.dirty and not entry["meta_dirty"] and not entry["conflict"]:return True
        try:
            if doc.dirty or entry["conflict"]:editor.save()
        except ExternalChangeError:
            entry["conflict"]=True;self.status.setText("文件已被外部修改，未覆盖；点击保存选择处理方式")
            if not interactive:return False
            with self.dialog():
                choice=QMessageBox.question(self,"外部修改冲突",f"{doc.path.name} 已被其他程序修改。\n是：用当前内容覆盖外部版本\n否：放弃当前内容并重新读取\n取消：保留编辑器内容",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)
            if choice==QMessageBox.StandardButton.Cancel:return False
            try:
                if choice==QMessageBox.StandardButton.Yes:editor.save(force=True)
                else:editor.reload();editor.restore_highlights(self.highlights.get(str(doc.path),{}))
            except (OSError,ValueError) as exc:self.error("保存 / 读取失败",exc);return False
        except (OSError,ValueError) as exc:
            self.status.setText(f"保存失败，内容仍保留：{exc}")
            if interactive:self.error("保存失败",exc)
            return False
        entry["conflict"]=False;entry["meta_dirty"]=False
        if doc.path.suffix.lower()==".txt":self.highlights[str(doc.path)]=editor.snapshot_highlights()
        self.tabbar.setTabText(self.index_for(str(doc.path)),doc.path.name)
        self.status.setText("已保存 · "+doc.encoding)
        return self.persist()

    def save_current(self):
        entry=self.current_entry()
        return self.save_entry(entry) if entry else True

    def save_all(self):
        for key,entry in list(self.entries.items()):
            if not self.save_entry(entry):self.tabbar.setCurrentIndex(self.index_for(key));return False
        return True

    def close_current(self):
        self.close_tab(self.tabbar.currentIndex())

    def close_tab(self,index):
        key=self.tabbar.tabData(index) if index>=0 else None
        if key and self.save_entry(self.entries[key]):self.remove_tab(key);self.persist()

    def remove_tab(self,key):
        entry=self.entries.pop(key);entry["timer"].stop();entry["timer"].deleteLater()
        index=self.index_for(key);self.tabbar.removeTab(index)
        self.stack.removeWidget(entry["page"]);entry["page"].deleteLater()
        self.show_current_page()

    def watch_files(self):
        for key,entry in self.entries.items():
            if entry["conflict"]:continue
            try:changed=entry["doc"].has_external_change()
            except OSError as exc:self.status.setText(str(exc));continue
            if changed:
                entry["conflict"]=True
                self.tabbar.setTabText(self.index_for(key),"⚠ "+entry["doc"].path.name)
                self.status.setText("外部文件发生变化或已移走 · 点击保存处理")

    def _restore_session(self):
        failures=[]
        for saved in self.state.get("tabs",[]):
            try:
                entry=self.open_file(Path(saved["path"]),quiet=True)
                line,column=map(int,saved.get("cursor","1.0").split("."))
                block=entry["editor"].document().findBlockByNumber(line-1)
                if block.isValid():
                    cursor=entry["editor"].textCursor();cursor.setPosition(min(block.position()+column,entry["editor"].document().characterCount()-1));entry["editor"].setTextCursor(cursor)
            except (OSError,ValueError) as exc:failures.append(str(exc))
        active=self.state.get("active")
        if active in self.entries:self.tabbar.setCurrentIndex(self.index_for(active))
        if failures:QTimer.singleShot(0,lambda:self.error("部分文件无法恢复","\n".join(failures)))

    def persist(self):
        if self.closing:return True
        tabs=[]
        for key,entry in self.entries.items():
            cursor=entry["editor"].textCursor()
            tabs.append({"path":key,"cursor":f"{cursor.blockNumber()+1}.{cursor.positionInBlock()}"})
        self.state.update({"folders":[str(p) for p in self.roots],"tabs":tabs,"active":self.current_key(),
                           "highlights":self.highlights,"colors":self.colors,"pet_x":self.pet.x(),
                           "panel_size":[self.normalGeometry().width(),self.normalGeometry().height()] if self.isMaximized() else [self.width(),self.height()],"sidebar":not self.sidebar.isHidden()})
        try:self.store.save(self.state)
        except (OSError,ValueError) as exc:self.status.setText(f"设置保存失败：{exc}");return False
        return True

    def find_dialog(self):
        if not self.current_entry():return
        if getattr(self,"find_window",None) and self.find_window.isVisible():self.find_window.raise_();return
        dialog=GlassDialog(self,"查找与替换","在当前笔记中查找文字，或替换匹配内容。",width=620)
        self.find_window=dialog;layout=dialog.body
        self.find_input=QLineEdit();self.find_input.setPlaceholderText("输入要查找的文字")
        find_label=QLabel("查找内容");find_label.setBuddy(self.find_input)
        layout.addWidget(find_label);layout.addWidget(self.find_input)
        self.replace_input=QLineEdit();self.replace_input.setPlaceholderText("输入替换文字，可留空")
        replace_label=QLabel("替换为");replace_label.setBuddy(self.replace_input)
        layout.addWidget(replace_label);layout.addWidget(self.replace_input)
        self.find_feedback=QLabel("查找会从当前光标继续，末尾后回到开头。")
        self.find_feedback.setWordWrap(True);self.find_feedback.setStyleSheet(f"color:{MUTED};font-size:14px;")
        layout.addWidget(self.find_feedback)
        buttons=QHBoxLayout()
        for label,callback in [("下一个",self.find_next),("替换选中",self.replace_one),("全部替换",self.replace_all)]:
            button=QPushButton(label);button.clicked.connect(callback);button.setEnabled(False)
            self.find_input.textChanged.connect(lambda value,b=button:b.setEnabled(bool(value)))
            buttons.addWidget(button)
        layout.addLayout(buttons);self.find_input.returnPressed.connect(self.find_next)
        dialog.show();self.find_input.setFocus()
        def closed_find():
            self.find_query=self.find_input.text();self.find_window=None
        dialog.finished.connect(closed_find)
        dialog.finished.connect(dialog.deleteLater)

    def find_next(self):
        entry=self.current_entry()
        query=self.find_input.text() if getattr(self,"find_window",None) else getattr(self,"find_query","")
        if entry and query:
            found=entry["editor"].find_next(query)
            if getattr(self,"find_window",None):self.find_feedback.setText("已选中匹配文字" if found else "没有找到匹配文字")
            if not found:self.status.setText("没有找到匹配文字")

    def replace_one(self):
        entry=self.current_entry()
        if entry:entry["editor"].replace_selection(self.find_input.text(),self.replace_input.text());self.find_next()

    def replace_all(self):
        entry=self.current_entry()
        if entry:
            message=f"已替换 {entry['editor'].replace_all(self.find_input.text(),self.replace_input.text())} 处"
            self.status.setText(message);self.find_feedback.setText(message)

    def start_search(self):
        for worker,cancel in self.search_workers:cancel.set()
        self.search_workers=[(worker,cancel) for worker,cancel in self.search_workers if worker.is_alive()]
        query=self.search.text().strip()
        if not query:self.show_current_page();return
        if not self.save_all():return
        self.search_serial+=1;serial=self.search_serial;roots=self.roots.copy()
        self.status.setText("正在搜索文件名与正文…")
        cancel=threading.Event()
        def work():
            results,errors=search_files(roots,query,cancelled=cancel.is_set)
            if not cancel.is_set():self.search_signals.ready.emit(serial,results,errors)
        worker=threading.Thread(target=work,daemon=True,name="NoteFlash-search")
        self.search_workers.append((worker,cancel));worker.start()

    def _search_ready(self,serial,results,errors):
        if self.closing or serial!=self.search_serial:return
        self.results.clear()
        for result in results:
            path=Path(result["path"])
            item=QListWidgetItem(icon("document"),f"{path.name}\n{path.parent}\n{result['snippet']}")
            item.setData(Qt.ItemDataRole.UserRole,result);self.results.addItem(item)
        self.results_count.setText(f"{len(results)} 个结果"+(f" · {len(errors)} 项读取失败" if errors else ""))
        self.stack.setCurrentWidget(self.results_page);self.status.setText("搜索完成")
        if errors:self.error("搜索未覆盖所有文件","\n".join(errors[:30]))

    def open_result(self,item):
        result=item.data(Qt.ItemDataRole.UserRole)
        entry=self.open_file(Path(result["path"]))
        if entry and result["line"]:
            block=entry["editor"].document().findBlockByNumber(result["line"]-1)
            if block.isValid():
                cursor=entry["editor"].textCursor();cursor.setPosition(min(block.position()+result["column"]-1,entry["editor"].document().characterCount()-1));entry["editor"].setTextCursor(cursor);entry["editor"].ensureCursorVisible()

    def tree_menu(self,point):
        item=self.tree.itemAt(point)
        if not item:return
        self.tree.setCurrentItem(item);path=self.selected_path()
        if not path:return
        menu=QMenu(self)
        menu.addAction("新建笔记",self.new_note);menu.addSeparator()
        menu.addAction("重命名",lambda:self.rename_path(path))
        menu.addAction("移动到…",lambda:self.move_dialog(path))
        menu.addAction("移入回收站…",lambda:self.delete_path(path))
        if path in self.roots:menu.addSeparator();menu.addAction("从列表移除（不删除）",lambda:self.remove_root(path))
        with self.dialog():menu.exec(self.tree.viewport().mapToGlobal(point))

    def remove_root(self,path):
        self.roots.remove(path);self.refresh_tree();self.persist()

    def rename_path(self,path):
        with self.dialog():name,okay=prompt_text(self,"重命名","新的名称：",text=path.name)
        if not okay or not name or name==path.name:return
        if any(c in name for c in '<>:"/\\|?*') or name in (".","..") or name.rstrip(" .")!=name:
            self.error("名称无效","请输入有效的 Windows 文件名");return
        if path.is_file() and Path(name).suffix.lower() not in (".txt",".md"):
            self.error("名称无效","需保留 .txt 或 .md 扩展名");return
        self.relocate(path,path.with_name(name))

    def move_dialog(self,path):
        with self.dialog():chosen=QFileDialog.getExistingDirectory(self,"移动到")
        if chosen:self.relocate(path,Path(chosen)/path.name)

    def relocate(self,old,new):
        old,new=Path(old).resolve(),Path(new).resolve()
        if old==new or not self.save_all():return
        incomplete=None
        try:move_path(old,new)
        except MoveIncompleteError as exc:incomplete=exc
        except (OSError,ValueError) as exc:self.error("移动失败",exc);return
        for key in list(self.entries):
            path=Path(key)
            if path==old or path.is_relative_to(old):
                target=new/path.relative_to(old) if path!=old else new
                entry=self.entries.pop(key);entry["doc"].path=target;entry["title"].setText(target.stem)
                index=self.index_for(key);self.tabbar.setTabData(index,str(target));self.tabbar.setTabText(index,target.name)
                self.entries[str(target)]=entry
        for key in list(self.highlights):
            path=Path(key)
            if path==old or path.is_relative_to(old):
                target=new/path.relative_to(old) if path!=old else new
                self.highlights[str(target)]=self.highlights.pop(key)
        self.roots=[new/p.relative_to(old) if p.is_relative_to(old) else p for p in self.roots]
        self.active=self.current_key();self.refresh_tree();self.persist()
        if incomplete:self.error("移动未完全完成",str(incomplete)+"\n已打开文件已关联到完整目标副本。")

    def delete_path(self,path):
        text=f"将 {path.name} 移入 Windows 回收站？"
        if path.is_dir():text+="\n其中所有类型的文件都会一并移入回收站。"
        with self.dialog():confirmed=QMessageBox.question(self,"确认删除",text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if confirmed!=QMessageBox.StandardButton.Yes or not self.save_all():return
        try:recycle_path(path)
        except (OSError,ValueError) as exc:self.error("删除失败",exc);return
        for key in list(self.entries):
            if Path(key)==path or Path(key).is_relative_to(path):self.remove_tab(key)
        self.roots=[p for p in self.roots if not (p==path or p.is_relative_to(path))]
        self.pet.react("delete");self.refresh_tree();self.persist()

    def settings(self):
        dialog=GlassDialog(self,"设置","调整桌面伙伴与笔记偏好。更改会自动保存。",width=510)
        dialog.setMinimumHeight(690)
        layout=dialog.body;layout.setSpacing(14)
        layout.addWidget(QLabel("宠物形象"))
        cards=QHBoxLayout();cards.setSpacing(8)
        group=QButtonGroup(dialog);group.setExclusive(True)
        atlas=self.pet._sheet
        for label,value in [("橘白小猫","cat"),("小狗","dog"),("小蛇","snake"),("小浣熊","raccoon")]:
            card=PetCard(value,label,atlas.copy(QRect(*POSES[value][0])))
            card.setObjectName(f"petCard_{value}");card.setChecked(value==self.pet.species)
            group.addButton(card);cards.addWidget(card)
            def change_species(checked,species=value):
                if checked:self.pet.set_species(species);self.state["species"]=species;self.persist()
            card.clicked.connect(change_species)
        layout.addLayout(cards)
        scale_caption=QHBoxLayout();scale_caption.addWidget(QLabel("宠物大小"));scale_caption.addStretch()
        scale_value=QLabel(f"{self.state.get('pet_scale',100)}%");scale_value.setObjectName("petScaleValue")
        scale_caption.addWidget(scale_value);layout.addLayout(scale_caption)
        scale_row=QHBoxLayout();scale_row.setSpacing(14)
        scale=QSlider(Qt.Orientation.Horizontal);scale.setObjectName("petScaleSlider")
        scale.setAccessibleName("宠物大小");scale.setRange(50,200);scale.setSingleStep(10);scale.setPageStep(10)
        scale.setTickInterval(10);scale.setValue(self.state.get("pet_scale",100));scale.setMinimumHeight(28)
        def change_scale(value):
            value=((value+5)//10)*10
            if scale.value()!=value:
                scale.blockSignals(True);scale.setValue(value);scale.blockSignals(False)
            self.pet.set_scale(value/100);self.state["pet_scale"]=value
            scale_value.setText(f"{value}%");self.persist()
            if self.isVisible():self.position_panel()
        scale.valueChanged.connect(change_scale);scale_row.addWidget(scale,1)
        reset_scale=QPushButton("恢复 100%");reset_scale.setObjectName("resetPetScale")
        reset_scale.clicked.connect(lambda:scale.setValue(100));scale_row.addWidget(reset_scale)
        layout.addLayout(scale_row)
        wander_row=QHBoxLayout();wander_row.setSpacing(12)
        wandering=SlideSwitch();wandering.setText("面板收起时沿桌面顶部闲逛")
        wandering.setAccessibleName("桌面闲逛");wandering.setObjectName("wanderSwitch")
        wandering.setChecked(self.state.get("wander",False))
        wandering.toggled.connect(lambda value:(self.state.update(wander=value),self.persist(),self.wander()))
        wander_row.addWidget(wandering);wander_row.addWidget(QLabel("面板收起时沿桌面顶部闲逛"));wander_row.addStretch()
        layout.addLayout(wander_row)
        layout.addWidget(QLabel("高亮颜色"));palette=QHBoxLayout()
        for index,color in enumerate(self.colors):
            button=QPushButton();button.setFixedSize(36,36);button.setToolTip(f"修改高亮颜色 {index+1}")
            button.setAccessibleName(f"高亮颜色 {index+1}")
            button.setStyleSheet(f"background:{color};border:none;border-radius:18px;padding:0;min-width:36px;max-width:36px;min-height:36px;max-height:36px;")
            def choose(checked=False,i=index,b=button):
                picked=QColorDialog.getColor(QColor(self.colors[i]),dialog,"选择高亮颜色")
                if picked.isValid():self.colors[i]=picked.name();b.setStyleSheet(f"background:{picked.name()};border:none;border-radius:18px;padding:0;min-width:36px;max-width:36px;min-height:36px;max-height:36px;");self.persist()
            button.clicked.connect(choose);palette.addWidget(button)
        palette.addStretch();layout.addLayout(palette)
        startup=SlideSwitch();startup.setText("登录 Windows 后自动启动")
        startup.setAccessibleName("开机启动");startup.setObjectName("startupSwitch")
        executable=Path(sys.executable).with_name("pythonw.exe")
        if not executable.exists():executable=Path(sys.executable)
        command=subprocess.list2cmdline([sys.executable] if getattr(sys,"frozen",False) else [str(executable),str(ROOT/"launch.py")])
        if not self.preview:
            try:startup.setChecked(is_startup_enabled(command))
            except OSError as exc:self.status.setText(str(exc))
        startup.setEnabled(not self.preview)
        def toggle_startup(value):
            try:set_startup_enabled(value,command)
            except OSError as exc:startup.blockSignals(True);startup.setChecked(not value);startup.blockSignals(False);self.error("启动项修改失败",exc)
        startup.toggled.connect(toggle_startup)
        startup_row=QHBoxLayout();startup_row.setSpacing(12);startup_row.addWidget(startup)
        startup_row.addWidget(QLabel("登录 Windows 后自动启动"));startup_row.addStretch()
        layout.addLayout(startup_row)
        note=QLabel("预览使用独立数据，不修改已有笔记或启动项。" if self.preview else "正文保存在选定目录，设置与高亮单独保存。")
        note.setWordWrap(True);note.setStyleSheet(f"color:{MUTED};font-size:13px;");layout.addWidget(note)
        management=QPushButton("数据目录与卸载…");management.setObjectName("manageApplication")
        management.clicked.connect(self.manage_application);layout.addWidget(management)
        layout.addStretch()
        done=QPushButton("完成");done.setProperty("primary",True);done.setMinimumWidth(112)
        done.clicked.connect(dialog.accept);layout.addWidget(done,0,Qt.AlignmentFlag.AlignRight)
        with self.dialog():dialog.exec()
        dialog.deleteLater()

    def manage_application(self):
        dialog=GlassDialog(self,"应用管理","笔记始终保存在你选择的文件夹中。",width=590)
        path=QLabel(f"应用数据目录：\n{self.store.path.parent}");path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);dialog.body.addWidget(path)
        relocate=QPushButton("更改应用数据目录…");relocate.setObjectName("changeDataDirectory")
        def choose_directory():
            with self.dialog():chosen=QFileDialog.getExistingDirectory(dialog,"选择专用应用数据目录")
            if chosen and self.change_data_directory(Path(chosen)):
                path.setText(f"应用数据目录：\n{self.store.path.parent}")
        relocate.clicked.connect(choose_directory);dialog.body.addWidget(relocate)
        explanation=QLabel("迁移仅包含设置与高亮记录，不会移动或删除任何笔记。")
        explanation.setWordWrap(True);dialog.body.addWidget(explanation)
        remove=QPushButton("一键卸载软件…");remove.setObjectName("uninstallApplication")
        remove.setEnabled(not self.preview and (self.app_home/"note-flash-install.json").exists() and (self.app_home/"Uninstall.exe").exists())
        remove.clicked.connect(self.confirm_uninstall);dialog.body.addWidget(remove)
        if not remove.isEnabled():
            dialog.body.addWidget(QLabel("独立预览或未安装版本不提供卸载操作。"))
        done=QPushButton("返回");done.clicked.connect(dialog.accept);dialog.body.addWidget(done)
        with self.dialog():dialog.exec()
        dialog.deleteLater()

    def change_data_directory(self,destination):
        if not self.save_all() or not self.persist():return False
        try:
            target=migrate_data_dir(self.store.path.parent,Path(destination),self.roots,
                                    app_home=None if self.preview else self.app_home)
        except MigrationCleanupError as exc:
            self.store=WorkspaceStore(exc.data_dir/"state.json")
            self.error("迁移完成，旧记录未完全清理",exc);return True
        except (OSError,ValueError) as exc:
            self.error("数据目录未更改",exc);return False
        self.store=WorkspaceStore(target/"state.json")
        self.status.setText(f"应用数据已切换到：{target}")
        return True

    def confirm_uninstall(self):
        dialog=GlassDialog(self,"确认卸载 Note Flash","软件将正常退出，随后移除安装文件。所有笔记文件和未知文件都会保留。",width=590)
        clear=QCheckBox("同时清除应用设置与高亮记录（默认保留）")
        clear.setObjectName("clearApplicationData");dialog.body.addWidget(clear)
        explanation=QLabel("勾选后会丢失高亮颜色、笔记高亮位置、标签与偏好；笔记正文不受影响。")
        explanation.setWordWrap(True);dialog.body.addWidget(explanation)
        actions=QHBoxLayout();actions.addStretch()
        cancel=QPushButton("取消");cancel.clicked.connect(dialog.reject);actions.addWidget(cancel)
        confirm=QPushButton("确认卸载");confirm.setObjectName("confirmUninstall");confirm.clicked.connect(dialog.accept);actions.addWidget(confirm)
        dialog.body.addLayout(actions)
        with self.dialog():accepted=dialog.exec()==QDialog.DialogCode.Accepted
        clear_data=clear.isChecked();dialog.deleteLater()
        if accepted:self.request_uninstall(clear_data)

    def request_uninstall(self,clear_data=False):
        if self.preview or not self.save_all() or not self.persist():return False
        try:
            helper=start_uninstall(self.app_home,clear_data=clear_data,wait_pid=os.getpid())
        except (OSError,ValueError,RuntimeError) as exc:
            self.error("无法启动卸载",exc);return False
        if self.quit():return True
        cancel_uninstall(helper)
        return False

    def pet_menu(self,point):
        menu=QMenu(self);menu.addAction("打开笔记",self.show_panel);menu.addAction("设置",self.settings);menu.addSeparator();menu.addAction("彻底退出",self.quit)
        with self.dialog():menu.exec(point)

    def wander(self):
        walking=self.state.get("wander",False) and not self.isVisible() and self.pet._press_pos is None
        self.pet.set_walking(walking)

    def quit(self):
        if not self.save_all():self.show_panel();return False
        if not self.persist():
            with self.dialog():choice=QMessageBox.question(self,"设置未保存","笔记正文已保存，但设置写入失败。保留原设置文件并退出？")
            if choice!=QMessageBox.StandardButton.Yes:return False
        self.closing=True
        self.search_serial+=1
        for worker,cancel in self.search_workers:cancel.set()
        for worker,cancel in self.search_workers:worker.join(timeout=.3)
        self.sync_timer.stop();self.watch_timer.stop();self.wander_timer.stop()
        for entry in self.entries.values():entry["timer"].stop()
        if self.tray:self.tray.hide()
        if self.backdrop:self.backdrop.close()
        self.pet.close();self.close()
        QApplication.instance().quit()
        return True
