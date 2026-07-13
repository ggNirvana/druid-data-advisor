#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    python = project_root / ".venv" / "bin" / "python"
    if not python.exists():
        raise SystemExit(f"本地运行时不存在，请先运行 {project_root / 'scripts' / 'setup-local.sh'}")
    os.chdir(project_root)
    os.execv(str(python), [str(python), "-m", "d4advisor", *sys.argv[1:]])


if __name__ == "__main__":
    main()
