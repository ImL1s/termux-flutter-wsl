#!/usr/bin/env python3
"""Check for version drift across configuration, scripts, and documentation files.

Reads single source of truth version parameters from `build.toml` and verifies that
all references in README, RELEASE_NOTES, agent guidance, guides, package.yaml,
installer scripts, and build scripts match.
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


def load_build_config(root_path: Path | None = None) -> dict[str, str]:
    base_root = root_path or ROOT
    config_path = base_root / "build.toml"
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
    engine_commit = flutter_cfg.get("engine_commit", "")
    framework_revision = flutter_cfg.get("framework_revision", "")
    framework_commit_date = flutter_cfg.get("framework_commit_date", "")
    devtools_version = flutter_cfg.get("devtools_version", "")
    sha256 = flutter_cfg.get("sha256", "")
    size = flutter_cfg.get("size", "")
    asset_name = flutter_cfg.get("asset_name", "")

    if not tag:
        fail("build.toml [flutter] missing 'tag'")
    if not release_tag:
        fail("build.toml [flutter] missing 'release_tag'")
    if not dart_version:
        fail("build.toml [flutter] missing 'dart_version'")
    if not framework_revision:
        fail("build.toml [flutter] missing 'framework_revision'")
    if not framework_commit_date:
        fail("build.toml [flutter] missing 'framework_commit_date'")
    if not devtools_version:
        fail("build.toml [flutter] missing 'devtools_version'")

    return {
        "tag": str(tag),
        "release_tag": str(release_tag),
        "dart_version": str(dart_version),
        "engine_commit": str(engine_commit),
        "framework_revision": str(framework_revision),
        "framework_commit_date": str(framework_commit_date),
        "devtools_version": str(devtools_version),
        "sha256": str(sha256),
        "size": str(size) if size else "",
        "asset_name": str(asset_name) or f"flutter_{tag}_aarch64.deb",
    }


def check_build_py(cfg: dict[str, str], root_path: Path | None = None) -> None:
    base_root = root_path or ROOT
    build_py = base_root / "build.py"
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


def check_package_yaml(cfg: dict[str, str], root_path: Path | None = None) -> None:
    base_root = root_path or ROOT
    pkg_yaml = base_root / "package.yaml"
    if not pkg_yaml.is_file():
        return
    text = pkg_yaml.read_text(encoding="utf-8")
    if "Version: $package_version" not in text and "Version: $tag" not in text:
        fail("package.yaml control block must specify 'Version: $package_version' or 'Version: $tag'")
    if "FLUTTER_PREBUILT_ENGINE_VERSION=" in text:
        match = re.search(r'export FLUTTER_PREBUILT_ENGINE_VERSION=["\']?([^"\'\n]+)', text)
        if match:
            found_eng = match.group(1).strip()
            if found_eng not in ("$version", cfg.get("engine_commit")):
                fail(f"package.yaml: FLUTTER_PREBUILT_ENGINE_VERSION mismatch: found '{found_eng}', expected '$version' or '{cfg.get('engine_commit')}'")


def check_markdown_docs(cfg: dict[str, str], root_path: Path | None = None) -> None:
    base_root = root_path or ROOT
    release_tag = cfg["release_tag"]
    dart_version = cfg["dart_version"]
    engine_commit = cfg.get("engine_commit")

    docs_to_check = [
        "README.md",
        "README_EN.md",
        "docs/releases/RELEASE_NOTES.md",
    ]

    for rel_path in docs_to_check:
        path = base_root / rel_path
        if not path.is_file():
            continue

        text = path.read_text(encoding="utf-8")

        # Check for release download URLs tag consistency
        url_matches = re.findall(r"releases/download/([^/]+)/", text)
        for found_tag in url_matches:
            if found_tag != release_tag:
                fail(f"{rel_path}: download URL tag mismatch: found '{found_tag}', expected '{release_tag}'")

        # Check dart version in shields or table if present
        if "3.12.0" in text and dart_version != "3.12.0":
            fail(f"{rel_path}: Contains hardcoded '3.12.0' but expected '{dart_version}'")

        # Check package size if present
        if cfg.get("size") and "Size |" in text:
            formatted_size = f"{int(cfg['size']):,}"
            m = re.search(r"Size \|\s*`?([0-9,]+)`?", text)
            if m and m.group(1) != formatted_size:
                fail(f"{rel_path}: Package size mismatch: found '{m.group(1)}', expected '{formatted_size}'")

        # We can also check if engine commit matches
        if engine_commit and "Engine | [" in text:
            if engine_commit not in text:
                fail(f"{rel_path}: Missing expected engine commit '{engine_commit}'")


def check_agent_guidance_docs(cfg: dict[str, str], root_path: Path | None = None) -> None:
    base_root = root_path or ROOT
    tag = cfg["tag"]
    asset_name = cfg["asset_name"]

    guidance_docs = ["AGENTS.md", "GEMINI.md", "CLAUDE.md"]
    for rel_path in guidance_docs:
        path = base_root / rel_path
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")

        # Check for active target version specification
        target_match = re.search(r"Target:\s*aarch64,\s*Flutter\s+([0-9.]+)", text)
        if target_match:
            found_target_ver = target_match.group(1)
            if found_target_ver != tag:
                fail(f"{rel_path}: Target Flutter version mismatch: found '{found_target_ver}', expected '{tag}'")

        # Check version-specific patch path diagram references
        patch_dir_matches = re.findall(r"patches/([0-9.]+)/", text)
        for pdir in patch_dir_matches:
            if pdir != tag:
                fail(f"{rel_path}: Patch directory diagram mismatch: found 'patches/{pdir}/', expected 'patches/{tag}/'")

        # Check adb push deb file references
        adb_deb_matches = re.findall(r"flutter_[0-9.]+_aarch64\.deb", text)
        for deb in adb_deb_matches:
            if deb != asset_name:
                fail(f"{rel_path}: Deb filename mismatch: found '{deb}', expected '{asset_name}'")


def check_guide_docs(cfg: dict[str, str], root_path: Path | None = None) -> None:
    base_root = root_path or ROOT
    tag = cfg["tag"]
    asset_name = cfg["asset_name"]
    engine_commit = cfg.get("engine_commit")
    sha256 = cfg.get("sha256")

    guides = [
        "docs/guides/BUILD_GUIDE.md",
        "docs/guides/BUILD_PROCESS.md",
        "docs/guides/INSTALL_GUIDE.md",
        "docs/guides/UPGRADE_GUIDE.md",
    ]

    for rel_path in guides:
        path = base_root / rel_path
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")

        # Check version header table in any guide where present
        if "Flutter tag |" in text:
            m = re.search(r"Flutter tag \|\s*`([^`]+)`", text)
            if m and m.group(1) != tag:
                fail(f"{rel_path}: Flutter tag mismatch in table: found '{m.group(1)}', expected '{tag}'")
        if "Engine revision |" in text and engine_commit:
            m = re.search(r"Engine revision \|\s*`([^`]+)`", text)
            if m and m.group(1) != engine_commit:
                fail(f"{rel_path}: Engine revision mismatch in table: found '{m.group(1)}', expected '{engine_commit}'")
        if "Package |" in text:
            m = re.search(r"Package \|\s*`([^`]+)`", text)
            if m and m.group(1) != asset_name:
                fail(f"{rel_path}: Package mismatch in table: found '{m.group(1)}', expected '{asset_name}'")
        if "SHA256 |" in text and sha256:
            m = re.search(r"SHA256 \|\s*`([^`]+)`", text)
            if m and m.group(1).lower() != sha256.lower():
                fail(f"{rel_path}: SHA256 mismatch in table: found '{m.group(1)}', expected '{sha256}'")

        # Check package deb mentions across all guides
        for deb_match in re.finditer(r"flutter_(\d+\.\d+\.\d+)_aarch64\.deb", text):
            found_tag = deb_match.group(1)
            if found_tag != tag:
                fail(f"{rel_path}: Package deb name version mismatch: found '{deb_match.group(0)}', expected '{asset_name}'")

        # Check patch paths across all guides
        for patch_match in re.finditer(r"patches/(\d+\.\d+\.\d+)/", text):
            found_patch_ver = patch_match.group(1)
            if found_patch_ver != tag:
                fail(f"{rel_path}: Patch path version mismatch: found '{patch_match.group(0)}', expected 'patches/{tag}/'")


def check_installer_scripts(cfg: dict[str, str], root_path: Path | None = None) -> None:
    base_root = root_path or ROOT
    tag = cfg["tag"]
    release_tag = cfg["release_tag"]

    scripts = [
        "install_flutter_complete.sh",
        "scripts/install/install.sh",
        "scripts/install/install_termux_flutter.sh",
        "scripts/test/gh_e2e_test.sh",
    ]

    for rel_path in scripts:
        path = base_root / rel_path
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


def check_post_install_script(cfg: dict[str, str], root_path: Path | None = None) -> None:
    base_root = root_path or ROOT
    path = base_root / "scripts" / "install" / "post_install.sh"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    tag = cfg.get("tag")
    dart_ver = cfg.get("dart_version")
    fw_rev = cfg.get("framework_revision")
    fw_date = cfg.get("framework_commit_date")
    dev_ver = cfg.get("devtools_version")

    if tag and f'CANONICAL_FLUTTER_VER="{tag}"' not in text:
        fail(f"scripts/install/post_install.sh: CANONICAL_FLUTTER_VER mismatch, expected '{tag}'")
    if dart_ver and f'CANONICAL_DART_VER="{dart_ver}"' not in text:
        fail(f"scripts/install/post_install.sh: CANONICAL_DART_VER mismatch, expected '{dart_ver}'")
    if fw_rev and f'CANONICAL_FRAMEWORK_REV="{fw_rev}"' not in text:
        fail(f"scripts/install/post_install.sh: CANONICAL_FRAMEWORK_REV mismatch, expected '{fw_rev}'")
    if fw_date and f'CANONICAL_FRAMEWORK_DATE="{fw_date}"' not in text:
        fail(f"scripts/install/post_install.sh: CANONICAL_FRAMEWORK_DATE mismatch, expected '{fw_date}'")
    if dev_ver and f'CANONICAL_DEVTOOLS_VER="{dev_ver}"' not in text:
        fail(f"scripts/install/post_install.sh: CANONICAL_DEVTOOLS_VER mismatch, expected '{dev_ver}'")


def run_checks(root_path: Path | None = None) -> list[str]:
    ERRORS.clear()
    cfg = load_build_config(root_path)
    if not cfg:
        return ERRORS

    check_build_py(cfg, root_path)
    check_package_yaml(cfg, root_path)
    check_markdown_docs(cfg, root_path)
    check_agent_guidance_docs(cfg, root_path)
    check_guide_docs(cfg, root_path)
    check_installer_scripts(cfg, root_path)
    check_post_install_script(cfg, root_path)

    return ERRORS


def main() -> int:
    errors = run_checks()
    if errors:
        print("Version drift check FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("Version drift check PASSED (all files aligned with build.toml).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
