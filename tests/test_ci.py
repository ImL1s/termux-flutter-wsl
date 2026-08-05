import os
import sys
import subprocess
from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "ci" / "verify_release_asset.py"
CHECK_REPO_SCRIPT = REPO_ROOT / "scripts" / "ci" / "check_repo.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))
from verify_release_asset import validate_sha256_format, verify_checksum_file


def test_ci_workflow_step_verification():
    """Verify that ci.yml contains job steps for pytest, shellcheck, and actionlint."""
    assert CI_WORKFLOW.is_file(), "ci.yml must exist"
    data = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    assert isinstance(data, dict), "ci.yml must be a valid mapping"
    assert "jobs" in data, "ci.yml must define jobs"

    repo_sanity = data["jobs"].get("repo-sanity")
    assert repo_sanity is not None, "ci.yml must contain repo-sanity job"

    steps = repo_sanity.get("steps", [])
    step_runs = [s.get("run", "") for s in steps if "run" in s]

    assert any("pytest" in run for run in step_runs), "ci.yml must contain a step executing pytest"
    assert any("shellcheck" in run for run in step_runs), "ci.yml must contain a step executing shellcheck"
    assert any("actionlint" in run for run in step_runs), "ci.yml must contain a step executing actionlint"


def test_verify_release_asset_sha256_format_validation():
    """Test strict SHA256 hex format validation in verify_release_asset.py."""
    valid_sha = "66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc706000"
    assert validate_sha256_format(valid_sha) == valid_sha.lower()

    mixed_case = "66A7099324C0D7094D604AA92ABEEC87B7A29B8E0BC697B819E0CD91FC706000"
    assert validate_sha256_format(mixed_case) == valid_sha.lower()

    # Missing / None
    with pytest.raises(ValueError, match="missing or empty"):
        validate_sha256_format(None)

    # Empty string
    with pytest.raises(ValueError, match="empty"):
        validate_sha256_format("   ")

    # Invalid length (63 chars)
    with pytest.raises(ValueError, match="Invalid SHA256 hex format"):
        validate_sha256_format("66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc70600")

    # Non-hex characters
    with pytest.raises(ValueError, match="Invalid SHA256 hex format"):
        validate_sha256_format("66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc70600Z")


def test_verify_checksum_file_validation(tmp_path):
    """Test checksum file verification helper in verify_release_asset.py."""
    valid_sha = "66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc706000"
    sha_file = tmp_path / "test.sha256"

    # Valid file content
    sha_file.write_text(f"{valid_sha}  flutter_3.44.2_aarch64.deb\n")
    assert verify_checksum_file(sha_file) == valid_sha.lower()

    # Empty file
    empty_file = tmp_path / "empty.sha256"
    empty_file.write_text("")
    with pytest.raises(ValueError, match="empty"):
        verify_checksum_file(empty_file)

    # Missing file
    missing_file = tmp_path / "missing.sha256"
    with pytest.raises(ValueError, match="missing"):
        verify_checksum_file(missing_file)

    # Invalid SHA256 in file
    invalid_file = tmp_path / "invalid.sha256"
    invalid_file.write_text("invalid_hash_string  asset.deb\n")
    with pytest.raises(ValueError, match="Invalid SHA256 hex format"):
        verify_checksum_file(invalid_file)


def test_lightweight_check_non_skip_sha256_validation(tmp_path):
    """Verify that LIGHTWEIGHT_CHECK=1 requires valid SHA256 format and fails on invalid/empty checksum."""
    # Create temp directory with invalid build.toml (invalid SHA256 format)
    bad_toml = tmp_path / "build.toml"
    bad_toml.write_text(
        '[flutter]\n'
        'tag = "3.44.2"\n'
        'release_tag = "v3.44.2-termux"\n'
        'asset_name = "flutter_3.44.2_aarch64.deb"\n'
        'sha256 = "INVALID_SHA256_FORMAT"\n'
    )

    env = os.environ.copy()
    env["LIGHTWEIGHT_CHECK"] = "1"

    # Run verify_release_asset.py in directory with invalid build.toml
    res = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT)],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1, f"LIGHTWEIGHT_CHECK should fail on invalid SHA256 format, got code {res.returncode}"
    assert "Invalid SHA256 hex format" in res.stderr or "Invalid SHA256 hex format" in res.stdout


def test_check_repo_script_execution():
    """Verify python scripts/ci/check_repo.py runs and passes cleanly."""
    res = subprocess.run(
        [sys.executable, str(CHECK_REPO_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"check_repo.py failed:\n{res.stderr}"
    assert "Repository sanity check passed." in res.stdout
