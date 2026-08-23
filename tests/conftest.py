"""Pytest fixtures and cross-platform test helpers for Flutter Termux SDK."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Union

# Ensure repository root and tests directory are in sys.path
TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

_IS_WSL_BASH = None


def is_wsl_bash() -> bool:
    """Dynamically detect if 'bash' command executes WSL bash or MSYS2/Git-Bash."""
    global _IS_WSL_BASH
    if _IS_WSL_BASH is not None:
        return _IS_WSL_BASH
    if sys.platform != "win32":
        _IS_WSL_BASH = False
        return False
    try:
        res = subprocess.run(["bash", "-c", "echo $WSL_DISTRO_NAME"], capture_output=True, text=True, timeout=3)
        if res.stdout.strip():
            _IS_WSL_BASH = True
            return True
        res2 = subprocess.run(["bash", "-c", "uname -r"], capture_output=True, text=True, timeout=3)
        _IS_WSL_BASH = "microsoft" in res2.stdout.lower() or "wsl" in res2.stdout.lower()
    except Exception:
        _IS_WSL_BASH = False
    return _IS_WSL_BASH


def to_bash_path(path: Union[str, Path]) -> str:
    """Convert a file path to the appropriate POSIX path format for the detected bash environment.

    - On Windows with WSL bash: C:\\foo\\bar -> /mnt/c/foo/bar
    - On Windows with Git-Bash/MSYS2: C:\\foo\\bar -> /c/foo/bar
    - On Linux/macOS: /foo/bar -> /foo/bar
    """
    p = Path(path).resolve()
    if sys.platform == "win32":
        if p.drive:
            drive = p.drive[0].lower()
            rel = p.as_posix()[len(p.drive):]  # strip 'C:' or 'D:'
            if is_wsl_bash():
                return f"/mnt/{drive}{rel}"
            else:
                return f"/{drive}{rel}"
        return p.as_posix()
    return p.as_posix()


to_wsl_posix = to_bash_path
to_bash_posix = to_bash_path
