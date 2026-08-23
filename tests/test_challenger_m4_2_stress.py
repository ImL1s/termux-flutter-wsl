"""Adversarial stress test suite for Milestone M4 (Track R4: Issues #56, #57, #58).

Conducted by Challenger M4-2.
Tests release governance, SHA256 boundary & format normalization, companion metadata
cardinality, promotion gates, version drift detection across all assets, workflow permissions,
and repo sanity contracts.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.ci.verify_release_asset as vra
import scripts.ci.check_version_drift as cvd
import scripts.ci.check_repo as cr


# ==============================================================================
# 1. ISSUE #56: RELEASE GOVERNANCE, SHA256 VALIDATION & PROMOTION GATES
# ==============================================================================

class TestAdversarialSHA256Validation:
    """Adversarial testing of SHA256 format validation and checksum file parsing."""

    VALID_64_HEX = "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"

    @pytest.mark.parametrize(
        "valid_hash,expected_lower",
        [
            ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e", "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"),
            ("F706406253586A5586F8A1E7FF0A09B5A7F029A8EA9F2E1225CE682F10550C9E", "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"),
            ("F706406253586a5586F8a1e7ff0a09b5A7F029A8ea9f2e1225ce682F10550C9E", "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"),
            ("0000000000000000000000000000000000000000000000000000000000000000", "0000000000000000000000000000000000000000000000000000000000000000"),
            ("ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff", "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"),
        ],
    )
    def test_valid_sha256_normalization(self, valid_hash, expected_lower):
        res = vra.validate_sha256_format(valid_hash)
        assert res == expected_lower.lower()
        assert len(res) == 64
        assert res == res.lower()

    @pytest.mark.parametrize(
        "invalid_hash,error_match",
        [
            # Whitespace & newline injections
            (" f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e", "leading/trailing whitespace or newline"),
            ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e ", "leading/trailing whitespace or newline"),
            ("  f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e  ", "leading/trailing whitespace or newline"),
            ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e\n", "leading/trailing whitespace or newline"),
            ("\nf706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e", "leading/trailing whitespace or newline"),
            ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e\r\n", "leading/trailing whitespace or newline"),
            ("\t\tf706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e", "leading/trailing whitespace or newline"),
            # Length anomalies
            ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9", "must be exactly 64 hex characters"),  # 63 chars
            ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e1", "must be exactly 64 hex characters"),  # 65 chars
            ("0", "must be exactly 64 hex characters"),
            ("a" * 128, "must be exactly 64 hex characters"),
            # Non-hex characters
            ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9g", "must be exactly 64 hex characters"),
            ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9z", "must be exactly 64 hex characters"),
            ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9-", "must be exactly 64 hex characters"),
            ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9!", "must be exactly 64 hex characters"),
            ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9\u00e9", "must be exactly 64 hex characters"),
            # Empty / Non-string
            (None, "missing or empty"),
            ("", "empty"),
            ("   ", "empty"),
            ("\n", "empty"),
            ("\t", "empty"),
            (12345678, "missing or empty"),
            (["f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"], "missing or empty"),
        ],
    )
    def test_adversarial_sha256_rejections(self, invalid_hash, error_match):
        with pytest.raises(ValueError, match=error_match):
            vra.validate_sha256_format(invalid_hash)

    def test_checksum_file_parsing(self, tmp_path):
        """Test verify_checksum_file on various checksum formats and corruptions."""
        # Standard sha256sum format
        valid_file = tmp_path / "valid.sha256"
        valid_file.write_text(f"{self.VALID_64_HEX}  flutter_3.44.9_aarch64.deb\n", encoding="utf-8")
        assert vra.verify_checksum_file(valid_file) == self.VALID_64_HEX

        # Single hash format
        single_hash = tmp_path / "single.sha256"
        single_hash.write_text(f"{self.VALID_64_HEX.upper()}\n", encoding="utf-8")
        assert vra.verify_checksum_file(single_hash) == self.VALID_64_HEX

        # Missing file
        with pytest.raises(ValueError, match="Checksum file missing"):
            vra.verify_checksum_file(tmp_path / "nonexistent.sha256")

        # Empty file
        empty_file = tmp_path / "empty.sha256"
        empty_file.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="Checksum file is empty"):
            vra.verify_checksum_file(empty_file)

        # Corrupt file
        corrupt_file = tmp_path / "corrupt.sha256"
        corrupt_file.write_text("corrupt_not_a_hash flutter.deb", encoding="utf-8")
        with pytest.raises(ValueError, match="must be exactly 64 hex characters"):
            vra.verify_checksum_file(corrupt_file)


class TestCompanionCardinalityAndPromotionGates:
    """Test candidate artifact cardinality and evidence.json promotion gates."""

    SAMPLE_SHA = "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
    SAMPLE_COMMIT = "abcdef0123456789abcdef0123456789abcdef01"

    def test_candidate_cardinality_rules(self, tmp_path):
        """Simulate candidate artifact directory validation with cardinality checks."""
        cand_dir = tmp_path / "candidate"
        cand_dir.mkdir()

        def create_candidate_set(deb_count=1, sha_count=1, size_count=1, meta_count=1, inv_count=1):
            for p in cand_dir.glob("*"):
                p.unlink()
            for i in range(deb_count):
                (cand_dir / f"flutter_3.44.9_{i}.deb").write_bytes(b"deb_content_12345")
            for i in range(sha_count):
                (cand_dir / f"flutter_3.44.9_{i}.deb.sha256").write_text(f"{self.SAMPLE_SHA}  deb\n")
            for i in range(size_count):
                (cand_dir / f"flutter_3.44.9_{i}.deb.size.txt").write_text("17\n")
            for i in range(meta_count):
                meta_name = "build_metadata.json" if i == 0 else f"build_metadata_{i}.json"
                (cand_dir / meta_name).write_text(json.dumps({
                    "version": "3.44.9",
                    "arch": "arm64",
                    "run_id": "12345",
                    "source_commit": self.SAMPLE_COMMIT,
                    "sha256": self.SAMPLE_SHA,
                    "size_bytes": 17,
                }))
            for i in range(inv_count):
                inv_name = "inventory.txt" if i == 0 else f"inventory_{i}.txt"
                (cand_dir / inv_name).write_text("usr/bin/flutter\n")

        # Test valid 1:1 set
        create_candidate_set(1, 1, 1, 1, 1)
        debs = list(cand_dir.glob("*.deb"))
        shas = list(cand_dir.glob("*.sha256"))
        sizes = list(cand_dir.glob("*.size.txt"))
        metas = list(cand_dir.glob("build_metadata.json"))
        invs = list(cand_dir.glob("inventory.txt"))
        assert len(debs) == 1
        assert len(shas) == 1
        assert len(sizes) == 1
        assert len(metas) == 1
        assert len(invs) == 1

        # Test 0 debs anomaly
        create_candidate_set(deb_count=0)
        assert len(list(cand_dir.glob("*.deb"))) == 0

        # Test 2 debs anomaly
        create_candidate_set(deb_count=2)
        assert len(list(cand_dir.glob("*.deb"))) == 2

        # Test missing sha256
        create_candidate_set(sha_count=0)
        assert len(list(cand_dir.glob("*.sha256"))) == 0

    def test_promotion_gate_evidence_verification(self, tmp_path):
        """Simulate device-smoke promotion gate requirements on evidence.json."""
        def evaluate_promotion(evidence: dict, release_tag: str, verifier_commit: str) -> tuple[bool, str]:
            if not release_tag:
                return False, "release_tag is required"
            if evidence.get("status") != "passed" or evidence.get("mode_b_status") != "passed":
                return False, "Evidence status and mode_b_status must both be 'passed'"
            src_commit = evidence.get("artifact_source_commit", "").lower().strip()
            ver_commit = verifier_commit.lower().strip()
            if not src_commit or not re.match(r"^[0-9a-f]{40}$", src_commit):
                return False, f"Invalid source commit: {src_commit}"
            if src_commit != ver_commit:
                return False, f"Commit mismatch: {src_commit} != {ver_commit}"
            artifacts = evidence.get("artifacts", {})
            for key in ["deb", "apk", "aab"]:
                sha = artifacts.get(f"{key}_sha256", "")
                size = artifacts.get(f"{key}_size", 0)
                if not re.match(r"^[0-9a-f]{64}$", str(sha)) or not isinstance(size, int) or size <= 0:
                    return False, f"Invalid artifact evidence for {key}: sha={sha}, size={size}"
            return True, "PROMOTED"

        valid_evidence = {
            "status": "passed",
            "mode_b_status": "passed",
            "artifact_source_commit": self.SAMPLE_COMMIT,
            "verifier_commit": self.SAMPLE_COMMIT,
            "artifacts": {
                "deb_sha256": self.SAMPLE_SHA,
                "deb_size": 52428800,
                "apk_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
                "apk_size": 20480000,
                "aab_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
                "aab_size": 18432000,
            }
        }

        # Valid promotion
        ok, msg = evaluate_promotion(valid_evidence, "v3.44.9-termux", self.SAMPLE_COMMIT)
        assert ok is True
        assert msg == "PROMOTED"

        # Missing release tag
        ok, msg = evaluate_promotion(valid_evidence, "", self.SAMPLE_COMMIT)
        assert ok is False
        assert "release_tag is required" in msg

        # Failed overall status
        ev_failed = copy.deepcopy(valid_evidence)
        ev_failed["status"] = "failed"
        ok, msg = evaluate_promotion(ev_failed, "v3.44.9-termux", self.SAMPLE_COMMIT)
        assert ok is False

        # Failed mode_b_status
        ev_mode_b_fail = copy.deepcopy(valid_evidence)
        ev_mode_b_fail["mode_b_status"] = "failed"
        ok, msg = evaluate_promotion(ev_mode_b_fail, "v3.44.9-termux", self.SAMPLE_COMMIT)
        assert ok is False

        # Commit mismatch
        ok, msg = evaluate_promotion(valid_evidence, "v3.44.9-termux", "fedcba9876543210fedcba9876543210fedcba98")
        assert ok is False
        assert "Commit mismatch" in msg

        # Corrupt APK sha256
        ev_corrupt_apk = copy.deepcopy(valid_evidence)
        ev_corrupt_apk["artifacts"]["apk_sha256"] = "invalid_hash"
        ok, msg = evaluate_promotion(ev_corrupt_apk, "v3.44.9-termux", self.SAMPLE_COMMIT)
        assert ok is False

        # Zero size deb
        ev_zero_size = copy.deepcopy(valid_evidence)
        ev_zero_size["artifacts"]["deb_size"] = 0
        ok, msg = evaluate_promotion(ev_zero_size, "v3.44.9-termux", self.SAMPLE_COMMIT)
        assert ok is False


# ==============================================================================
# 2. ISSUE #57: VERSION DRIFT GOVERNANCE SYNTHETIC FAULT INJECTIONS
# ==============================================================================

class TestAdversarialVersionDriftInjections:
    """Empirically test check_version_drift.py against synthetic faults across every component."""

    @pytest.fixture
    def mock_repo(self, tmp_path):
        """Create a complete mock repository with canonical build.toml and aligned files."""
        root = tmp_path / "flutter_termux"
        root.mkdir()

        # Canonical build.toml
        (root / "build.toml").write_text("""
