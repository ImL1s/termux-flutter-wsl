import json
import re
import subprocess
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def parse_metadata_source_commit(json_str: str) -> str:
    """Simulate the python extraction command used in device-smoke.yml."""
    data = json.loads(json_str)
    val = data.get("source_commit", "")
    if val is None:
        val = ""
    return str(val)


def validate_evidence_schema_strict(evidence_data: dict) -> bool:
    """Strict schema validation for evidence.json enforcing required keys."""
    required_keys = ["status", "timestamp", "device", "apk_launch", "crash_free"]
    for key in required_keys:
        if key not in evidence_data:
            return False
    if evidence_data["status"] not in ("passed", "failed"):
        return False
    if not isinstance(evidence_data["apk_launch"], (bool, str)):
        return False
    if not isinstance(evidence_data["crash_free"], (bool, str)):
        return False
    return True


def test_adversarial_build_metadata_missing_source_commit(tmp_path):
    # Case 1: missing source_commit key
    metadata_missing = tmp_path / "metadata_missing.json"
    metadata_missing.write_text(json.dumps({"version": "3.44.2", "arch": "arm64"}), encoding="utf-8")
    commit_missing = parse_metadata_source_commit(metadata_missing.read_text(encoding="utf-8"))
    assert commit_missing == "", "Missing source_commit key must result in empty string"

    # Case 2: source_commit is null
    metadata_null = tmp_path / "metadata_null.json"
    metadata_null.write_text(json.dumps({"version": "3.44.2", "source_commit": None}), encoding="utf-8")
    commit_null = parse_metadata_source_commit(metadata_null.read_text(encoding="utf-8"))
    assert commit_null == "", "source_commit=null must be sanitized to empty string, not string 'None'"

    # Case 3: source_commit is empty string
    metadata_empty = tmp_path / "metadata_empty.json"
    metadata_empty.write_text(json.dumps({"version": "3.44.2", "source_commit": ""}), encoding="utf-8")
    commit_empty = parse_metadata_source_commit(metadata_empty.read_text(encoding="utf-8"))
    assert commit_empty == "", "source_commit='' must yield empty string"

    # Verify bash rejection logic: if [ -z "$SOURCE_COMMIT" ]
    for commit_val in [commit_missing, commit_null, commit_empty]:
        assert len(commit_val) == 0, "All invalid/missing source_commit values must be empty string for bash -z check"


def test_adversarial_build_metadata_invalid_json(tmp_path):
    invalid_json_file = tmp_path / "invalid_metadata.json"
    invalid_json_file.write_text("{version: 3.44.2, invalid_json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        parse_metadata_source_commit(invalid_json_file.read_text(encoding="utf-8"))


def test_adversarial_evidence_json_schema_validation():
    valid_evidence = {
        "status": "passed",
        "timestamp": "2026-08-05T12:00:00Z",
        "device": "Samsung SM-X716B",
        "apk_launch": True,
        "crash_free": True,
    }
    assert validate_evidence_schema_strict(valid_evidence) is True

    # Test required keys missing one by one
    for key in ["status", "timestamp", "device", "apk_launch", "crash_free"]:
        invalid_ev = dict(valid_evidence)
        del invalid_ev[key]
        assert validate_evidence_schema_strict(invalid_ev) is False, f"Missing required key '{key}' must be rejected"

    # Test invalid status value
    invalid_status = dict(valid_evidence, status="invalid_status")
    assert validate_evidence_schema_strict(invalid_status) is False

    # Test invalid type for apk_launch
    invalid_launch_type = dict(valid_evidence, apk_launch=12345)
    assert validate_evidence_schema_strict(invalid_launch_type) is False

    # Test invalid type for crash_free
    invalid_crash_type = dict(valid_evidence, crash_free={"invalid": "type"})
    assert validate_evidence_schema_strict(invalid_crash_type) is False


def test_adversarial_device_smoke_permissions():
    workflow_path = ROOT / ".github" / "workflows" / "device-smoke.yml"
    assert workflow_path.is_file(), "device-smoke.yml must exist"

    text = workflow_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    permissions = data.get("permissions", {})
    assert permissions.get("contents") == "write", "device-smoke.yml top-level permissions must contain contents: write"
    assert permissions.get("actions") == "read", "device-smoke.yml top-level permissions must contain actions: read"


def test_adversarial_release_promotion_arguments_and_target():
    workflow_path = ROOT / ".github" / "workflows" / "device-smoke.yml"
    text = workflow_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    steps = data["jobs"]["smoke"]["steps"]
    promote_step = next((s for s in steps if s.get("name") == "Promote Release"), None)
    assert promote_step is not None, "Promote Release step must be present in device-smoke.yml"

    step_run = promote_step.get("run", "")

    # Check extraction/retrieval of source commit from environment or metadata
    assert ("sourceCommit" in step_run or "ARTIFACT_SOURCE_COMMIT" in step_run or "source_commit" in step_run), (
        "Promote Release step must obtain source commit"
    )

    # Check gh release create flags and --target commit binding
    assert "gh release create" in step_run, "Promote Release step must call gh release create"
    assert "--target" in step_run and ("$sourceCommit" in step_run or "$SOURCE_COMMIT" in step_run or "$env:ARTIFACT_SOURCE_COMMIT" in step_run), (
        "gh release create must use --target with source commit"
    )

    # Check that $GITHUB_SHA of the workflow run is NOT used as target
    assert "--target \"$GITHUB_SHA\"" not in step_run, "Must not use $GITHUB_SHA of smoke workflow run as target"
    assert "--target '$GITHUB_SHA'" not in step_run, "Must not use $GITHUB_SHA of smoke workflow run as target"
    assert "--target $env:GITHUB_SHA" not in step_run, "Must not use $GITHUB_SHA of smoke workflow run as target"


def test_adversarial_device_smoke_script_evidence_format():
    """Verify that run_termux_smoke.ps1 and termux_smoke.sh output evidence.json with complete details."""
    ps1_path = ROOT / "scripts" / "device" / "run_termux_smoke.ps1"
    sh_path = ROOT / "scripts" / "device" / "termux_smoke.sh"

    ps1_text = ps1_path.read_text(encoding="utf-8")
    sh_text = sh_path.read_text(encoding="utf-8")

    assert "evidence.json" in ps1_text, "run_termux_smoke.ps1 must write evidence.json"
    assert "evidence.json" in sh_text, "termux_smoke.sh must write evidence.json"

    # Check that both scripts construct evidence containing launch/status information
    assert "launch_result" in ps1_text and "exit_status" in ps1_text
    assert "launch_result" in sh_text and "exit_status" in sh_text
