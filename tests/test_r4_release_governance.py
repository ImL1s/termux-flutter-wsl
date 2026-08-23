"""Release Governance and Version Drift Governance Test Suite (Milestone M4: Track R4).

Dedicated unit, boundary, integration, and adversarial regression tests for:
- Issue #56: Release Governance (verify_release_asset.py, strict SHA256 hex/whitespace validation,
  size checking, lightweight vs full check, and companion metadata cardinality/contract).
- Issue #57: Version Drift Governance (check_version_drift.py, 0-drift invariant, SSOT synchronization
  from build.toml across build.py, package.yaml, documentation, and installer scripts).
"""

import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.ci.check_version_drift as check_version_drift
import scripts.ci.verify_release_asset as verify_release_asset
from scripts.ci.verify_release_asset import (
    validate_sha256_format,
    verify_checksum_file,
)


# ============================================================================
# Issue #56: Release Governance — SHA256 Syntax & Parsing Unit Tests
# ============================================================================

class TestSHA256FormatValidation:
    """Test strict 64-hex lowercase validation and corruption rejection in validate_sha256_format."""

    def test_valid_lowercase_sha256(self):
        valid_hash = "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
        result = validate_sha256_format(valid_hash)
        assert result == valid_hash
        assert result.islower()
        assert len(result) == 64

    def test_valid_uppercase_sha256_normalizes_to_lowercase(self):
        upper_hash = "F706406253586A5586F8A1E7FF0A09B5A7F029A8EA9F2E1225CE682F10550C9E"
        result = validate_sha256_format(upper_hash)
        assert result == upper_hash.lower()
        assert result.islower()
        assert len(result) == 64

    def test_valid_mixed_case_sha256(self):
        mixed_hash = "f706406253586A5586F8a1e7ff0A09b5A7F029A8EA9F2E1225ce682F10550c9e"
        result = validate_sha256_format(mixed_hash)
        assert result == mixed_hash.lower()
        assert result.islower()

    @pytest.mark.parametrize("bad_hash,reason", [
        ("1234567890abcdef", "too short (16 chars)"),
        ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9", "too short (63 chars)"),
        ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e1", "too long (65 chars)"),
        ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9g", "invalid character 'g'"),
        ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9z", "invalid character 'z'"),
        ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9-", "invalid symbol '-'"),
        ("f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9\u00e9", "unicode char"),
    ])
    def test_invalid_sha256_characters_or_length_rejected(self, bad_hash, reason):
        with pytest.raises(ValueError, match=r"Invalid SHA256 hex format"):
            validate_sha256_format(bad_hash)

    @pytest.mark.parametrize("whitespace_hash", [
        " f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e",
        "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e ",
        " f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e ",
        "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e\n",
        "\nf706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e",
        "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e\r\n",
        "\t\tf706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e",
    ])
    def test_whitespace_and_newline_strictly_rejected(self, whitespace_hash):
        with pytest.raises(ValueError, match=r"whitespace or newline"):
            validate_sha256_format(whitespace_hash)

    @pytest.mark.parametrize("empty_val", [None, "", "   ", "\n", 12345, []])
    def test_empty_or_non_string_rejected(self, empty_val):
        with pytest.raises(ValueError, match=r"missing or empty|empty"):
            validate_sha256_format(empty_val)


class TestChecksumFileParsing:
    """Test verify_checksum_file parsing of sha256 checksum files."""

    def test_standard_sha256sum_format(self, tmp_path):
        target = tmp_path / "asset.deb.sha256"
        valid_hash = "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
        target.write_text(f"{valid_hash}  flutter_3.44.9_aarch64.deb\n", encoding="utf-8")
        assert verify_checksum_file(target) == valid_hash

    def test_single_hash_file(self, tmp_path):
        target = tmp_path / "hash_only.sha256"
        valid_hash = "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
        target.write_text(f"{valid_hash}\n", encoding="utf-8")
        assert verify_checksum_file(target) == valid_hash

    def test_missing_checksum_file_raises(self, tmp_path):
        missing = tmp_path / "nonexistent.sha256"
        with pytest.raises(ValueError, match=r"Checksum file missing"):
            verify_checksum_file(missing)

    def test_empty_checksum_file_raises(self, tmp_path):
        empty_file = tmp_path / "empty.sha256"
        empty_file.write_text("   \n", encoding="utf-8")
        with pytest.raises(ValueError, match=r"Checksum file is empty"):
            verify_checksum_file(empty_file)

    def test_corrupt_checksum_in_file_raises(self, tmp_path):
        corrupt = tmp_path / "corrupt.sha256"
        corrupt.write_text("invalid_hash_string  flutter.deb\n", encoding="utf-8")
        with pytest.raises(ValueError, match=r"Invalid SHA256 hex format"):
            verify_checksum_file(corrupt)