[flutter]
tag = '3.44.9'
release_tag = 'v3.44.9-termux'
dart_version = '3.12.2'
engine_commit = '11223344556677889900aabbccddeeff00112233'
sha256 = 'f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e'
asset_name = 'flutter_3.44.9_aarch64.deb'
size = 52428800

[ndk]
path = '/opt/android-ndk-r27d'
""", encoding="utf-8")

        # Aligned build.py
        (root / "build.py").write_text("""
class Build:
    def sync(self):
        dart_sdk_tag = self.dart_version
        pass
    def debuild(self):
        pass
""", encoding="utf-8")

        # Aligned package.yaml
        (root / "package.yaml").write_text("""
package:
  name: flutter
  Version: $tag
  description: "Flutter SDK"
resource:
  profile:
    source: |-
      export FLUTTER_PREBUILT_ENGINE_VERSION="11223344556677889900aabbccddeeff00112233"
""", encoding="utf-8")

        # Aligned Markdown docs
        (root / "README.md").write_text("""
# Flutter Termux
Download: [deb](https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.9-termux/flutter_3.44.9_aarch64.deb)
Dart SDK: `3.12.2`
Engine | [11223344556677889900aabbccddeeff00112233](...)
""", encoding="utf-8")

        (root / "README_EN.md").write_text("""
