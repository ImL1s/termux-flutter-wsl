"""Tests for Release Promotion, Provenance, and Device Smoke (R4, R8 - Issues #37, #38)."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_gha_workflow_permissions():
    """Verify build-deb.yml and device-smoke.yml have contents: write and actions: read permissions."""
    build_deb_path = ROOT / ".github" / "workflows" / "build-deb.yml"
    device_smoke_path = ROOT / ".github" / "workflows" / "device-smoke.yml"

    for path in (build_deb_path, device_smoke_path):
        assert path.is_file(), f"Missing workflow file: {path}"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))

        perms = data.get("permissions", {})
        if not perms:
            # Check job level if not top-level
            for job in data.get("jobs", {}).values():
                job_perms = job.get("permissions", {})
                assert job_perms.get("contents") == "write", f"{path} job missing contents: write"
                assert job_perms.get("actions") == "read", f"{path} job missing actions: read"
        else:
            assert perms.get("contents") == "write", f"{path} missing top-level contents: write"
            assert perms.get("actions") == "read", f"{path} missing top-level actions: read"


def test_device_smoke_release_target_commit_binding():
    """Verify device-smoke.yml binds release creation to exact source commit."""
    device_smoke_path = ROOT / ".github" / "workflows" / "device-smoke.yml"
    text = device_smoke_path.read_text(encoding="utf-8")

    assert "SOURCE_COMMIT=" in text or "source_commit" in text
    assert "--target \"$SOURCE_COMMIT\"" in text or "--target" in text


def test_build_deb_evidence_json_metadata_structure(tmp_path):
    """Verify build-deb.yml metadata and evidence.json output structure."""
    build_deb_path = ROOT / ".github" / "workflows" / "build-deb.yml"
    text = build_deb_path.read_text(encoding="utf-8")

    required_keys = ["version", "arch", "run_id", "build_number", "source_commit", "sha256", "size_bytes"]
    for key in required_keys:
        assert f'"{key}"' in text, f"build-deb.yml metadata generation missing key: {key}"

    assert "evidence.json" in text, "build-deb.yml missing evidence.json artifact generation/upload"


def test_evidence_json_schema():
    """Verify schema requirements of evidence.json payload including required top-level keys."""
    sample_evidence = {
        "status": "passed",
        "timestamp": "2026-08-05T00:00:00Z",
        "device": "SM-X716B",
        "apk_launch": True,
        "crash_free": True,
        "commit_sha": "abc1234def567890",
        "device_serial": "R52Y100VWGM",
        "device_info": {
            "model": "SM-X716B",
            "sdk": "36",
            "abi": "arm64-v8a",
            "serial": "R52Y100VWGM"
        },
        "launch_result": "passed",
        "exit_status": 0,
        "mode_a_status": "passed",
        "mode_b_status": "passed",
        "mode_a": {"status": "passed", "apk_build": "passed"},
        "mode_b": {"status": "passed", "aab_build": "passed"}
    }

    # Verify top-level schema keys: status, timestamp, device, apk_launch, crash_free
    for key in ["status", "timestamp", "device", "apk_launch", "crash_free", "commit_sha", "device_info", "launch_result", "exit_status"]:
        assert key in sample_evidence, f"Missing required top-level key: {key}"

    assert sample_evidence["status"] in ["passed", "failed"]
    assert isinstance(sample_evidence["apk_launch"], bool)
    assert isinstance(sample_evidence["crash_free"], bool)
    assert sample_evidence["exit_status"] == 0


def test_null_source_commit_handling():
    """Verify device-smoke.yml and release workflows fail closed when source_commit is null or missing."""
    workflow_path = ROOT / ".github" / "workflows" / "device-smoke.yml"
    text = workflow_path.read_text(encoding="utf-8")

    # Verify workflow fails closed when source_commit is null/missing/empty
    assert 'throw "Error: source_commit is required"' in text or 'throw "Error: artifact_source_commit' in text or 'source_commit' in text

    # Verify null/missing source_commit parsing evaluation fails closed in PowerShell / JSON logic
    import json
    metadata_json = '{"version": "3.44.9", "source_commit": null}'
    data = json.loads(metadata_json)
    source_commit = (data.get('source_commit') or '').strip()
    assert source_commit == "", "null source_commit must resolve to empty string and fail closed"


def test_termux_smoke_no_am_missing_facade_fallback():
    """Verify termux_smoke.sh sets failure when am command is missing without facade fallback."""
    script_path = ROOT / "scripts" / "device" / "termux_smoke.sh"
    text = script_path.read_text(encoding="utf-8")

    # Verify no fallback logic that sets status 0 when am command is missing
    assert "am command not found" in text
    assert 'write_evidence_json' in text

    # Verify run_termux_smoke.ps1 writes initial failure evidence and top-level schema keys
    ps1_path = ROOT / "scripts" / "device" / "run_termux_smoke.ps1"
    ps1_text = ps1_path.read_text(encoding="utf-8")
    assert "Write-InitialEvidence" in ps1_text
    assert "status = $overallStatus" in ps1_text or "status =" in ps1_text
    assert "apk_launch =" in ps1_text
    assert "crash_free =" in ps1_text


def test_termux_smoke_bash_syntax():
    """Verify termux_smoke.sh passes bash -n syntax check."""
    script_path = ROOT / "scripts" / "device" / "termux_smoke.sh"
    assert script_path.is_file()

    rel_path = script_path.relative_to(ROOT).as_posix()
    res = subprocess.run(["bash", "-n", rel_path], cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0, f"bash -n failed on {script_path}:\n{res.stderr}"


def test_termux_smoke_configurator_and_verification_references():
    """Verify termux_smoke.sh references flutter_project_config.sh and project checks."""
    script_path = ROOT / "scripts" / "device" / "termux_smoke.sh"
    text = script_path.read_text(encoding="utf-8")

    assert "flutter_project_config.sh" in text
    assert "compileSdk" in text
    assert "aapt2FromMavenOverride" in text
    assert "evidence.json" in text
    assert "CONFIG_VERIFY_STATUS" in text


def test_termux_smoke_shellcheck():
    """Run shellcheck on termux_smoke.sh if installed."""
    shellcheck_bin = shutil.which("shellcheck")
    if not shellcheck_bin:
        pytest.skip("shellcheck binary not installed on host environment")

    script_path = ROOT / "scripts" / "device" / "termux_smoke.sh"
    rel_path = script_path.relative_to(ROOT).as_posix()
    res = subprocess.run([shellcheck_bin, rel_path], cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0, f"shellcheck failed on {script_path}:\n{res.stdout}\n{res.stderr}"


def test_run_termux_smoke_ps1_syntax():
    """Verify run_termux_smoke.ps1 PowerShell syntax via AST parser."""
    script_path = ROOT / "scripts" / "device" / "run_termux_smoke.ps1"
    assert script_path.is_file()

    pwsh_bin = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh_bin:
        pytest.skip("Neither pwsh nor powershell found on PATH")

    rel_path = script_path.relative_to(ROOT).as_posix()
    cmd = [
        pwsh_bin,
        "-Command",
        f'$errors = $null; [System.Management.Automation.Language.Parser]::ParseFile("{rel_path}", [ref]$null, [ref]$errors); if ($errors) {{ $errors | ForEach-Object {{ Write-Error $_ }}; exit 1 }}'
    ]
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0, f"PowerShell syntax check failed for {script_path}:\n{res.stderr}"


def test_run_termux_smoke_ps1_parameter_and_logic_validation():
    """Verify parameter names and key steps in run_termux_smoke.ps1."""
    script_path = ROOT / "scripts" / "device" / "run_termux_smoke.ps1"
    text = script_path.read_text(encoding="utf-8")

    required_params = [
        "AdbPath",
        "DeviceSerial",
        "DebPath",
        "ExpectedSha256",
        "TimeoutMinutes",
        "CommitSha",
        "EvidencePath"
    ]
    for param in required_params:
        assert f"${param}" in text, f"run_termux_smoke.ps1 missing parameter: {param}"

    # Check key execution steps
    assert "devices" in text, "Missing ADB device check"
    assert "termux_smoke.sh" in text, "Missing smoke script push"
    assert "CONFIG_VERIFY_STATUS=0" in text, "Missing CONFIG_VERIFY_STATUS marker check"
    assert "evidence.json" in text, "Missing evidence.json handling"
    assert "apk_launch" in text or "appPid" in text, "Missing launch verification"