# ============================================================================
# Issue #56: Release Governance — verify_release_asset.py Execution & Modes
# ============================================================================

class TestVerifyReleaseAssetExecution:
    """Test verify_release_asset.py CLI execution, lightweight check mode, and full verification."""

    def test_missing_build_toml_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc:
            verify_release_asset.main()
        assert exc.value.code == 1

    def test_missing_required_manifest_fields_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "build.toml").write_text("""
[flutter]
release_tag = "v3.44.9-termux"
# missing asset_name and sha256
""", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            verify_release_asset.main()
        assert exc.value.code == 1

    def test_invalid_size_in_manifest_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "build.toml").write_text("""
[flutter]
release_tag = "v3.44.9-termux"
asset_name = "flutter_3.44.9_aarch64.deb"
sha256 = "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
size = -10
""", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            verify_release_asset.main()
        assert exc.value.code == 1

    def test_lightweight_check_no_local_file_passes_syntax_verification(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LIGHTWEIGHT_CHECK", "1")
        (tmp_path / "build.toml").write_text("""
[flutter]
release_tag = "v3.44.9-termux"
asset_name = "flutter_3.44.9_aarch64.deb"
sha256 = "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
size = 500
""", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            verify_release_asset.main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "LIGHTWEIGHT_CHECK enabled" in captured.out

    def test_lightweight_check_with_matching_local_file_verifies_hash_and_size(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LIGHTWEIGHT_CHECK", "1")
        payload = b"test payload for deb packaging verification"
        computed_sha = hashlib.sha256(payload).hexdigest()
        computed_size = len(payload)

        asset_name = "flutter_3.44.9_aarch64.deb"
        (tmp_path / asset_name).write_bytes(payload)
        (tmp_path / "build.toml").write_text(f"""
[flutter]
release_tag = "v3.44.9-termux"
asset_name = "{asset_name}"
sha256 = "{computed_sha}"
size = {computed_size}
""", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            verify_release_asset.main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Local file SHA256 verified" in captured.out

    def test_lightweight_check_with_mismatched_local_hash_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LIGHTWEIGHT_CHECK", "1")
        asset_name = "flutter_3.44.9_aarch64.deb"
        (tmp_path / asset_name).write_bytes(b"tampered content")
        (tmp_path / "build.toml").write_text(f"""
[flutter]
release_tag = "v3.44.9-termux"
asset_name = "{asset_name}"
sha256 = "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
size = 16
""", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            verify_release_asset.main()
        assert exc.value.code == 1

    def test_lightweight_check_with_mismatched_local_size_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LIGHTWEIGHT_CHECK", "1")
        payload = b"content"
        computed_sha = hashlib.sha256(payload).hexdigest()
        asset_name = "flutter_3.44.9_aarch64.deb"
        (tmp_path / asset_name).write_bytes(payload)
        (tmp_path / "build.toml").write_text(f"""
[flutter]
release_tag = "v3.44.9-termux"
asset_name = "{asset_name}"
sha256 = "{computed_sha}"
size = 999999
""", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            verify_release_asset.main()
        assert exc.value.code == 1

    def test_release_event_tag_mismatch_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        event_json = tmp_path / "event.json"
        event_json.write_text(json.dumps({"release": {"tag_name": "v9.9.9-wrong"}}), encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_NAME", "release")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_json))

        (tmp_path / "build.toml").write_text("""
[flutter]
release_tag = "v3.44.9-termux"
asset_name = "flutter_3.44.9_aarch64.deb"
sha256 = "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
""", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            verify_release_asset.main()
        assert exc.value.code == 1

    @patch("urllib.request.urlopen")
    @patch("urllib.request.urlretrieve")
    def test_full_mode_successful_github_api_and_download_verification(self, mock_retrieve, mock_urlopen, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LIGHTWEIGHT_CHECK", raising=False)
        monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))

        payload = b"mock deb package content for full verification"
        computed_sha = hashlib.sha256(payload).hexdigest()
        computed_size = len(payload)
        asset_name = "flutter_3.44.9_aarch64.deb"

        (tmp_path / "build.toml").write_text(f"""
[flutter]
release_tag = "v3.44.9-termux"
asset_name = "{asset_name}"
sha256 = "{computed_sha}"
size = {computed_size}
""", encoding="utf-8")

        # Mock GitHub API release response with all 5 assets
        api_data = {
            "assets": [
                {
                    "name": asset_name,
                    "browser_download_url": f"https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.9-termux/{asset_name}",
                    "size": computed_size,
                    "digest": f"sha256:{computed_sha}",
                },
                {
                    "name": f"{asset_name}.sha256",
                    "browser_download_url": f"https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.9-termux/{asset_name}.sha256",
                },
                {
                    "name": f"{asset_name}.size.txt",
                    "browser_download_url": f"https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.9-termux/{asset_name}.size.txt",
                },
                {
                    "name": "inventory.txt",
                    "browser_download_url": f"https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.9-termux/inventory.txt",
                },
                {
                    "name": "build_metadata.json",
                    "browser_download_url": f"https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.9-termux/build_metadata.json",
                },
            ]
        }

        def fake_urlopen(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            resp = MagicMock()
            if "api.github.com" in url:
                resp.read.return_value = json.dumps(api_data).encode("utf-8")
            elif url.endswith(".sha256"):
                resp.read.return_value = f"{computed_sha}  {asset_name}\n".encode("utf-8")
            elif url.endswith(".size.txt"):
                resp.read.return_value = f"{computed_size}\n".encode("utf-8")
            elif url.endswith("build_metadata.json"):
                resp.read.return_value = json.dumps({"sha256": computed_sha, "size_bytes": computed_size}).encode("utf-8")
            else:
                resp.read.return_value = b"ok"
            m = MagicMock()
            m.__enter__.return_value = resp
            return m

        mock_urlopen.side_effect = fake_urlopen

        # Mock download writing target file
        def fake_download(url, dest):
            Path(dest).write_bytes(payload)
        mock_retrieve.side_effect = fake_download

        # Should complete without error
        verify_release_asset.main()
        assert (tmp_path / asset_name).is_file()

    @patch("urllib.request.urlopen")
    def test_full_mode_missing_asset_in_api_fails(self, mock_urlopen, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LIGHTWEIGHT_CHECK", raising=False)

        (tmp_path / "build.toml").write_text("""
[flutter]
release_tag = "v3.44.9-termux"
asset_name = "flutter_3.44.9_aarch64.deb"
sha256 = "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"
""", encoding="utf-8")

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"assets": []}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with pytest.raises(SystemExit) as exc:
            verify_release_asset.main()
        assert exc.value.code == 1


# ============================================================================
# Issue #56: Companion Metadata Contracts & Cardinality Validation
# ============================================================================

class TestCompanionMetadataContracts:
    """Test companion metadata structure and 1:1 cardinality constraints."""

    def test_companion_artifact_cardinality_rules(self, tmp_path):
        """Simulate device-smoke candidate set verification (exactly 1 of each required file)."""
        staging = tmp_path / "staging"
        staging.mkdir()

        deb = staging / "flutter_3.44.9_aarch64.deb"
        sha = staging / "flutter_3.44.9_aarch64.deb.sha256"
        size = staging / "flutter_3.44.9_aarch64.deb.size.txt"
        meta = staging / "build_metadata.json"
        inv = staging / "inventory.txt"
        evi = staging / "evidence.json"

        deb.write_bytes(b"content")
        sha.write_text(f"{hashlib.sha256(b'content').hexdigest()}  {deb.name}\n", encoding="utf-8")
        size.write_text("7\n", encoding="utf-8")
        meta.write_text(json.dumps({
            "commit": "5a2a6a42cce67f965cf540fcecf616faca624aa1",
            "build_timestamp": "2026-08-15T05:00:00Z",
            "flutter_tag": "3.44.9",
            "dart_version": "3.12.2",
            "architecture": "aarch64",
        }), encoding="utf-8")
        inv.write_text("bin/flutter\nbin/cache/dart-sdk/bin/dart\n", encoding="utf-8")
        evi.write_text(json.dumps({"status": "passed", "mode_b_status": "passed"}), encoding="utf-8")

        debs = list(staging.glob("*.deb"))
        shas = list(staging.glob("*.deb.sha256"))
        sizes = list(staging.glob("*.deb.size.txt"))
        metas = list(staging.glob("build_metadata.json"))
        invs = list(staging.glob("inventory.txt"))
        evis = list(staging.glob("evidence.json"))

        assert len(debs) == 1, "Must have exactly 1 .deb artifact"
        assert len(shas) == 1, "Must have exactly 1 .sha256 companion"
        assert len(sizes) == 1, "Must have exactly 1 .size.txt companion"
        assert len(metas) == 1, "Must have exactly 1 build_metadata.json"
        assert len(invs) == 1, "Must have exactly 1 inventory.txt"
        assert len(evis) == 1, "Must have exactly 1 evidence.json"

    def test_duplicate_artifact_violates_cardinality(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "flutter_3.44.9_aarch64.deb").write_bytes(b"deb1")
        (staging / "flutter_3.44.9_aarch64_copy.deb").write_bytes(b"deb2")
        debs = list(staging.glob("*.deb"))
        assert len(debs) != 1, "Multiple debs must violate singleton constraint"

    def test_evidence_json_promotion_gate_validation(self):
        valid_evidence = {"status": "passed", "mode_b_status": "passed"}
        assert valid_evidence["status"] == "passed"
        assert valid_evidence["mode_b_status"] == "passed"

        failed_evidence_1 = {"status": "failed", "mode_b_status": "passed"}
        assert failed_evidence_1["status"] != "passed"

        failed_evidence_2 = {"status": "passed", "mode_b_status": "failed"}
        assert failed_evidence_2["mode_b_status"] != "passed"


# ============================================================================
# Issue #57: Version Drift Governance — Invariants & Detection Tests
# ============================================================================

class TestVersionDriftGovernance:
    """Test check_version_drift.py and 0-drift invariant across all repository assets."""

    def test_current_repo_zero_drift_invariant(self):
        """Verify that current repository codebase has exactly 0 version drift."""
        errors = check_version_drift.run_checks(REPO_ROOT)
        assert errors == [], f"Repository has unexpected version drift: {errors}"

    def test_ssot_build_config_loading(self):
        cfg = check_version_drift.load_build_config(REPO_ROOT)
        assert cfg["tag"] == "3.44.9"
        assert cfg["release_tag"] == "v3.44.9-termux"
        assert cfg["dart_version"] == "3.12.2"
        assert cfg["engine_commit"] == "5a2a6a42cce67f965cf540fcecf616faca624aa1"
        assert cfg["sha256"] == "8b32041a11452b8d995ba45dcc2bb196e4d841410c46871853a6f4c24acddd20"
        assert cfg["asset_name"] == "flutter_3.44.9_aarch64.deb"

    def test_drift_detected_when_build_py_hardcodes_stale_dart(self, tmp_path):
        (tmp_path / "build.py").write_text("""
class Build:
    def sync(self):
        version = '3.12.0'
        return version
    def configure(self):
        pass
""", encoding="utf-8")
        cfg = {"dart_version": "3.12.2"}
        check_version_drift.ERRORS.clear()
        check_version_drift.check_build_py(cfg, tmp_path)
        assert len(check_version_drift.ERRORS) == 1
        assert "hardcoded '3.12.0'" in check_version_drift.ERRORS[0]

    def test_drift_detected_when_package_yaml_has_wrong_engine_version(self, tmp_path):
        (tmp_path / "package.yaml").write_text("""
control:
  Version: $tag
resource:
  profile:
    source: |-
      export FLUTTER_PREBUILT_ENGINE_VERSION="stale_commit_hash"
""", encoding="utf-8")
        cfg = {"engine_commit": "5a2a6a42cce67f965cf540fcecf616faca624aa1"}
        check_version_drift.ERRORS.clear()
        check_version_drift.check_package_yaml(cfg, tmp_path)
        assert len(check_version_drift.ERRORS) == 1
        assert "FLUTTER_PREBUILT_ENGINE_VERSION mismatch" in check_version_drift.ERRORS[0]

    def test_drift_detected_when_markdown_docs_have_stale_download_tag(self, tmp_path):
        (tmp_path / "README.md").write_text("""
[Download](https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.41.5-termux/flutter.deb)
""", encoding="utf-8")
        cfg = {
            "release_tag": "v3.44.9-termux",
            "dart_version": "3.12.2",
            "engine_commit": "5a2a6a42cce67f965cf540fcecf616faca624aa1",
        }
        check_version_drift.ERRORS.clear()
        check_version_drift.check_markdown_docs(cfg, tmp_path)
        assert len(check_version_drift.ERRORS) == 1
        assert "download URL tag mismatch" in check_version_drift.ERRORS[0]

    def test_drift_detected_when_agent_guidance_has_stale_target_version(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("""
- Target: aarch64, Flutter 3.41.5
""", encoding="utf-8")
        cfg = {
            "tag": "3.44.9",
            "asset_name": "flutter_3.44.9_aarch64.deb",
        }
        check_version_drift.ERRORS.clear()
        check_version_drift.check_agent_guidance_docs(cfg, tmp_path)
        assert len(check_version_drift.ERRORS) == 1
        assert "Target Flutter version mismatch" in check_version_drift.ERRORS[0]

    def test_drift_detected_when_agent_guidance_has_stale_patch_diagram(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("""
├── patches/3.35.0/
""", encoding="utf-8")
        cfg = {
            "tag": "3.44.9",
            "asset_name": "flutter_3.44.9_aarch64.deb",
        }
        check_version_drift.ERRORS.clear()
        check_version_drift.check_agent_guidance_docs(cfg, tmp_path)
        assert len(check_version_drift.ERRORS) == 1
        assert "Patch directory diagram mismatch" in check_version_drift.ERRORS[0]

    def test_drift_detected_when_build_guide_has_stale_sha256_in_table(self, tmp_path):
        guides_dir = tmp_path / "docs" / "guides"
        guides_dir.mkdir(parents=True)
        (guides_dir / "BUILD_GUIDE.md").write_text("""
| Flutter tag | `3.44.9` |
| SHA256 | `0000000000000000000000000000000000000000000000000000000000000000` |
""", encoding="utf-8")
        cfg = {
            "tag": "3.44.9",
            "asset_name": "flutter_3.44.9_aarch64.deb",
            "engine_commit": "5a2a6a42cce67f965cf540fcecf616faca624aa1",
            "sha256": "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e",
        }
        check_version_drift.ERRORS.clear()
        check_version_drift.check_guide_docs(cfg, tmp_path)
        assert len(check_version_drift.ERRORS) == 1
        assert "SHA256 mismatch in table" in check_version_drift.ERRORS[0]

    def test_drift_detected_when_installer_script_has_mismatched_version(self, tmp_path):
        (tmp_path / "install_flutter_complete.sh").write_text("""
FLUTTER_VERSION="3.35.0"
RELEASE_TAG="v3.35.0-termux"
EXPECTED_SHA256="wrong_hash"
""", encoding="utf-8")
        cfg = {
            "tag": "3.44.9",
            "release_tag": "v3.44.9-termux",
            "sha256": "f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e",
        }
        check_version_drift.ERRORS.clear()
        check_version_drift.check_installer_scripts(cfg, tmp_path)
        assert len(check_version_drift.ERRORS) == 3
        err_text = " ".join(check_version_drift.ERRORS)
        assert "FLUTTER_VERSION mismatch" in err_text
        assert "RELEASE_TAG mismatch" in err_text
        assert "EXPECTED_SHA256 line does not contain expected hash" in err_text