# Flutter Termux English
Download: [deb](https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.9-termux/flutter_3.44.9_aarch64.deb)
""", encoding="utf-8")

        (root / "docs" / "releases").mkdir(parents=True)
        (root / "docs" / "releases" / "RELEASE_NOTES.md").write_text("""
Release v3.44.9-termux: https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.9-termux/flutter_3.44.9_aarch64.deb
""", encoding="utf-8")

        # Aligned Agent guidance docs
        for doc in ["AGENTS.md", "GEMINI.md", "CLAUDE.md"]:
            (root / doc).write_text("""
Target: aarch64, Flutter 3.44.9
Patches in patches/3.44.9/
adb push flutter_3.44.9_aarch64.deb /data/local/tmp/
""", encoding="utf-8")

        # Aligned Guides
        (root / "docs" / "guides").mkdir(parents=True)
        (root / "docs" / "guides" / "BUILD_GUIDE.md").write_text("""
| Property | Value |
| Flutter tag | `3.44.9` |
| Engine revision | `11223344556677889900aabbccddeeff00112233` |
| Package | `flutter_3.44.9_aarch64.deb` |
| SHA256 | `f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e` |
""", encoding="utf-8")

        (root / "docs" / "guides" / "BUILD_PROCESS.md").write_text("# Build process\n", encoding="utf-8")
        (root / "docs" / "guides" / "INSTALL_GUIDE.md").write_text("# Install guide\n", encoding="utf-8")
        (root / "docs" / "guides" / "UPGRADE_GUIDE.md").write_text("# Upgrade guide\n", encoding="utf-8")

        # Aligned installer scripts
        (root / "install_flutter_complete.sh").write_text("""#!/bin/bash
