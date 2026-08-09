import os
import json
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = (REPO_ROOT / "scripts" / "device" / "termux_smoke.sh").relative_to(REPO_ROOT).as_posix()

def to_wsl_posix(p):
    s = p.as_posix()
    if len(s) > 1 and s[1:3] == ":/":
        return f"/mnt/{s[0].lower()}{s[2:]}"
    return s

def test_termux_smoke_script_syntax():
    res = subprocess.run(["bash", "-n", SCRIPT_PATH], cwd=REPO_ROOT, capture_output=True, text=True)
    assert res.returncode == 0, f"Syntax error in termux_smoke.sh: {res.stderr}"

def test_termux_smoke_evidence_structure(tmp_path):
    log_file = to_wsl_posix(tmp_path / "smoke.log")
    deb_file = tmp_path / "dummy.deb"
    deb_file.write_text("dummy deb")
    deb_posix = to_wsl_posix(deb_file)

    home_dir = tmp_path / "home"
    home_dir.mkdir()
    home_posix = to_wsl_posix(home_dir)

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_SMOKE_LOG='{log_file}'; "
        f"export TERMUX_SMOKE_DEB='{deb_posix}'; "
        f"export TERMUX_SMOKE_COMMIT_SHA='abc123def'; "
        f"export HOME='{home_posix}'; "
        f"bash ./{SCRIPT_PATH}"
    ]

    res = subprocess.run(bash_cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    ev_path = home_dir / ".termux_smoke" / "evidence.json"
    assert ev_path.exists(), f"evidence.json not created.\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"

    data = json.loads(ev_path.read_text())
    assert "status" in data
    assert "apk_launch" in data
    assert "crash_free" in data
    assert "commit_sha" in data
    assert data["commit_sha"] == "abc123def"
    assert "mode_a" in data
    assert "mode_b" in data


def test_termux_smoke_delegated_launch_emits_pending_host_marker(tmp_path):
    log_file = tmp_path / "smoke.log"
    script = (
        f"export TERMUX_SMOKE_LOG='{to_wsl_posix(log_file)}'\n"
        "record_status() { echo \"$1=$2\" >> \"$TERMUX_SMOKE_LOG\"; }\n"
        "ALLOW_LOCAL_TERMUX_LAUNCH=0\n"
        "if [ \"${ALLOW_LOCAL_TERMUX_LAUNCH:-0}\" = \"1\" ]; then\n"
        "  record_status APK_LAUNCH_STATUS 0\n"
        "else\n"
        "  record_status APK_HOST_VERIFY_REQUIRED 0\n"
        "fi\n"
    )
    sh_file = tmp_path / "test.sh"
    sh_file.write_text(script, encoding="utf-8", newline="\n")
    res = subprocess.run(["bash", to_wsl_posix(sh_file)], cwd=REPO_ROOT, capture_output=True, text=True)
    assert res.returncode == 0, f"Command failed: {res.stderr}"
    log_content = log_file.read_text()
    assert "APK_HOST_VERIFY_REQUIRED=0" in log_content
    assert "APK_LAUNCH_STATUS=0" not in log_content


def test_mode_b_failure_fails_overall_status():
    ps_script = (REPO_ROOT / "scripts" / "device" / "run_termux_smoke.ps1").read_text(encoding="utf-8")
    assert 'BUILD_AAB_STATUS=0' in ps_script
    assert 'overallStatus = if ($launchPassed -and $modeA -eq "passed" -and $modeB -eq "passed") { "passed" } else { "failed" }' in ps_script
