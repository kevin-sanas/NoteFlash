"""Qt application entry and isolated installed-binary verification scenarios."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QMenu

from .qt_app import NoteWindow
from . import __version__
from .data_paths import resolve_data_dir, prepare_data_dir, read_install_config


def main():
    parser=argparse.ArgumentParser(description="Note Flash 本地笔记")
    parser.add_argument("--open",action="store_true",help="打开笔记面板")
    parser.add_argument("--state-dir","--data-dir",dest="state_dir",type=Path,help="独立应用数据目录")
    parser.add_argument("--no-register",action="store_true",help="不创建系统注册信息")
    parser.add_argument("--verify-report",type=Path)
    parser.add_argument("--verify-exit-menu",choices=("tray","pet"))
    parser.add_argument("--performance-scenario",choices=("rest","occluded","wander","edit","tabs","search"))
    parser.add_argument("--duration",type=float,default=20)
    parser.add_argument("--ready-file",type=Path)
    args=parser.parse_args()
    home=Path(sys.executable).parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parents[1]
    diagnostic=bool(args.verify_report or args.performance_scenario)
    if diagnostic and args.state_dir is None:
        parser.error("验证与资源测量必须指定独立 --state-dir。")
    explicit=args.state_dir
    if explicit is None and not getattr(sys,"frozen",False) and read_install_config(home) is None:
        explicit=home/".qt-data"
    state_dir=resolve_data_dir(home,explicit)
    if diagnostic and state_dir.exists() and any(state_dir.iterdir()):
        parser.error("验证与资源测量必须使用空的独立数据目录。")
    prepare_data_dir(state_dir)
    app=QApplication(sys.argv[:1]);app.setQuitOnLastWindowClosed(False)
    window=NoteWindow(state_dir,preview=diagnostic,tray=True)
    window.app_home=home
    temporary=None;cover=None;typing=None;note=None
    if diagnostic:
        temporary=tempfile.TemporaryDirectory(prefix="verification-notes-",dir=state_dir)
        note=Path(temporary.name)/"中文笔记.txt"
        note.write_text(("性能验证笔记：保持正文与高亮可编辑。\n"*2500) if args.performance_scenario in ("edit","tabs") else "安装验证\n",encoding="utf-8")
        if args.verify_report or args.performance_scenario in ("edit","tabs","search"):
            window.roots=[note.parent];window.refresh_tree();entry=window.open_file(note)
            window.show_panel();entry["editor"].moveCursor(entry["editor"].textCursor().MoveOperation.End)
            entry["editor"].insertPlainText("自动保存验证")
        if args.performance_scenario=="edit":
            typing=QTimer(window);typing.setInterval(180)
            typing.timeout.connect(lambda:entry["editor"].insertPlainText("编辑"));typing.start()
        if args.performance_scenario=="tabs":
            for index in range(11):
                extra=note.parent/f"标签{index+2}.txt";extra.write_bytes(note.read_bytes());window.open_file(extra)
        if args.performance_scenario=="search":
            for index in range(500):
                (note.parent/f"搜索{index:04}.txt").write_text(("本地目录检索样本。\n"*120)+"目标内容",encoding="utf-8")
            window.refresh_tree();window.search.setText("目标内容")
            typing=QTimer(window);typing.setInterval(1200);typing.timeout.connect(window.start_search);typing.start()
            window.start_search()
        if args.performance_scenario=="wander":
            window.state["wander"]=True;window.wander()
        if args.performance_scenario=="occluded":
            cover=QWidget(None,Qt.WindowType.Window|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
            cover.setWindowTitle("Note Flash · 临时遮挡测量")
            cover.setStyleSheet("background:#284d6a;")
            cover.setGeometry(window.pet.geometry().adjusted(-20,0,20,20));cover.show();cover.raise_()
        def ready():
            if args.ready_file:
                args.ready_file.write_text(json.dumps({"pid":os.getpid(),"frontend":"qt","version":__version__,"platform":app.platformName(),
                    "scenario":args.performance_scenario,"pet_interval":window.pet._timer.interval(),
                    "pet_timer_active":window.pet._timer.isActive(),"pet_visible":window.pet.isVisible(),
                    "occluded":window.pet._occluded,"tray_available":bool(window.tray),
                    "open_tabs":len(window.entries),"fixture_files":501 if args.performance_scenario=="search" else len(window.entries),
                    "focus_collapse_suppressed":diagnostic}),encoding="utf-8")
        QTimer.singleShot(1600,ready)
        def finish():
            if typing:typing.stop()
            sprites={}
            if args.verify_report:
                for species in ("cat","dog","snake","raccoon"):
                    window.pet.set_species(species)
                    sprites[species]=all(not pixmap.isNull() for pixmap in window.pet._base_frames)
            report={"frontend":"qt","version":__version__,"platform":app.platformName(),"app_home":str(home),
                    "data_dir":str(state_dir),"autosaved":"自动保存验证" in note.read_text(encoding="utf-8"),
                    "icons":{"application":not window.app_icon.pixmap(32,32).isNull(),
                             "github":not window.findChild(QPushButton,"githubButton").icon().pixmap(20,20).isNull()},
                    "sprites":sprites}
            if args.verify_exit_menu:
                entry["editor"].insertPlainText("退出入口验证")
                report["exit_menu"]=args.verify_exit_menu
                if args.verify_exit_menu=="tray" and window.tray:
                    action=next(a for a in window.tray.contextMenu().actions() if a.text()=="彻底退出")
                    action.trigger()
                elif args.verify_exit_menu=="pet":
                    def trigger_pet_exit():
                        menu=QApplication.activePopupWidget()
                        if isinstance(menu,QMenu):
                            action=next(a for a in menu.actions() if a.text()=="彻底退出")
                            menu.close();action.trigger()
                    QTimer.singleShot(100,trigger_pet_exit)
                    window.pet_menu(window.pet.mapToGlobal(window.pet.rect().center()))
                else:
                    report["exit_menu_unavailable"]=True
                    window.quit()
                report["closed"]=window.closing
                report["exit_saved"]="退出入口验证" in note.read_text(encoding="utf-8")
                report["tray_removed"]=not bool(window.tray and window.tray.isVisible())
            else:
                report["closed"]=window.quit()
            if args.verify_report:args.verify_report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        QTimer.singleShot(round((3 if args.verify_report else args.duration)*1000),finish)
    elif args.open:
        window.show_panel()
    result=app.exec()
    if cover:cover.close()
    if temporary:temporary.cleanup()
    return result


if __name__=="__main__":
    raise SystemExit(main())
