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
from urllib.parse import unquote

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs requirements.txt first.
    yaml = None

ROOT = Path(__file__).resolve().parents[2]
ERRORS: list[str] = []

ROOT_MARKDOWN_ALLOWLIST = {
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "ORIGINAL_REQUEST.md",
    "PROJECT.md",
    "README.md",
    "README_EN.md",
}

REQUIRED_DOCS = [
    "docs/README.md",
    "docs/CI_CD.md",
    "docs/guides/BUILD_GUIDE.md",
    "docs/guides/BUILD_PROCESS.md",
    "docs/guides/INSTALL_GUIDE.md",
    "docs/guides/UPGRADE_GUIDE.md",
    "docs/releases/CHANGELOG.md",
    "docs/releases/RELEASE_NOTES.md",
]


def fail(message: str) -> None:
    ERRORS.append(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require_file(path: str) -> None:
    if not (ROOT / path).is_file():
        fail(f"missing required file: {path}")


def check_markdown_fences() -> None:
    for path in sorted(ROOT.glob("**/*.md")):
        if any(part in {".git", "flutter", "sysroot", "reference_termux_flutter", ".omx", ".omc", ".agents", "scratch"} for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if text.count("```") % 2:
            fail(f"unbalanced markdown code fence: {path.relative_to(ROOT)}")


def check_markdown_no_control_characters() -> None:
    for path in sorted(ROOT.glob("**/*.md")):
        if any(part in {".git", "flutter", "sysroot", "reference_termux_flutter", ".omx", ".omc", ".agents", "scratch"} for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for ch in line:
                if ord(ch) < 32 and ch not in "\t":
                    fail(f"{path.relative_to(ROOT)}:L{line_no}: forbidden control character U+{ord(ch):04X}")


def check_markdown_links() -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)\s]+\.md(?:#[^)]+)?)\)")
    for path in sorted(ROOT.glob("**/*.md")):
        if any(part in {".git", "flutter", "sysroot", "reference_termux_flutter", ".omx", ".omc", ".agents", "scratch"} for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in link_pattern.finditer(text):
            target = unquote(match.group(1).split("#", 1)[0])
            if "://" in target or target.startswith("#"):
                continue
            resolved = ((ROOT if target.startswith("/") else path.parent) / target.lstrip("/")).resolve()
            if not resolved.is_file():
                try:
                    rel_path = path.relative_to(ROOT)
                except ValueError:
                    rel_path = path.name
                fail(f"{rel_path}: broken markdown link: {match.group(1)}")


def check_doc_layout() -> None:
    for rel in REQUIRED_DOCS:
        require_file(rel)

    for path in sorted(ROOT.glob("*.md")):
        if path.name not in ROOT_MARKDOWN_ALLOWLIST:
            fail(f"root markdown should live under docs/: {path.name}")


def check_no_stale_release_commands() -> None:
    stale_patterns = {
        "flutter_3.41.5_aarch64.deb": "old 3.41.5 deb download/install command",
        "releases/download/3.41.5": "old release URL without v3.44.0",
        "Clone Flutter 3.41.5": "old AGENTS clone comment",
    }
    checked = [
        "README.md",
        "README_EN.md",
        "docs/guides/BUILD_GUIDE.md",
        "docs/guides/INSTALL_GUIDE.md",
        "docs/guides/UPGRADE_GUIDE.md",
        "docs/releases/CHANGELOG.md",
        "docs/releases/RELEASE_NOTES.md",
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

    ci_path = ROOT / ".github" / "workflows" / "ci.yml"
    if ci_path.is_file():
        ci_text = ci_path.read_text(encoding="utf-8")
        if "pytest" not in ci_text:
            fail("ci.yml missing pytest execution step")
        if "shellcheck" not in ci_text:
            fail("ci.yml missing shellcheck execution step")
        elif "--severity=" not in ci_text:
            fail("ci.yml missing shellcheck --severity flag")
        if "actionlint" not in ci_text:
            fail("ci.yml missing actionlint execution step")
        elif "curl -sSfL" not in ci_text:
            fail("ci.yml actionlint step must use curl -sSfL")


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
    # Read expected version from build.toml
    toml_text = read("build.toml")
    import re as _re
    m = _re.search(r"tag\s*=\s*'([^']+)'", toml_text)
    expected_ver = m.group(1) if m else "3.44.9"
    if f'FLUTTER_VERSION="{expected_ver}"' not in text:
        fail(f"install_flutter_complete.sh default Flutter version is not {expected_ver}")
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
        "scripts/ci/check_version_drift.py",
        "scripts/device/run_termux_smoke.ps1",
        "scripts/device/termux_smoke.sh",
        "scripts/test/gh_e2e_test.sh",
    ]:
        require_file(path)

    if (ROOT / "gh_e2e_test.sh").exists():
        fail("gh_e2e_test.sh should live under scripts/test/, not repository root")


def check_version_drift_contract() -> None:
    try:
        import check_version_drift
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        import check_version_drift
    if check_version_drift.main() != 0:
        fail("check_version_drift.py detected version drift errors")


def check_sysroot_lock_contract() -> None:
    lock_file = ROOT / "sysroot.lock.json"
    if not lock_file.is_file():
        fail("missing required file: sysroot.lock.json")
        return
    try:
        import json
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        arch_entry = data.get("aarch64") or data.get("arm64")
        if not isinstance(arch_entry, dict):
            fail("sysroot.lock.json missing aarch64/arm64 entry")
            return
        for req_key in ("arch", "created_at", "tree_hash", "packages"):
            if req_key not in arch_entry:
                fail(f"sysroot.lock.json missing required field: {req_key}")
        pkgs = arch_entry.get("packages", {})
        if not isinstance(pkgs, dict) or not pkgs:
            fail("sysroot.lock.json packages mapping is empty or invalid")
            return
        for pkg_name, pkg_info in pkgs.items():
            if not isinstance(pkg_info, dict):
                fail(f"sysroot.lock.json package '{pkg_name}' is invalid")
                continue
            for field in ("name", "version", "url", "sha256", "size", "archive_path", "repo", "dist"):
                if field not in pkg_info:
                    fail(f"sysroot.lock.json package '{pkg_name}' missing required field '{field}'")
    except Exception as e:
        fail(f"sysroot.lock.json validation failed: {e}")


def check_script_headers() -> None:
    shell_scripts = sorted(list(ROOT.glob("*.sh")) + list((ROOT / "scripts").glob("**/*.sh")))
    for script in shell_scripts:
        rel = script.relative_to(ROOT)
        text = script.read_text(encoding="utf-8", errors="ignore")
        if not text.startswith("#!"):
            fail(f"{rel}: shell script missing shebang header")
        if "\r\n" in text:
            fail(f"{rel}: shell script contains CRLF line endings")

    py_entrypoints = [
        "build.py",
        "package.py",
        "sysroot.py",
        "scripts/ci/check_repo.py",
        "scripts/ci/check_version_drift.py",
        "scripts/ci/verify_release_asset.py",
    ]
    for py_rel in py_entrypoints:
        py_path = ROOT / py_rel
        if py_path.is_file():
            text = py_path.read_text(encoding="utf-8", errors="ignore")
            if not text.startswith("#!"):
                fail(f"{py_rel}: Python script missing shebang header")
            if "\r\n" in text:
                fail(f"{py_rel}: Python script contains CRLF line endings")


def check_test_modules_and_ci_steps() -> None:
    required_test_modules = [
        "tests/test_installer.py",
        "tests/test_flutter_project_config.py",
        "tests/test_post_install.py",
        "tests/test_sysroot.py",
        "tests/test_release.py",
        "tests/test_build_pipeline.py",
        "tests/test_package.py",
        "tests/test_ci.py",
        "tests/test_r4_release_governance.py",
    ]
    for test_mod in required_test_modules:
        require_file(test_mod)

    ci_yml = ROOT / ".github" / "workflows" / "ci.yml"
    if not ci_yml.is_file():
        fail("missing required file: .github/workflows/ci.yml")
        return

    ci_text = ci_yml.read_text(encoding="utf-8")
    for req_tool in ("pytest", "shellcheck", "actionlint"):
        if req_tool not in ci_text:
            fail(f".github/workflows/ci.yml missing job step for {req_tool}")


def check_repository_hygiene() -> None:
    """Ensure no scratch artifacts, test caches, backups, or receipts leak into the repository."""
    import subprocess
    gitignore = ROOT / ".gitignore"
    if not gitignore.is_file():
        fail("Missing .gitignore file")
        return
    gi_text = gitignore.read_text(encoding="utf-8")
    for required_pattern in ("scratch/", ".pytest_cache/", "*.bak", "*.receipt.json"):
        if required_pattern not in gi_text:
            fail(f".gitignore missing essential hygiene pattern: {required_pattern}")

    # Check git tracked files for scratch or hygiene leaks
    try:
        res = subprocess.run(
            ["git", "ls-files", "scratch/"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            tracked_scratch = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            if tracked_scratch:
                fail(f"Tracked files found under scratch/ directory: {tracked_scratch[:5]}")
    except Exception:
        pass


def main() -> int:
    check_ci_layout()
    check_doc_layout()
    check_markdown_fences()
    check_markdown_no_control_characters()
    check_markdown_links()
    check_no_stale_release_commands()
    check_yaml_files()
    check_post_install_contract()
    check_installer_contract()
    check_version_drift_contract()
    check_sysroot_lock_contract()
    check_script_headers()
    check_test_modules_and_ci_steps()
    check_repository_hygiene()

    if ERRORS:
        print("Repository sanity check failed:", file=sys.stderr)
        for error in ERRORS:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Repository sanity check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
