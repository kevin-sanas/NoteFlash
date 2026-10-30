"""Build the standalone Windows app and installer using project-local tools."""

import os
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parent.parent


def main():
    build = ROOT / "build" / "qt-candidate"
    dist = ROOT / "dist" / "qt-candidate"
    temporary = build / "temp"
    temporary.mkdir(parents=True, exist_ok=True)
    for name in ("NoteFlash-Setup.exe", "NoteFlash-Portable.zip"):
        (dist / name).unlink(missing_ok=True)
    startup_report = ROOT / "artifacts" / "candidate-startup.json"
    startup_report.parent.mkdir(parents=True, exist_ok=True)
    startup_report.unlink(missing_ok=True)
    env = os.environ.copy()
    windows = Path(os.environ["SystemRoot"])
    env.update({"PYTHONPATH": os.pathsep.join(str(ROOT/p) for p in (".build-deps",".runtime-deps")), "PYTHONDONTWRITEBYTECODE": "1",
                # Qt uses Windows' unversioned ICU API. Inherited tool PATHs
                # caused PyInstaller to bundle an incompatible Poppler ICU78.
                "PATH": os.pathsep.join(map(str,(Path(sys.executable).parent, windows / "System32", windows))),
                "PYINSTALLER_CONFIG_DIR": str(build / "pyinstaller-cache"),
                "TEMP": str(temporary), "TMP": str(temporary)})
    common = [sys.executable, "-B", "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
              "--distpath", str(dist), "--workpath", str(build / "work"), "--specpath", str(build),
              "--version-file", str(ROOT / "installer" / "version_info.txt"),
              "--icon", str(ROOT / "assets" / "branding" / "note-flash.ico")]
    app = common + ["--onedir", "--name", "NoteFlash"]
    app += ["--add-data", f"{ROOT / 'assets' / 'branding'};assets/branding"]
    for name in ("approved-atlas.png", "motion-walk-v1.png", "motion-expressions-v1.png", "motion.json"):
        app += ["--add-data", f"{ROOT / 'assets' / 'pets' / name};assets/pets"]
    app += [str(ROOT / "launch.py")]
    subprocess.run(app, cwd=ROOT, env=env, check=True)
    bundled_icu = list((dist / "NoteFlash").rglob("icu*.dll"))
    if bundled_icu:
        raise RuntimeError(f"Qt must use Windows ICU; unexpected bundled ICU: {bundled_icu}")
    with tempfile.TemporaryDirectory(prefix="startup-",dir=temporary) as probe:
        probe_env=env.copy();probe_env["QT_QPA_PLATFORM"]="windows"
        subprocess.run([str(dist / "NoteFlash" / "NoteFlash.exe"), "--verify-report", str(startup_report),
                        "--state-dir", str(Path(probe)/"state"), "--no-register"],
                       cwd=ROOT, env=probe_env, check=True, timeout=45)
        result=json.loads(startup_report.read_text(encoding="utf-8"))
        if (result.get("frontend") != "qt" or result.get("platform") != "windows"
                or not result.get("autosaved") or not result.get("closed")
                or not all(result.get("icons",{}).get(key) for key in ("application","github"))):
            raise RuntimeError(f"Native Qt startup gate failed: {result}")
    uninstaller = common + ["--onefile", "--name", "Uninstall", str(ROOT / "installer" / "uninstall.py")]
    subprocess.run(uninstaller, cwd=ROOT, env=env, check=True)
    shutil.copyfile(dist / "Uninstall.exe", dist / "NoteFlash" / "Uninstall.exe")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copyfile(ROOT / name, dist / "NoteFlash" / name)
    shutil.copytree(ROOT / "licenses", dist / "NoteFlash" / "licenses", dirs_exist_ok=True)
    payload = build / "application.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((dist / "NoteFlash").rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(dist / "NoteFlash"))
    setup = common + ["--onefile", "--name", "NoteFlash-Setup", "--add-data", f"{payload};.", str(ROOT / "installer" / "setup.py")]
    subprocess.run(setup, cwd=ROOT, env=env, check=True)
    shutil.copyfile(payload, dist / "NoteFlash-Portable.zip")
    print(f"Application: {dist / 'NoteFlash' / 'NoteFlash.exe'}")
    print(f"Installer: {dist / 'NoteFlash-Setup.exe'}")
    print(f"Portable: {dist / 'NoteFlash-Portable.zip'}")


if __name__ == "__main__":
    main()
