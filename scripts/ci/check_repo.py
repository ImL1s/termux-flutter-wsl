#!/usr/bin/env python3
"""Repository sanity checks for CI.

These checks intentionally stay lightweight so they can run on free
GitHub-hosted runners for every PR. They guard the release/docs/scripts
contracts that matter for this Termux Flutter build without attempting the
multi-hour engine build.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs requirements.txt first.
    yaml = None

ROOT = Path(__file__).resolve().parents[2]
ERRORS: list[str] = []


def fail(message: str) -> None:
    ERRORS.append(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require_file(path: str) -> None:
    if not (ROOT / path).is_file():
        fail(f"missing required file: {path}")


def check_markdown_fences() -> None:
    for path in sorted(ROOT.glob("**/*.md")):
        if any(part in {".git", "flutter", "sysroot", "reference_termux_flutter", ".omx", ".omc"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if text.count("```") % 2:
            fail(f"unbalanced markdown code fence: {path.relative_to(ROOT)}")


def check_no_stale_release_commands() -> None:
    stale_patterns = {
        "flutter_3.41.5_aarch64.deb": "old 3.41.5 deb download/install command",
        "releases/download/3.41.5": "old release URL without v3.44.0",
        "Clone Flutter 3.41.5": "old AGENTS clone comment",
    }
    checked = [
        "README.md",
        "README_EN.md",
        "INSTALL_GUIDE.md",
        "RELEASE_NOTES.md",
        "BUILD_GUIDE.md",
        "CLAUDE.md",
        "GEMINI.md",
        "AGENTS.md",
        "scripts/test/gh_e2e_test.sh",
    ]
    for rel in checked:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern, description in stale_patterns.items():
            if pattern in text:
                fail(f"{rel}: contains {description}: {pattern}")


def check_yaml_files() -> None:
    if yaml is None:
        fail("PyYAML is not installed; run pip install -r requirements.txt")
        return

    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            fail(f"workflow is not a mapping: {path.relative_to(ROOT)}")
            continue
        if "jobs" not in data:
            fail(f"workflow has no jobs: {path.relative_to(ROOT)}")
        text = path.read_text(encoding="utf-8")
        if "self-hosted" in text and re.search(r"(?m)^\s*pull_request\s*:", text):
            fail(f"self-hosted workflow must not run automatically on pull_request: {path.relative_to(ROOT)}")

    package = ROOT / "package.yaml"
    data = yaml.safe_load(package.read_text(encoding="utf-8"))
    resources = data.get("resource", {}) if isinstance(data, dict) else {}
    for key in ("dart_bin", "dartvm_bin", "dartaotruntime", "post_install"):
        if key not in resources:
            fail(f"package.yaml missing resource.{key}")


def check_post_install_contract() -> None:
    text = read("scripts/install/post_install.sh")
    required = [
        "PLATFORM_ABI_LIST",
        "Flutter Gradle plugin cache cleared",
        "forceNdkDownload() patched to early return",
        "Termux: map Android host to Linux artifacts",
        "Termux: allow linux build",
    ]
    for marker in required:
        if marker not in text:
            fail(f"post_install.sh missing marker: {marker}")


def check_installer_contract() -> None:
    text = read("install_flutter_complete.sh")
    if 'FLUTTER_VERSION="3.44.0"' not in text:
        fail("install_flutter_complete.sh default Flutter version is not 3.44.0")
    if 'NDK_VERSION="29.0.14206865"' not in text:
        fail("install_flutter_complete.sh default NDK version is not r29")
    if "android-ndk-r27" in text:
        fail("install_flutter_complete.sh still references removed NDK r27 downloads")


def check_ci_layout() -> None:
    for path in [
        ".github/workflows/ci.yml",
        ".github/workflows/build-deb.yml",
        ".github/workflows/device-smoke.yml",
        "scripts/ci/check_repo.py",
        "scripts/device/run_termux_smoke.ps1",
        "scripts/device/termux_smoke.sh",
        "scripts/test/gh_e2e_test.sh",
        "docs/CI_CD.md",
    ]:
        require_file(path)

    if (ROOT / "gh_e2e_test.sh").exists():
        fail("gh_e2e_test.sh should live under scripts/test/, not repository root")


def main() -> int:
    check_ci_layout()
    check_markdown_fences()
    check_no_stale_release_commands()
    check_yaml_files()
    check_post_install_contract()
    check_installer_contract()

    if ERRORS:
        print("Repository sanity check failed:", file=sys.stderr)
        for error in ERRORS:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Repository sanity check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
