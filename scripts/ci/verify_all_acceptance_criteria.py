#!/usr/bin/env python3
"""Acceptance Criteria Verification Runner.

Validates all requirements R1 to R4 in ORIGINAL_REQUEST.md and PROJECT.md:
1. Release URL tag repair (no stale download/v3.44.2/ URLs without -termux tag)
2. HTTP HEAD response for FLUTTER_DEB_URL (returns 200/302)
3. Single source of version management (release_tag in build.toml)
4. build.py sync() uses self.dart_version (no hardcoded '3.12.0' in sync())
5. check_version_drift.py execution
6. Python compilation check for build.py, package.py, sysroot.py, utils.py, check_repo.py, check_version_drift.py
7. build.py preflight execution
8. build.toml portable configuration (no hardcoded personal paths)
9. git check-ignore build.local.toml
10. install_flutter_complete.sh SHA256 validation & error handling
11. Shell syntax check (bash -n) on installer and test scripts
12. git diff --check whitespace check
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

ROOT = Path(__file__).resolve().parents[2]
ERRORS: list[str] = []
PASSED_CHECKS: list[str] = []

# Exclude historical specification files from URL tag search
EXCLUDE_URL_CHECK_FILES = {"ORIGINAL_REQUEST.md"}


def record_pass(check_name: str) -> None:
    PASSED_CHECKS.append(check_name)
    print(f"[PASS] {check_name}")


def record_fail(check_name: str, message: str) -> None:
    ERRORS.append(f"{check_name}: {message}")
    print(f"[FAIL] {check_name}: {message}", file=sys.stderr)


def check_stale_url_tags() -> None:
    check_name = "1. Release URL tag repair (grep download/v3.44.9/)"
    stale_pattern = "download/v3.44.9/"
    found_matches: list[str] = []

    search_paths: list[Path] = []
    # *.md and *.sh at root (excluding ORIGINAL_REQUEST.md)
    for p in ROOT.glob("*.md"):
        if p.name not in EXCLUDE_URL_CHECK_FILES:
            search_paths.append(p)
    for p in ROOT.glob("*.sh"):
        search_paths.append(p)

    # release/ and docs/ recursively
    for dir_name in ("release", "docs"):
        target_dir = ROOT / dir_name
        if target_dir.is_dir():
            for p in target_dir.rglob("*"):
                if p.is_file() and p.suffix in (".md", ".sh", ".txt", ".yml", ".yaml"):
                    search_paths.append(p)

    for path in sorted(set(search_paths)):
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            if stale_pattern in content:
                rel = path.relative_to(ROOT)
                found_matches.append(str(rel))
        except Exception as e:
            record_fail(check_name, f"Error reading {path}: {e}")

    if found_matches:
        record_fail(check_name, f"Found stale download/v3.44.9/ URL in: {', '.join(found_matches)}")
    else:
        record_pass(check_name)


def check_http_head_release_deb() -> None:
    check_name = "2. HTTP HEAD response for FLUTTER_DEB_URL"
    url = "https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.9-termux/flutter_3.44.9_aarch64.deb"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            method="HEAD",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            if status in (200, 301, 302, 307, 308):
                record_pass(f"{check_name} (HTTP {status})")
            else:
                record_fail(check_name, f"Unexpected HTTP status {status} for {url}")
    except Exception as e:
        record_fail(check_name, f"Failed HTTP HEAD request for {url}: {e}")


def check_build_toml_release_tag() -> None:
    check_name = "3. build.toml defines release_tag = 'v3.44.9-termux'"
    toml_path = ROOT / "build.toml"
    if not toml_path.is_file():
        record_fail(check_name, "build.toml does not exist")
        return

    content = toml_path.read_text(encoding="utf-8")
    if tomllib is not None:
        data = tomllib.loads(content)
        release_tag = data.get("flutter", {}).get("release_tag", "")
    else:
        m = re.search(r'release_tag\s*=\s*["\']([^"\']+)["\']', content)
        release_tag = m.group(1) if m else ""

    expected = "v3.44.9-termux"
    if release_tag == expected:
        record_pass(check_name)
    else:
        record_fail(check_name, f"Expected '{expected}', found '{release_tag}' in build.toml")


def check_build_py_no_hardcoded_dart_version() -> None:
    check_name = "4. build.py sync() has no hardcoded '3.12.0'"
    build_py = ROOT / "build.py"
    if not build_py.is_file():
        record_fail(check_name, "build.py does not exist")
        return

    text = build_py.read_text(encoding="utf-8")
    sync_match = re.search(r"def sync\(.*?\):(.*?)(?=\n    def |\Z)", text, re.DOTALL)
    if not sync_match:
        record_fail(check_name, "build.py sync() method not found")
        return

    sync_text = sync_match.group(1)
    if "'3.12.0'" in sync_text or '"3.12.0"' in sync_text:
        record_fail(check_name, "build.py sync() contains hardcoded '3.12.0' string")
    else:
        record_pass(check_name)


def check_version_drift_script() -> None:
    check_name = "5. Run scripts/ci/check_version_drift.py"
    script = ROOT / "scripts" / "ci" / "check_version_drift.py"
    res = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, cwd=ROOT)
    if res.returncode == 0:
        record_pass(check_name)
    else:
        record_fail(check_name, f"Script failed with code {res.returncode}:\n{res.stderr or res.stdout}")


def check_py_compile() -> None:
    check_name = "6. Python compilation check (py_compile)"
    files_to_compile = [
        "build.py",
        "package.py",
        "sysroot.py",
        "utils.py",
        "scripts/ci/check_repo.py",
        "scripts/ci/check_version_drift.py",
        "scripts/ci/verify_all_acceptance_criteria.py",
    ]
    cmd = [sys.executable, "-m", "py_compile"] + files_to_compile
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if res.returncode == 0:
        record_pass(check_name)
    else:
        record_fail(check_name, f"py_compile failed:\n{res.stderr}")


def check_build_preflight() -> None:
    check_name = "7. Run python build.py preflight"
    cmd = [sys.executable, "build.py", "preflight"]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if res.returncode == 0:
        record_pass(check_name)
    else:
        record_fail(check_name, f"build.py preflight returned non-zero code {res.returncode}:\n{res.stderr or res.stdout}")


def check_build_toml_no_personal_paths() -> None:
    check_name = "8. build.toml portable config (no hardcoded personal paths)"
    toml_path = ROOT / "build.toml"
    content = toml_path.read_text(encoding="utf-8")

    personal_patterns = [
        r"/home/\w+",
        r"C:\\Users\\\w+",
        r"/opt/android-ndk",
        r"D:\\OtherProject",
    ]
    found_issues = []
    for pattern in personal_patterns:
        matches = re.findall(pattern, content)
        if matches:
            found_issues.extend(matches)

    if found_issues:
        record_fail(check_name, f"Found personal path patterns in build.toml: {found_issues}")
    else:
        record_pass(check_name)


def check_git_ignore_build_local_toml() -> None:
    check_name = "9. Check git check-ignore build.local.toml"
    res = subprocess.run(["git", "check-ignore", "build.local.toml"], capture_output=True, text=True, cwd=ROOT)
    if res.returncode == 0 and "build.local.toml" in res.stdout:
        record_pass(check_name)
    else:
        record_fail(check_name, f"git check-ignore build.local.toml failed or output empty (exit code {res.returncode})")


def check_install_script_sha256_verification() -> None:
    check_name = "10. install_flutter_complete.sh SHA256 validation & error handling"
    script_path = ROOT / "install_flutter_complete.sh"
    lib_path = ROOT / "scripts" / "install" / "lib_common.sh"
    if not script_path.is_file():
        record_fail(check_name, "install_flutter_complete.sh does not exist")
        return

    content = script_path.read_text(encoding="utf-8")
    lib_content = lib_path.read_text(encoding="utf-8") if lib_path.is_file() else ""
    full_content = content + "\n" + lib_content

    has_expected_sha = "EXPECTED_SHA256=" in content
    has_sha_check = "sha256sum" in full_content or "verify_sha256" in content
    has_error_exit = "exit 1" in full_content or "exit $exit_code" in content

    if has_expected_sha and has_sha_check and has_error_exit:
        record_pass(check_name)
    else:
        record_fail(check_name, f"SHA256 validation missing components: expected_sha={has_expected_sha}, sha_check={has_sha_check}, exit_1={has_error_exit}")


def check_bash_syntax() -> None:
    check_name = "11. Shell syntax check (bash -n)"
    scripts = [
        "install_flutter_complete.sh",
        "scripts/install/install.sh",
        "scripts/install/install_termux_flutter.sh",
        "scripts/test/gh_e2e_test.sh",
    ]
    # Use relative POSIX paths with cwd=ROOT so Windows backslashes don't break bash argument parsing
    bash_bin = None
    if os.name == "nt":
        for candidate in [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ]:
            if os.path.exists(candidate):
                bash_bin = candidate
                break
    if not bash_bin:
        found = shutil.which("bash")
        if found and "system32" not in found.lower():
            bash_bin = found
    if not bash_bin:
        bash_bin = "bash"

    cmd = [bash_bin, "-n"] + scripts
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=15)
        if res.returncode == 0:
            record_pass(check_name)
        else:
            record_fail(check_name, f"bash -n syntax check failed:\n{res.stderr}")
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired) as e:
        record_fail(check_name, f"bash execution error: {e}")


def check_git_diff() -> None:
    check_name = "12. Run git diff --check"
    res = subprocess.run(
        ["git", "--no-pager", "diff", "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=dict(os.environ, PAGER="cat", GIT_PAGER="cat"),
    )
    if res.returncode == 0:
        record_pass(check_name)
    else:
        record_fail(check_name, f"git diff --check reported whitespace issues:\n{res.stdout or res.stderr}")


def main() -> int:
    print("============================================================")
    print("      Running Acceptance Criteria Verification Suite        ")
    print("============================================================")

    check_stale_url_tags()
    check_http_head_release_deb()
    check_build_toml_release_tag()
    check_build_py_no_hardcoded_dart_version()
    check_version_drift_script()
    check_py_compile()
    check_build_preflight()
    check_build_toml_no_personal_paths()
    check_git_ignore_build_local_toml()
    check_install_script_sha256_verification()
    check_bash_syntax()
    check_git_diff()

    print("============================================================")
    print(f"Summary: {len(PASSED_CHECKS)} passed, {len(ERRORS)} failed.")
    print("============================================================")

    if ERRORS:
        print("Verification Suite FAILED:", file=sys.stderr)
        for err in ERRORS:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("All Acceptance Criteria PASSED successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
