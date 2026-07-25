#!/usr/bin/env python3
"""Check for version drift across configuration, scripts, and documentation files.

Reads single source of truth version parameters from `build.toml` and verifies that
all references in README, RELEASE_NOTES, installer scripts, and build scripts match.
"""
from __future__ import annotations

import re
import sys
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


def fail(msg: str) -> None:
    ERRORS.append(msg)


def load_build_config() -> dict[str, str]:
    config_path = ROOT / "build.toml"
    if not config_path.is_file():
        fail(f"build.toml not found at {config_path}")
        return {}

    if tomllib is None:
        fail("Neither tomllib nor tomli is available to parse build.toml")
        return {}

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    flutter_cfg = data.get("flutter", {})
    tag = flutter_cfg.get("tag", "")
    release_tag = flutter_cfg.get("release_tag", "")
    dart_version = flutter_cfg.get("dart_version", "")
    sha256 = flutter_cfg.get("sha256", "")
    asset_name = flutter_cfg.get("asset_name", "")

    if not tag:
        fail("build.toml [flutter] missing 'tag'")
    if not release_tag:
        fail("build.toml [flutter] missing 'release_tag'")
    if not dart_version:
        fail("build.toml [flutter] missing 'dart_version'")

    return {
        "tag": str(tag),
        "release_tag": str(release_tag),
        "dart_version": str(dart_version),
        "sha256": str(sha256),
        "asset_name": str(asset_name) or f"flutter_{tag}_aarch64.deb",
    }


def check_build_py(cfg: dict[str, str]) -> None:
    build_py = ROOT / "build.py"
    if not build_py.is_file():
        fail("build.py missing")
        return
    text = build_py.read_text(encoding="utf-8")

    sync_match = re.search(r"def sync\(.*?\):(.*?)(?=\n    def |\Z)", text, re.DOTALL)
    if sync_match:
        sync_text = sync_match.group(1)
        if "'3.12.0'" in sync_text or '"3.12.0"' in sync_text:
            fail("build.py sync() contains hardcoded '3.12.0' Dart SDK version string; should use self.dart_version")
    else:
        fail("build.py missing sync() method")


def check_markdown_docs(cfg: dict[str, str]) -> None:
    release_tag = cfg["release_tag"]

    docs_to_check = [
        "README.md",
        "README_EN.md",
        "docs/releases/RELEASE_NOTES.md",
    ]

    for rel_path in docs_to_check:
        path = ROOT / rel_path
        if not path.is_file():
            continue

        text = path.read_text(encoding="utf-8")

        # Check for release download URLs tag consistency
        url_matches = re.findall(r"releases/download/([^/]+)/", text)
        for found_tag in url_matches:
            if found_tag != release_tag:
                fail(f"{rel_path}: download URL tag mismatch: found '{found_tag}', expected '{release_tag}'")


def check_installer_scripts(cfg: dict[str, str]) -> None:
    tag = cfg["tag"]
    release_tag = cfg["release_tag"]

    scripts = [
        "install_flutter_complete.sh",
        "scripts/install/install.sh",
        "scripts/install/install_termux_flutter.sh",
        "scripts/test/gh_e2e_test.sh",
    ]

    for rel_path in scripts:
        path = ROOT / rel_path
        if not path.is_file():
            continue

        text = path.read_text(encoding="utf-8")

        ver_match = re.search(r'FLUTTER_VERSION=["\']?([^"\':\s\n}]+)', text)
        if ver_match:
            found_ver = ver_match.group(1).lstrip("v")
            if found_ver != tag and not found_ver.startswith("${"):
                fail(f"{rel_path}: FLUTTER_VERSION mismatch: found '{found_ver}', expected '{tag}'")

        tag_match = re.search(r'RELEASE_TAG=["\']?([^"\':\s\n}]+)', text)
        if tag_match:
            found_tag = tag_match.group(1)
            if found_tag != release_tag and not found_tag.startswith("${"):
                fail(f"{rel_path}: RELEASE_TAG mismatch: found '{found_tag}', expected '{release_tag}'")

        sha_match = re.search(r'EXPECTED_SHA256=.*', text)
        if sha_match and cfg.get("sha256"):
            line = sha_match.group(0)
            if cfg["sha256"] not in line:
                fail(f"{rel_path}: EXPECTED_SHA256 line does not contain expected hash '{cfg['sha256']}': {line}")


def main() -> int:
    cfg = load_build_config()
    if not cfg:
        print("Failed to load build config from build.toml", file=sys.stderr)
        return 1

    check_build_py(cfg)
    check_markdown_docs(cfg)
    check_installer_scripts(cfg)

    if ERRORS:
        print("Version drift check FAILED:", file=sys.stderr)
        for err in ERRORS:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("Version drift check PASSED (all files aligned with build.toml).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
