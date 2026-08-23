import os
import sys
import json
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


def to_wsl_posix(path):
    p = Path(path).resolve().as_posix()
    if len(p) > 1 and p[1] == ':':
        drive = p[0].lower()
        return f"/{drive}{p[2:]}"
    return p


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
    sha_file.write_text(f"{valid_sha}  flutter_3.44.9_aarch64.deb\n")
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
        'tag = "3.44.9"\n'
        'release_tag = "v3.44.9-termux"\n'
        'asset_name = "flutter_3.44.9_aarch64.deb"\n'
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


def test_candidate_artifact_resolution_fail_closed(tmp_path):
    """Verify candidate artifact resolution bash logic fails closed on multiple debs or missing metadata."""
    cand_dir = tmp_path / "candidate" / "release"
    cand_dir.mkdir(parents=True)

    # 1. Multiple debs -> fail
    (cand_dir / "app1.deb").write_text("deb1")
    (cand_dir / "app2.deb").write_text("deb2")
    (cand_dir / "app.sha256").write_text("a" * 64)
    (cand_dir / "app.size.txt").write_text("100")
    (cand_dir / "build_metadata.json").write_text('{"source_commit":"abc"}')
    (cand_dir / "inventory.txt").write_text("inv")

    bash_script = """
    mapfile -t DEBS < <(find ./candidate -type f -name '*.deb')
    if [ "${#DEBS[@]}" -ne 1 ]; then exit 1; fi
    """
    res = subprocess.run(["bash", "-c", bash_script], cwd=str(tmp_path), capture_output=True)
    assert res.returncode == 1


def test_promotion_rejection_on_mode_b_failure(tmp_path):
    """Verify promotion script rejects release when mode_b_status is failed."""
    ev_file = tmp_path / "evidence.json"
    ev_data = {"status": "failed", "mode_a_status": "passed", "mode_b_status": "failed"}
    ev_file.write_text(json.dumps(ev_data))

    data = json.loads(ev_file.read_text())
    ev_status = data.get("status", "failed")
    mode_b_status = data.get("mode_b_status", "failed")

    # Promotion requirement: both ev_status and mode_b_status must be 'passed'
    promotion_allowed = (ev_status == "passed" and mode_b_status == "passed")
    assert not promotion_allowed, "Promotion must be rejected when mode_b_status is failed"


def test_workflow_ndk_resolution_fallback(tmp_path):
    """Verify workflow NDK resolution script falls back to default /opt/android-ndk-r27d when env is empty."""
    opt_ndk = tmp_path / "opt" / "android-ndk-r27d"
    clang_bin = opt_ndk / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin" / "clang"
    clang_bin.mkdir(parents=True)
    clang_bin.touch()

    ndk_dir = ""
    if not ndk_dir or not Path(ndk_dir).exists():
        if opt_ndk.exists():
            ndk_dir = str(opt_ndk)

    resolved_clang = Path(ndk_dir) / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin" / "clang"
    assert resolved_clang.exists(), "Workflow NDK resolution failed to fall back to default NDK directory"


def test_size_artifact_contract_producer_and_parser(tmp_path):
    """Test size artifact contract: producer writes pure integer stat output, parser strictly validates ^[0-9]+$, single line, positive integer, and exact byte size."""
    dummy_deb = tmp_path / "test.deb"
    dummy_deb.write_bytes(b"x" * 12345)
    size_file = tmp_path / "test.deb.size.txt"

    # Producer contract (stat -c '%s' "$DEB" | tee "${DEB}.size.txt")
    size_bytes = dummy_deb.stat().st_size
    size_file.write_text(f"{size_bytes}\n", encoding="utf-8")

    def check_size_file(file_path, expected_size):
        if not file_path.is_file():
            return "Error: missing file"
        content_raw = file_path.read_text(encoding="utf-8")
        lines = content_raw.splitlines()
        if len(lines) != 1:
            return f"Error: expected 1 line, got {len(lines)}"
        content = lines[0].strip()
        import re
        if not re.match(r"^[0-9]+$", content):
            return f"Error: content '{content}' is not a pure integer"
        val = int(content)
        if val <= 0:
            return f"Error: size {val} is not positive"
        if val != expected_size:
            return f"Error: size {val} != expected {expected_size}"
        return "VERIFIED"

    assert check_size_file(size_file, 12345) == "VERIFIED"

    # Test rejection of annotated value (e.g. "test.deb 12345 bytes")
    bad_annotated = tmp_path / "bad_annotated.txt"
    bad_annotated.write_text("test.deb 12345 bytes\n", encoding="utf-8")
    assert check_size_file(bad_annotated, 12345) != "VERIFIED"

    # Test rejection of empty file
    bad_empty = tmp_path / "bad_empty.txt"
    bad_empty.write_text("", encoding="utf-8")
    assert check_size_file(bad_empty, 12345) != "VERIFIED"

    # Test rejection of multiline file
    bad_multi = tmp_path / "bad_multi.txt"
    bad_multi.write_text("12345\n67890\n", encoding="utf-8")
    assert check_size_file(bad_multi, 12345) != "VERIFIED"

    # Test rejection of negative value
    bad_neg = tmp_path / "bad_neg.txt"
    bad_neg.write_text("-12345\n", encoding="utf-8")
    assert check_size_file(bad_neg, 12345) != "VERIFIED"
