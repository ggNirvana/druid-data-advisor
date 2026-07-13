#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    project_root = Path(__file__).resolve().parents[3]
    if os.name == "nt":
        python = project_root / ".venv" / "Scripts" / "python.exe"
    else:
        python = project_root / ".venv" / "bin" / "python"
    if not python.exists():
        raise SystemExit(
            f"本地运行时不存在，请先运行 {project_root / 'scripts' / 'setup-local.sh'}"
        )
    command = [str(python), "-m", "d4advisor", *sys.argv[1:]]
    if os.name == "nt":
        return subprocess.call(command, cwd=project_root)
    os.chdir(project_root)
    os.execv(str(python), command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