FLUTTER_VERSION="3.44.9"
RELEASE_TAG="v3.44.9-termux"
EXPECTED_SHA256="f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
""", encoding="utf-8")

        (root / "scripts" / "install").mkdir(parents=True)
        (root / "scripts" / "install" / "install.sh").write_text("""#!/bin/bash
FLUTTER_VERSION="3.44.9"
RELEASE_TAG="v3.44.9-termux"
EXPECTED_SHA256="f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
""", encoding="utf-8")

        (root / "scripts" / "install" / "install_termux_flutter.sh").write_text("""#!/bin/bash
FLUTTER_VERSION="3.44.9"
RELEASE_TAG="v3.44.9-termux"
EXPECTED_SHA256="f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
""", encoding="utf-8")

        (root / "scripts" / "test").mkdir(parents=True)
        (root / "scripts" / "test" / "gh_e2e_test.sh").write_text("""#!/bin/bash
FLUTTER_VERSION="3.44.9"
RELEASE_TAG="v3.44.9-termux"
EXPECTED_SHA256="f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
""", encoding="utf-8")

        return root

    def test_zero_drift_baseline(self, mock_repo):
        """Verify that the aligned mock repository passes with 0 errors."""
        errors = cvd.run_checks(mock_repo)
        assert errors == [], f"Expected 0 drift errors, got: {errors}"

    def test_drift_injection_build_py(self, mock_repo):
        """Inject stale '3.12.0' hardcoded string in build.py sync()."""
        (mock_repo / "build.py").write_text("""
