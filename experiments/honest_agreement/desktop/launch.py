"""Isolated portable entry point; invoke with python -I -B."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(ROOT / 'vendor'), str(ROOT / 'hadagent/src')]

from control import main

if __name__ == '__main__':
    raise SystemExit(main())
