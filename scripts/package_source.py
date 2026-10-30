"""Create a public source archive without local notes, tests or build outputs."""

from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from note_flash import __version__


def main():
    files = [ROOT / name for name in (
        ".gitignore", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
        "launch.py", "run.ps1", "启动笔记.cmd",
        "requirements-runtime.txt", "requirements-build.txt",
        "scripts/build_windows.py", "scripts/package_source.py",
        "installer/__init__.py", "installer/setup.py", "installer/uninstall.py",
        "installer/version_info.txt",
    )]
    files += [path for path in (ROOT / "note_flash").glob("*.py")
              if path.name not in {"app.py", "pet.py"}]
    for directory in ("assets/branding", "licenses", "docs/images"):
        files += [path for path in (ROOT / directory).rglob("*") if path.is_file()]
    files += [ROOT / "assets/pets" / name for name in (
        "approved-atlas.png", "motion-walk-v1.png", "motion-expressions-v1.png",
        "motion.json", "generation.json",
    )]
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing or unsupported release file: {path}")
    output = ROOT / "dist" / f"NoteFlash-{__version__}-source.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            archive.write(path, f"NoteFlash-{__version__}/{path.relative_to(ROOT).as_posix()}")
    print(f"Source archive: {output} ({len(set(files))} files)")


if __name__ == "__main__":
    main()