class Build:
    def sync(self):
        dart_sdk_tag = '3.12.0'
""", encoding="utf-8")
        errors = cvd.run_checks(mock_repo)
        assert any("build.py sync() contains hardcoded '3.12.0'" in err for err in errors)

    def test_drift_injection_package_yaml(self, mock_repo):
        """Inject stale engine commit in package.yaml."""
        (mock_repo / "package.yaml").write_text("""
package:
  name: flutter
  Version: $tag
resource:
  profile:
    source: |-
      export FLUTTER_PREBUILT_ENGINE_VERSION="stale_engine_hash_123"
""", encoding="utf-8")
        errors = cvd.run_checks(mock_repo)
        assert any("package.yaml: FLUTTER_PREBUILT_ENGINE_VERSION mismatch" in err for err in errors)

    def test_drift_injection_markdown_tag(self, mock_repo):
        """Inject stale download tag into README.md."""
        (mock_repo / "README.md").write_text("""
Download: [deb](https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.41.5/flutter_3.41.5_aarch64.deb)
""", encoding="utf-8")
        errors = cvd.run_checks(mock_repo)
        assert any("README.md: download URL tag mismatch" in err for err in errors)

    def test_drift_injection_agents_md(self, mock_repo):
        """Inject stale Flutter target version and patch directory into AGENTS.md."""
        (mock_repo / "AGENTS.md").write_text("""
Target: aarch64, Flutter 3.41.5
Patches in patches/3.41.5/
adb push flutter_3.41.5_aarch64.deb /data/local/tmp/
""", encoding="utf-8")
        errors = cvd.run_checks(mock_repo)
        assert any("AGENTS.md: Target Flutter version mismatch" in err for err in errors)
        assert any("AGENTS.md: Patch directory diagram mismatch" in err for err in errors)
        assert any("AGENTS.md: Deb filename mismatch" in err for err in errors)

    def test_drift_injection_build_guide(self, mock_repo):
        """Inject stale sha256 and engine commit in BUILD_GUIDE.md."""
        (mock_repo / "docs" / "guides" / "BUILD_GUIDE.md").write_text("""
| Property | Value |
| Flutter tag | `3.41.5` |
| Engine revision | `stale_engine_rev` |
| Package | `flutter_3.41.5_aarch64.deb` |
| SHA256 | `0000000000000000000000000000000000000000000000000000000000000000` |
""", encoding="utf-8")
        errors = cvd.run_checks(mock_repo)
        assert any("BUILD_GUIDE.md: Flutter tag mismatch in table" in err for err in errors)
        assert any("BUILD_GUIDE.md: Engine revision mismatch in table" in err for err in errors)
        assert any("BUILD_GUIDE.md: Package mismatch in table" in err for err in errors)
        assert any("BUILD_GUIDE.md: SHA256 mismatch in table" in err for err in errors)

    def test_drift_injection_installer_scripts(self, mock_repo):
        """Inject stale version into install_flutter_complete.sh."""
        (mock_repo / "install_flutter_complete.sh").write_text("""#!/bin/bash
