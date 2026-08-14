import hashlib
import os
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
LIB_COMMON = REPO_ROOT / "scripts" / "install" / "lib_common.sh"
INSTALLER = REPO_ROOT / "install_flutter_complete.sh"


def to_bash_path(path):
    path = Path(path).resolve()
    try:
        rel = path.relative_to(REPO_ROOT)
        return rel.as_posix()
    except ValueError:
        p = path.as_posix()
        if len(p) > 1 and p[1] == ":":
            drive = p[0].lower()
            return f"/mnt/{drive}{p[2:]}"
        return p


def test_verify_sha256_success(tmp_path):
    test_file = tmp_path / "sample.txt"
    content = b"hello world\n"
    test_file.write_bytes(content)
    expected_sha = hashlib.sha256(content).hexdigest()

    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(test_file)
    cmd = f"source '{lib_path}' && verify_sha256 '{file_path}' '{expected_sha}'"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Failed: stdout={res.stdout}, stderr={res.stderr}"
    assert test_file.exists()


def test_verify_sha256_mismatch_removes_file(tmp_path):
    test_file = tmp_path / "corrupt.txt"
    test_file.write_bytes(b"corrupted content\n")
    wrong_sha = "0000000000000000000000000000000000000000000000000000000000000000"

    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(test_file)
    cmd = f"source '{lib_path}' && verify_sha256 '{file_path}' '{wrong_sha}'"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode != 0
    assert not test_file.exists(), "File should be removed on sha256 mismatch"


def test_verify_sha256_missing_hasher_fails(tmp_path):
    test_file = tmp_path / "sample.txt"
    content = b"hello world\n"
    test_file.write_bytes(content)
    expected_sha = hashlib.sha256(content).hexdigest()

    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(test_file)
    mock_cmd = 'command() { if [ "$2" = "sha256sum" ] || [ "$2" = "shasum" ]; then return 1; fi; builtin command "$@"; };'
    cmd = f"{mock_cmd} source '{lib_path}' && verify_sha256 '{file_path}' '{expected_sha}'"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode != 0
    assert "Neither sha256sum nor shasum is available" in res.stdout or "Neither sha256sum nor shasum" in res.stdout


def test_installer_syntax():
    res = subprocess.run(["bash", "-n", to_bash_path(INSTALLER)], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"bash -n failed: {res.stderr}"


def test_lib_common_syntax():
    res = subprocess.run(["bash", "-n", to_bash_path(LIB_COMMON)], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"bash -n failed: {res.stderr}"
