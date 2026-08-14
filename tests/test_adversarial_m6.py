"""Adversarial security and contract tests for Milestone 6 (CI depth & verification suite).

Tests:
1. Verify SHA256 strict validation in verify_release_asset.py (short hex, invalid chars, empty string, None, uppercase handling) in LIGHTWEIGHT_CHECK=1 mode.
2. Verify check_repo.py failure when pytest, shellcheck, or actionlint is missing from ci.yml.
3. Verify ci.yml YAML syntax and structural validity.
"""

import os
import sys
import json
import pytest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.ci.verify_release_asset as verify_release_asset
import scripts.ci.check_repo as check_repo


def test_sha256_validation_adversarial_formats(tmp_path, monkeypatch):
    """Verify verify_release_asset.py rejects invalid SHA256 formats even when LIGHTWEIGHT_CHECK=1."""
    invalid_sha256_cases = [
        "1234567890abcdef",  # short hex (16 chars)
        "66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc70600",   # 63 chars
        "66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc7060001",  # 65 chars
        "66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc70600g",  # non-hex char 'g'
        "ZZZZ099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc706000",  # non-hex char 'Z'
        "66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc706000\n", # trailing newline
        " 66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc706000 ", # leading/trailing whitespace
        "",  # empty string
    ]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LIGHTWEIGHT_CHECK", "1")

    for bad_sha in invalid_sha256_cases:
        encoded_sha = json.dumps(bad_sha)
        toml_content = f"""
[flutter]
release_tag = "v3.44.2-termux"
asset_name = "flutter_3.44.2_aarch64.deb"
sha256 = {encoded_sha}
size = 100
"""
        (tmp_path / "build.toml").write_text(toml_content, encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            verify_release_asset.main()
        assert exc_info.value.code == 1, f"Failed to reject invalid SHA256: '{bad_sha}'"


def test_sha256_validation_missing_sha256(tmp_path, monkeypatch):
    """Verify verify_release_asset.py rejects missing sha256 in build.toml."""
    toml_content = """
[flutter]
release_tag = "v3.44.2-termux"
asset_name = "flutter_3.44.2_aarch64.deb"
size = 100
"""
    (tmp_path / "build.toml").write_text(toml_content, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LIGHTWEIGHT_CHECK", "1")

    with pytest.raises(SystemExit) as exc_info:
        verify_release_asset.main()
    assert exc_info.value.code == 1


def test_sha256_uppercase_valid_in_lightweight_mode(tmp_path, monkeypatch):
    """Verify valid uppercase SHA256 hex is accepted and normalized."""
    uppercase_sha = "66A7099324C0D7094D604AA92ABEEC87B7A29B8E0BC697B819E0CD91FC706000"
    toml_content = f"""
[flutter]
release_tag = "v3.44.2-termux"
asset_name = "flutter_3.44.2_aarch64.deb"
sha256 = "{uppercase_sha}"
size = 100
"""
    (tmp_path / "build.toml").write_text(toml_content, encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LIGHTWEIGHT_CHECK", "1")

    class MockResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            data = {
                "assets": [
                    {
                        "name": "flutter_3.44.2_aarch64.deb",
                        "browser_download_url": "https://example.com/flutter.deb",
                        "size": 100,
                        "digest": f"sha256:{uppercase_sha.lower()}",
                    }
                ]
            }
            return json.dumps(data).encode("utf-8")

    monkeypatch.setattr(verify_release_asset.urllib.request, "urlopen", lambda req: MockResponse())

    with pytest.raises(SystemExit) as exc_info:
        verify_release_asset.main()

    assert exc_info.value.code == 0


def test_check_repo_fails_when_ci_yml_lacks_required_linters(monkeypatch, tmp_path):
    """Verify check_repo.py fails if pytest, shellcheck, or actionlint is omitted from ci.yml."""
    monkeypatch.setattr(check_repo, "ROOT", tmp_path)

    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    package_yaml = tmp_path / "package.yaml"
    package_yaml.write_text("""
resource:
  dart_bin: foo
  dartvm_bin: foo
  dartaotruntime: foo
  post_install: foo
""", encoding="utf-8")

    missing_tools = ["pytest", "shellcheck", "actionlint"]

    try:
        for tool in missing_tools:
            check_repo.ERRORS.clear()
            
            steps = [t for t in missing_tools if t != tool]
            ci_content = "name: CI\njobs:\n  repo-sanity:\n    runs-on: ubuntu-latest\n    steps:\n"
            for s in steps:
                if s == "shellcheck":
                    ci_content += "      - run: shellcheck --severity=error\n"
                elif s == "actionlint":
                    ci_content += "      - run: actionlint && curl -sSfL\n"
                else:
                    ci_content += f"      - run: {s}\n"

            ci_path = workflows_dir / "ci.yml"
            ci_path.write_text(ci_content, encoding="utf-8")

            check_repo.check_yaml_files()
            assert len(check_repo.ERRORS) > 0, f"check_repo failed to detect missing '{tool}' in ci.yml"
            assert any(f"missing {tool}" in err for err in check_repo.ERRORS)
    finally:
        check_repo.ERRORS.clear()


def test_ci_yml_curl_typo_and_shellcheck_severity_adversarial(monkeypatch, tmp_path):
    """Adversarial check: verify check_repo rejects curl -sSF typo or missing --severity flag in ci.yml."""
    monkeypatch.setattr(check_repo, "ROOT", tmp_path)

    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    package_yaml = tmp_path / "package.yaml"
    package_yaml.write_text("""
resource:
  dart_bin: foo
  dartvm_bin: foo
  dartaotruntime: foo
  post_install: foo
""", encoding="utf-8")

    # Case 1: missing --severity in shellcheck step
    ci_content_no_severity = """name: CI
jobs:
  repo-sanity:
    runs-on: ubuntu-latest
    steps:
      - run: pytest
      - run: shellcheck install_flutter_complete.sh
      - run: actionlint && curl -sSfL
"""
    (workflows_dir / "ci.yml").write_text(ci_content_no_severity, encoding="utf-8")
    try:
        check_repo.ERRORS.clear()
        check_repo.check_yaml_files()
        assert len(check_repo.ERRORS) > 0, "check_repo should fail when --severity= is missing from shellcheck step"
        assert any("missing shellcheck --severity flag" in err for err in check_repo.ERRORS)
    finally:
        check_repo.ERRORS.clear()

    # Case 2: missing curl -sSfL (e.g. using typo curl -sSF) in actionlint step
    ci_content_curl_typo = """name: CI
jobs:
  repo-sanity:
    runs-on: ubuntu-latest
    steps:
      - run: pytest
      - run: shellcheck --severity=error
      - run: actionlint && curl -sSF
"""
    (workflows_dir / "ci.yml").write_text(ci_content_curl_typo, encoding="utf-8")
    try:
        check_repo.ERRORS.clear()
        check_repo.check_yaml_files()
        assert len(check_repo.ERRORS) > 0, "check_repo should fail when curl -sSfL is missing from actionlint step"
        assert any("actionlint step must use curl -sSfL" in err for err in check_repo.ERRORS)
    finally:
        check_repo.ERRORS.clear()


def test_ci_yml_structure_strict_validation():
    """Verify actual repository .github/workflows/ci.yml structure and syntax."""
    ci_path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    assert ci_path.is_file(), "ci.yml file missing"

    text = ci_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    assert isinstance(data, dict), "ci.yml must be a YAML mapping"
    assert data.get("name") == "CI"
    # PyYAML parses unquoted 'on:' as boolean True
    on_trigger = data.get("on") or data.get(True)
    assert on_trigger is not None, "ci.yml missing 'on' trigger section"
    assert "permissions" in data
    assert data["permissions"].get("contents") == "read"
    assert "jobs" in data
    assert "repo-sanity" in data["jobs"]

    repo_sanity = data["jobs"]["repo-sanity"]
    assert repo_sanity.get("runs-on") == "ubuntu-latest"
    assert repo_sanity.get("timeout-minutes") == 20

    steps = repo_sanity.get("steps", [])
    step_runs = [s.get("run", "") for s in steps if isinstance(s, dict)]
    full_runs_text = "\n".join(step_runs)

    # Check execution of required commands
    assert "pytest" in full_runs_text
    assert "shellcheck" in full_runs_text
    assert "--severity=" in full_runs_text, "ci.yml must include shellcheck --severity filter"
    assert "actionlint" in full_runs_text
    assert "curl -sSfL" in full_runs_text, "ci.yml must use curl -sSfL"
    assert "curl -sSF " not in text and "curl -sSF\n" not in text, "ci.yml must not contain curl -sSF typo"
    assert "check_repo.py" in full_runs_text
    assert "check_version_drift.py" in full_runs_text


def test_check_repo_actual_pass():
    """Verify repository contract checker passes on current repository state."""
    check_repo.ERRORS.clear()
    exit_code = check_repo.main()
    assert exit_code == 0, f"check_repo failed with errors: {check_repo.ERRORS}"
