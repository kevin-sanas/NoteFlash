"""Absolute-path launcher used by the optional Windows startup entry."""

from pathlib import Path
import sys

if not getattr(sys,"frozen",False):
    sys.path.insert(0,str(Path(__file__).resolve().parent/".runtime-deps"))

from note_flash.qt_launcher import main

if __name__ == "__main__":
    main()