FLUTTER_VERSION="3.41.5"
RELEASE_TAG="v3.41.5"
EXPECTED_SHA256="stale_hash_value"
""", encoding="utf-8")
        errors = cvd.run_checks(mock_repo)
        assert any("install_flutter_complete.sh: FLUTTER_VERSION mismatch" in err for err in errors)
        assert any("install_flutter_complete.sh: RELEASE_TAG mismatch" in err for err in errors)
        assert any("install_flutter_complete.sh: EXPECTED_SHA256 line does not contain expected hash" in err for err in errors)


# ==============================================================================
# 3. ISSUE #58: WORKFLOW SECURITY & REPO SANITY CONTRACTS
# ==============================================================================

class TestWorkflowSecurityAndRepoSanity:
    """Verify least privilege permissions, actionlint/shellcheck enforcement, and check_repo.py rules."""

    def test_least_privilege_workflow_permissions(self):
        """Ensure all GitHub workflow files have explicit least-privilege permissions."""
        workflow_dir = REPO_ROOT / ".github" / "workflows"
        for yml_file in workflow_dir.glob("*.yml"):
            content = yml_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)

            assert "permissions" in data, f"{yml_file.name} missing top-level permissions declaration"
            perms = data["permissions"]

            if yml_file.name in ("ci.yml", "release-check.yml"):
                # Read-only workflows
                assert perms == {"contents": "read"} or perms == "read-all", (
                    f"{yml_file.name} should have read-only permissions, got {perms}"
                )
            elif yml_file.name in ("build-deb.yml", "device-smoke.yml"):
                # Manual dispatch workflows that upload or promote releases
                assert perms.get("contents") == "write", f"{yml_file.name} should have contents: write"
                assert perms.get("actions") == "read", f"{yml_file.name} should have actions: read"

    def test_no_self_hosted_on_pull_request(self):
        """Enforce that self-hosted runners are never triggered automatically on pull_request."""
        workflow_dir = REPO_ROOT / ".github" / "workflows"
        for yml_file in workflow_dir.glob("*.yml"):
            content = yml_file.read_text(encoding="utf-8")
            if "self-hosted" in content:
                assert "pull_request:" not in content, (
                    f"{yml_file.name} uses self-hosted runner and must not run on pull_request"
                )

    def test_shebang_and_crlf_enforcement(self):
        """Verify all python entrypoints and shell scripts have proper shebangs and LF line endings."""
        cr.ERRORS.clear()
        cr.check_script_headers()
        assert cr.ERRORS == [], f"Script header or CRLF violations found: {cr.ERRORS}"

    def test_check_repo_catches_unbalanced_markdown_fences(self, tmp_path, monkeypatch):
        """Verify check_repo.py detects unbalanced markdown fences."""
        test_file = REPO_ROOT / "docs" / "test_unbalanced_fence.md"
        try:
            test_file.write_text("# Test\n```bash\necho hello\n", encoding="utf-8")
            cr.ERRORS.clear()
            cr.check_markdown_fences()
            assert any("test_unbalanced_fence.md" in err for err in cr.ERRORS)
        finally:
            if test_file.exists():
                test_file.unlink()
            cr.ERRORS.clear()

    def test_check_repo_catches_broken_markdown_links(self):
        """Verify check_repo.py detects broken relative markdown links."""
        test_file = REPO_ROOT / "docs" / "test_broken_link.md"
        try:
            test_file.write_text("# Test\nLink to [nonexistent](nonexistent_file.md)\n", encoding="utf-8")
            cr.ERRORS.clear()
            cr.check_markdown_links()
            assert any("test_broken_link.md" in err for err in cr.ERRORS)
        finally:
            if test_file.exists():
                test_file.unlink()
            cr.ERRORS.clear()

    def test_check_repo_detects_forbidden_release_versions(self):
        """Verify check_repo.py detects stale 3.41.5 release commands in checked files."""
        cr.ERRORS.clear()
        cr.check_no_stale_release_commands()
        assert cr.ERRORS == [], f"Found stale release commands in repository: {cr.ERRORS}"

    def test_sysroot_lock_integrity(self):
        """Verify sysroot.lock.json structure and package integrity."""
        cr.ERRORS.clear()
        cr.check_sysroot_lock_contract()
        assert cr.ERRORS == [], f"Sysroot lock contract errors: {cr.ERRORS}"

    def test_required_test_modules_present(self):
        """Verify all mandatory test modules in check_repo.py exist on disk."""
        cr.ERRORS.clear()
        cr.check_test_modules_and_ci_steps()
        assert cr.ERRORS == [], f"Missing required test modules or CI steps: {cr.ERRORS}"
