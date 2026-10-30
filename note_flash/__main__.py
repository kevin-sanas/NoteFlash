from pathlib import Path
import sys

if not getattr(sys,"frozen",False):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/".runtime-deps"))

from .qt_launcher import main

main()
