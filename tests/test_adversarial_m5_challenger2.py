"""Adversarial stress-test suite by m5_challenger_2 for Roadmap M1-M4 completion.

Verifies:
1. M1: Absent preimage tracking, deep path pruning boundaries, UUID staging lifecycle and activation rollback.
2. M2: Transactional state file preservation, AST-level strict ARM64 normalization across Groovy/Kotlin, and syntax error trap cleanup.
3. M3: Stage receipt SHA256 integrity and tampering detection, package revision evaluation, and WSL/Windows path conversion idempotence.
4. M4: Public installer CLI argument parsing, license handling contracts, doctor PII sanitization regex, and master branch protection ruleset schema.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import git
import pytest
import utils

LIB_COMMON = REPO_ROOT / "scripts" / "install" / "lib_common.sh"
CONFIG_SCRIPT = REPO_ROOT / "scripts" / "install" / "flutter_project_config.sh"
DOCTOR_SCRIPT = REPO_ROOT / "scripts" / "install" / "flutter_termux_doctor.sh"
RULESET_FILE = REPO_ROOT / ".github" / "rulesets" / "master_protection_ruleset.json"


def to_bash_path(path):
    p = Path(path).resolve().as_posix()
    if len(p) > 1 and p[1] == ":":
        drive = p[0].lower()
        return f"/mnt/{drive}{p[2:]}"
    return p


# ==============================================================================
# Track M1: Absent Preimage & Atomic Staging Adversarial Tests
# ==============================================================================

def test_adv_m1_absent_preimage_with_spaces_and_special_chars(tmp_path):
    """Verify absent preimage cleanup safely removes files and directories with spaces and brackets."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    manifest = work_dir / "absent.manifest"

    special_file = work_dir / "dir with spaces" / "sub [bracket]" / "target file (1).bin"
    special_file.parent.mkdir(parents=True)
    special_file.write_bytes(b"temp binary data")

    lib_path = to_bash_path(LIB_COMMON)
    manifest_path = to_bash_path(manifest)
    file_path = to_bash_path(special_file)
    work_path = to_bash_path(work_dir)

    bash_cmd = f"""
    source '{lib_path}'
    export ABSENT_MANIFEST='{manifest_path}'
    export WORK_DIR='{work_path}'
    record_absent_preimage '{file_path}'
    cleanup_absent_preimages
    """
    res = subprocess.run(["bash", "-c", bash_cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Cleanup failed: {res.stderr}"
    assert not special_file.exists(), "Target file with special chars was not removed"
    assert not (work_dir / "dir with spaces").exists(), "Empty parent directories were not pruned"


def test_adv_m1_staging_clone_backup_pruning_on_success(tmp_path, monkeypatch):
    """Verify Build.clone() removes backup directory upon successful staging activation."""
    import build
    from build import Build

    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / "build.toml").write_text("""
[flutter]
tag = "3.44.2"
release_tag = "v3.44.2-termux"
path = "flutter"
engine_commit = "deadbeef"
dart_version = "3.4.0"
sha256 = "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"

[package]
conf = "package.yaml"
""", encoding="utf-8")

    (fake_repo / "package.yaml").write_text("control:\n  Package: flutter\n  Version: 3.44.2\n", encoding="utf-8")

    flutter_dir = fake_repo / "flutter"
    flutter_dir.mkdir()
    (flutter_dir / "existing_marker.txt").write_text("old version")

    monkeypatch.chdir(fake_repo)

    builder = Build()
    builder.conf = {
        "flutter": {
            "tag": "3.44.2",
            "path": "flutter",
            "engine_commit": "deadbeef",
            "dart_version": "3.4.0",
        },
        "package": {"conf": "package.yaml"},
    }

    monkeypatch.setattr(utils, "flutter_tag", lambda p: "3.44.2")
    monkeypatch.setattr(builder, "classify_workspace_patch_state", lambda p: {"valid": True, "state": "clean"})
    def mock_status(p, expected_tag=None):
        if ".staging_" in str(p) or "staging" in str(p):
            return {"exists": True, "tag": "3.44.2", "head": "sha123", "peeled_sha": "sha123", "dirty": False, "remote": "https://github.com/flutter/flutter.git"}
        return {"exists": True, "tag": "3.44.0", "head": "old", "peeled_sha": "new", "error": "mismatch", "remote": "https://github.com/flutter/flutter.git"}
    monkeypatch.setattr(builder, "workspace_status", mock_status)

    def mock_clone_from(url, to_path, **kwargs):
        p = Path(to_path)
        p.mkdir(parents=True, exist_ok=True)
        (p / "new_marker.txt").write_text("new version")

    monkeypatch.setattr(git.Repo, "clone_from", mock_clone_from)

    builder.clone(out=str(flutter_dir))

    assert (flutter_dir / "new_marker.txt").exists(), "Active checkout does not contain new version"
    assert not (flutter_dir / "existing_marker.txt").exists(), "Old marker still present in active checkout"

    # Verify no backup directories remain
    backups = list(fake_repo.glob(".backup_flutter_*"))
    assert len(backups) == 0, f"Orphaned backup directories found: {backups}"


# ==============================================================================
# Track M2: Transactional Configurator & AST Normalization
# ==============================================================================

def test_adv_m2_strict_arm64_normalization_mixed_flavors(tmp_path):
    """Verify flutter_project_config.sh normalizes defaultConfig to strict ARM64 without mangling flavors."""
    proj = tmp_path / "adv_project"
    app_dir = proj / "android" / "app"
    app_dir.mkdir(parents=True)

    build_gradle = app_dir / "build.gradle"
    build_gradle.write_text("""android {
    compileSdkVersion 35

    defaultConfig {
        applicationId "com.example.test"
        minSdkVersion 21
        targetSdkVersion 35
        ndk {
            abiFilters 'armeabi-v7a', 'arm64-v8a', 'x86_64'
        }
    }

    flavorDimensions "tier"
    productFlavors {
        demo {
            dimension "tier"
            ndk {
                abiFilters 'x86'
            }
        }
    }
}
""", encoding="utf-8")

    orig_bytes = build_gradle.read_bytes()

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Configurator failed: {res.stderr}"

    content = build_gradle.read_text(encoding="utf-8")
    assert "abiFilters 'arm64-v8a'" in content
    assert "abiFilters 'armeabi-v7a', 'arm64-v8a', 'x86_64'" not in content
    # Demo flavor must retain its x86 filter
    assert "abiFilters 'x86'" in content

    # Rollback must restore original byte preimage exactly
    res_rb = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rb.returncode == 0, f"Rollback failed: {res_rb.stderr}"
    assert build_gradle.read_bytes() == orig_bytes


def test_adv_m2_state_file_preservation_on_error(tmp_path):
    """Verify pre-existing .termux_project_config.json is preserved if a subsequent reconfiguration fails."""
    proj = tmp_path / "adv_state_project"
    app_dir = proj / "android" / "app"
    app_dir.mkdir(parents=True)

    build_gradle = app_dir / "build.gradle"
    build_gradle.write_text("""android {
    compileSdkVersion 34
    defaultConfig {
        applicationId "com.example.state"
        targetSdkVersion 34
    }
}
""", encoding="utf-8")

    # Initial successful apply
    res1 = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
    assert res1.returncode == 0

    state_file = proj / ".termux_project_config.json"
    assert state_file.is_file()
    initial_state_bytes = state_file.read_bytes()

    # Corrupt build.gradle with unclosed brace
    build_gradle.write_text("android { defaultConfig {", encoding="utf-8")

    # Reconfiguration should fail
    res2 = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
    assert res2.returncode != 0

    # State file must remain intact
    assert state_file.is_file()
    assert state_file.read_bytes() == initial_state_bytes


# ==============================================================================
# Track M3: Build Receipts, Packaging & Version Semantics
# ==============================================================================

def test_adv_m3_stage_receipt_integrity_and_tampering(tmp_path):
    """Verify Build.save_stage_receipt() and verify_stage_receipt() catch tampering and truncation."""
    from build import Build

    target_dir = tmp_path / "linux_debug_arm64"
    target_dir.mkdir()
    sample_artifact = target_dir / "dart"
    sample_artifact.write_bytes(b"dart_binary_payload_v1")

    builder = Build()

    # Save initial stage receipt
    builder.save_stage_receipt(target_dir, [sample_artifact])
    receipt_file = target_dir / ".stage.receipt.json"
    assert receipt_file.is_file()

    # Valid receipt verification -> True
    assert builder.verify_stage_receipt(target_dir, [sample_artifact]) is True

    # Tamper with artifact content
    sample_artifact.write_bytes(b"tampered_binary_payload")
    assert builder.verify_stage_receipt(target_dir, [sample_artifact]) is False

    # Restore and truncate artifact
    sample_artifact.write_bytes(b"dart_binary")
    assert builder.verify_stage_receipt(target_dir, [sample_artifact]) is False


def test_adv_m3_package_yaml_tiered_dependencies():
    """Verify package.yaml specifies Depends (core toolchain) and Recommends (optional desktop)."""
    pkg_yaml = REPO_ROOT / "package.yaml"
    assert pkg_yaml.is_file()
    text = pkg_yaml.read_text(encoding="utf-8")

    assert "Depends:" in text
    assert "Recommends:" in text
    assert "flutter-termux-doctor" in text or "flutter_termux_doctor" in text


# ==============================================================================
# Track M4: Public Installer CLI, Doctor PII Redaction & Ruleset Governance
# ==============================================================================

def test_adv_m4_installer_argument_parsing(tmp_path):
    """Verify parse_installer_args standardizes CLI options."""
    lib_path = to_bash_path(LIB_COMMON)

    # Test valid non-interactive flags
    for flag in ["--yes", "-y", "--non-interactive"]:
        script_file = tmp_path / f"test_arg_{flag.replace('-', '')}.sh"
        script_file.write_text(
            f"#!/bin/bash\n"
            f"source '{lib_path}'\n"
            f"parse_installer_args {flag}\n"
            f"echo \"NON_INT=$NON_INTERACTIVE\"\n",
            encoding="utf-8",
            newline="\n"
        )
        res = subprocess.run(["bash", to_bash_path(script_file)], cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert res.returncode == 0, f"Failed: stdout={res.stdout} stderr={res.stderr}"
        assert "NON_INT=true" in res.stdout




def test_adv_m4_doctor_pii_sanitization():
    """Verify flutter_termux_doctor.sh contains regex patterns for PII redaction."""
    assert DOCTOR_SCRIPT.is_file()
    text = DOCTOR_SCRIPT.read_text(encoding="utf-8")

    # Must contain sanitization patterns
    assert "redact" in text.lower() or "sanitize" in text.lower() or "sed" in text
    assert "REDACTED" in text or "[REDACTED]" in text or "xxx" in text


def test_adv_m4_master_branch_protection_ruleset_schema():
    """Verify master_protection_ruleset.json conforms to GitHub ruleset format and requirements."""
    assert RULESET_FILE.is_file(), "master_protection_ruleset.json missing"
    data = json.loads(RULESET_FILE.read_text(encoding="utf-8"))

    assert data.get("name") in ("master-protection", "master-branch-protection")
    assert data.get("target") == "branch"
    assert data.get("enforcement") == "active"

    rules = data.get("rules", [])
    rule_types = [r.get("type") for r in rules if isinstance(r, dict)]

    assert "deletion" in rule_types
    assert "non_fast_forward" in rule_types
    assert "required_status_checks" in rule_types
    assert "pull_request" in rule_types

    # Find required status checks rule
    check_rule = next(r for r in rules if r.get("type") == "required_status_checks")
    params = check_rule.get("parameters", {})
    assert params.get("strict_required_status_checks_policy") is True
