import hashlib
import os
import re
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
POST_INSTALL = REPO_ROOT / "scripts" / "install" / "post_install.sh"


def to_bash_path(path):
    path = Path(path).resolve()
    try:
        rel = path.relative_to(REPO_ROOT)
        return rel.as_posix()
    except ValueError:
        p = path.as_posix()
        if len(p) > 1 and p[1] == ":":
            drive = p[0].lower()
            return f"/mnt/{drive}{p[2:]}"
        return p


def create_mock_env(tmp_path):
    flutter_root = tmp_path / "flutter"
    android_sdk = tmp_path / "android-sdk"
    prefix = tmp_path / "usr"

    # Create directories
    (flutter_root / "packages" / "flutter_tools" / "gradle" / "src" / "main" / "kotlin").mkdir(parents=True, exist_ok=True)
    (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "commands").mkdir(parents=True, exist_ok=True)
    (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "web").mkdir(parents=True, exist_ok=True)
    (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "build_system" / "targets").mkdir(parents=True, exist_ok=True)
    (flutter_root / "packages" / "flutter_tools" / "gradle" / "src" / "main" / "scripts").mkdir(parents=True, exist_ok=True)
    (flutter_root / "packages" / "flutter_tools" / "bin").mkdir(parents=True, exist_ok=True)
    (flutter_root / "bin" / "internal").mkdir(parents=True, exist_ok=True)
    (flutter_root / "bin" / "cache" / "dart-sdk" / "bin" / "snapshots").mkdir(parents=True, exist_ok=True)
    (android_sdk / "platforms" / "android-34").mkdir(parents=True, exist_ok=True)
    (android_sdk / "platforms" / "android-34" / "android.jar").touch()
    (android_sdk / "platforms" / "android-35").mkdir(parents=True, exist_ok=True)
    (android_sdk / "platforms" / "android-35" / "android.jar").touch()
    (android_sdk / "platforms" / "android-36").mkdir(parents=True, exist_ok=True)
    (android_sdk / "platforms" / "android-36" / "android.jar").touch()
    (android_sdk / "build-tools").mkdir(parents=True, exist_ok=True)
    (android_sdk / "cmdline-tools" / "latest").mkdir(parents=True, exist_ok=True)
    (prefix / "bin").mkdir(parents=True, exist_ok=True)
    (prefix / "share" / "flutter").mkdir(parents=True, exist_ok=True)
    (prefix / "tmp").mkdir(parents=True, exist_ok=True)

    # Dummy snapshot and dart binary so downloads and pub get are skipped
    (flutter_root / "bin" / "cache" / "dart-sdk" / "bin" / "snapshots" / "dds_aot.dart.snapshot").write_text("snapshot", newline="\n")
    mock_dart = flutter_root / "bin" / "cache" / "dart-sdk" / "bin" / "dart"
    mock_dart.write_text("#!/bin/sh\nexit 0\n", newline="\n")
    mock_dart.chmod(0o755)

    pkg_cfg = flutter_root / "packages" / "flutter_tools" / ".dart_tool" / "package_config.json"
    pkg_cfg.parent.mkdir(parents=True, exist_ok=True)
    pkg_cfg.write_text("{}", newline="\n")

    (flutter_root / "bin" / "internal" / "engine.version").write_text("dummy_version", newline="\n")
    (flutter_root / "version").write_text("3.44.0", newline="\n")

    # Target files with upstream preimages
    files = {
        flutter_root / "packages" / "flutter_tools" / "gradle" / "src" / "main" / "kotlin" / "FlutterExtension.kt":
            "val compileSdkVersion: Int = 36\n",
        flutter_root / "packages" / "flutter_tools" / "gradle" / "src" / "main" / "kotlin" / "FlutterPluginConstants.kt":
            "package com.flutter.gradle\nobject FlutterPluginConstants {\n private const val PLATFORM_ARM32 = \"android-arm\"\n}\n",
        flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "commands" / "build_apk.dart":
            "static const _kDefaultJitArchs = <String>['android-arm', 'android-arm64', 'android-x64']\nstatic const _kDefaultAotArchs = <String>['android-arm', 'android-arm64', 'android-x64']\n",
        flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "commands" / "build_aar.dart":
            "defaultsTo: <String>['android-arm', 'android-arm64', 'android-x64']\n",
        flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "commands" / "build_appbundle.dart":
            "defaultsTo: <String>['android-arm', 'android-arm64', 'android-x64']\n",
        flutter_root / "packages" / "flutter_tools" / "gradle" / "src" / "main" / "kotlin" / "FlutterPluginUtils.kt":
            "fun forceNdkDownload() {\n val forcingNotRequired: Boolean = true\n }\n",
        flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "flutter_cache.dart":
            "final List<String>? binaryDirs = artifacts[_platform.operatingSystem];\n",
        flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "artifacts.dart":
            "if (platform.isLinux) {\n",
        flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "build_info.dart":
            "if (globals.platform.isLinux) {\n",
        flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "web" / "chrome.dart":
            "if (platform.isLinux) {\n",
        flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "commands" / "build_linux.dart":
            "if (!globals.platform.isLinux)\n!featureFlags.isLinuxEnabled || !globals.platform.isLinux\n",
        flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "build_system" / "targets" / "icon_tree_shaker.dart":
            "kIconTreeShakerFlag\n_environment.defines[kIconTreeShakerFlag] == 'true'\n",
        flutter_root / "packages" / "flutter_tools" / "gradle" / "src" / "main" / "scripts" / "CMakeLists.txt":
            "cmake_minimum_required(VERSION 3.6)\nproject(FlutterNDKTrick C CXX)\n",
        flutter_root / "bin" / "flutter": "#!/usr/bin/env bash\necho flutter\n",
        flutter_root / "bin" / "dart": "#!/usr/bin/env bash\necho dart\n",
        flutter_root / "bin" / "internal" / "shared.sh": "#!/usr/bin/env bash\n",
        flutter_root / "bin" / "internal" / "update_dart_sdk.sh": "#!/usr/bin/env bash\n",
        flutter_root / "bin" / "internal" / "content_aware_hash.sh": "#!/usr/bin/env bash\n",
        flutter_root / "bin" / "internal" / "last_engine_commit.sh": "#!/usr/bin/env bash\n",
        flutter_root / "bin" / "internal" / "update_engine_version.sh": "#!/usr/bin/env bash\n",
        flutter_root / "packages" / "flutter_tools" / "bin" / "tool_backend.sh": "#!/usr/bin/env bash\n",
    }

    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.replace("\r\n", "\n"), newline="\n")

    return flutter_root, android_sdk, prefix, files


def run_post_install(flutter_root, android_sdk, prefix, args=None):
    if args is None:
        args = ["--apply"]
    post_install_path = to_bash_path(POST_INSTALL)
    flut_path = to_bash_path(flutter_root)
    sdk_path = to_bash_path(android_sdk)
    pref_path = to_bash_path(prefix)

    cmd = (
        f"export FLUTTER_ROOT='{flut_path}' && "
        f"export ANDROID_SDK='{sdk_path}' && "
        f"export PREFIX='{pref_path}' && "
        f"export DART_SDK='{flut_path}/bin/cache/dart-sdk' && "
        f"bash '{post_install_path}' {' '.join(args)}"
    )
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    return res


def test_post_install_syntax():
    res = subprocess.run(["bash", "-n", to_bash_path(POST_INSTALL)], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"bash -n failed: {res.stderr}"


def test_no_cmake_compiler_works_force_written():
    content = POST_INSTALL.read_text(encoding="utf-8")
    assert "set(CMAKE_C_COMPILER_WORKS TRUE)" not in content
    assert "set(CMAKE_CXX_COMPILER_WORKS TRUE)" not in content
    assert "CMAKE_C_COMPILER_WORKS" not in content
    assert "CMAKE_CXX_COMPILER_WORKS" not in content


def test_dual_preimage_apply_from_upstream_preimage(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode == 0, f"post_install failed: stdout={res.stdout}, stderr={res.stderr}"

    # Check transformed postimages
    ext_kt = (flutter_root / "packages" / "flutter_tools" / "gradle" / "src" / "main" / "kotlin" / "FlutterExtension.kt").read_text()
    assert "val compileSdkVersion: Int = 34" in ext_kt

    apk_dart = (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "commands" / "build_apk.dart").read_text()
    assert "static const _kDefaultJitArchs = <String>['android-arm64']" in apk_dart
    assert "['android-arm', 'android-arm64', 'android-x64']" not in apk_dart


def test_dual_preimage_check_on_postimage(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    # Apply first to convert to postimage
    res1 = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res1.returncode == 0

    # Now run --check on postimage
    res2 = run_post_install(flutter_root, android_sdk, prefix, ["--check"])
    assert res2.returncode == 0, f"--check failed: stdout={res2.stdout}, stderr={res2.stderr}"
    assert "already correct" in res2.stdout or "already applied" in res2.stdout
    assert "pending" not in res2.stdout


def test_dual_preimage_apply_idempotent(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    # Apply once
    res1 = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res1.returncode == 0

    # Snapshot target files after 1st apply
    target_files = list(flutter_root.glob("**/*"))
    hashes_after_first = {}
    for p in target_files:
        if p.is_file():
            hashes_after_first[p] = hashlib.sha256(p.read_bytes()).hexdigest()

    # Apply second time
    res2 = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res2.returncode == 0, f"Second --apply failed: stdout={res2.stdout}, stderr={res2.stderr}"

    # Verify 0 diff
    for p, h in hashes_after_first.items():
        if p.exists():
            assert hashlib.sha256(p.read_bytes()).hexdigest() == h, f"File {p} changed on second --apply"


def test_dual_preimage_rollback(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)

    # Store original contents
    orig_contents = {p: p.read_bytes() for p in files.keys()}

    # Apply patches
    res1 = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res1.returncode == 0

    # Rollback patches
    res2 = run_post_install(flutter_root, android_sdk, prefix, ["--rollback"])
    assert res2.returncode == 0, f"--rollback failed: stdout={res2.stdout}, stderr={res2.stderr}"

    # Verify byte-identical restoration
    for path, expected_bytes in orig_contents.items():
        assert path.read_bytes() == expected_bytes, f"Rollback failed to restore byte-identical file {path}"


def test_dual_preimage_unknown_content_fails(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)

    # Overwrite a target file with unknown content
    bad_file = flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "commands" / "build_apk.dart"
    bad_file.write_text("CORRUPTED_UNKNOWN_CONTENT_XYZ")

    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode != 0
    assert "unknown upstream content" in res.stdout or "unknown upstream content" in res.stderr


def test_split_select_stub_exits_one(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode == 0

    bt_dir = android_sdk / "build-tools" / "35.0.0"
    split_select = bt_dir / "split-select"
    assert split_select.exists()

    ss_path = to_bash_path(split_select)
    sub_res = subprocess.run(["bash", "-c", f"bash '{ss_path}'"], capture_output=True, text=True)
    assert sub_res.returncode == 1, f"split-select stub should exit 1, got {sub_res.returncode}"


def make_symlink(target, link):
    try:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
    except Exception:
        target_bash = to_bash_path(target)
        link_bash = to_bash_path(link)
        subprocess.run(["bash", "-c", f"ln -sf '{target_bash}' '{link_bash}'"], check=True)


def test_mode_b_validation_success(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    bt_dir = android_sdk / "build-tools" / "35.0.0"
    bt_dir.mkdir(parents=True, exist_ok=True)

    # Create mock aapt2 symlink pointing to an executable mock script
    mock_aapt2 = tmp_path / "mock_aapt2.sh"
    mock_aapt2_content = (
        "#!/bin/sh\n"
        "if [ \"$1\" = \"compile\" ]; then\n"
        "  out_dir=\"${4%/}\"\n"
        "  touch \"${out_dir}/values_strings.arsc.flat\"\n"
        "  exit 0\n"
        "elif [ \"$1\" = \"link\" ]; then\n"
        "  touch \"$3\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    ).replace("\r\n", "\n")
    mock_aapt2.write_text(mock_aapt2_content, newline="\n")
    mock_aapt2.chmod(0o755)

    aapt2_link = bt_dir / "aapt2"
    # Create symlink with "Android/Sdk" in target path to trigger Mode B check
    fake_sdk_target_path = tmp_path / "Android" / "Sdk" / "aapt2"
    fake_sdk_target_path.parent.mkdir(parents=True, exist_ok=True)
    fake_sdk_target_path.write_text(mock_aapt2.read_text(encoding="utf-8").replace("\r\n", "\n"), newline="\n")
    fake_sdk_target_path.chmod(0o755)

    make_symlink(fake_sdk_target_path, aapt2_link)

    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode == 0
    assert "Mode B toolchain validation passed (aapt2 compile/link works)" in res.stdout


def test_mode_b_validation_failure_reverts_to_mode_a(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    bt_dir = android_sdk / "build-tools" / "35.0.0"
    bt_dir.mkdir(parents=True, exist_ok=True)

    # Create broken mock aapt2 that fails on compile
    fake_sdk_target_path = tmp_path / "Android" / "Sdk" / "aapt2"
    fake_sdk_target_path.parent.mkdir(parents=True, exist_ok=True)
    fake_sdk_target_path.write_text("#!/bin/sh\nexit 1\n".replace("\r\n", "\n"), newline="\n")
    fake_sdk_target_path.chmod(0o755)

    aapt2_link = bt_dir / "aapt2"
    make_symlink(fake_sdk_target_path, aapt2_link)

    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode == 0
    assert "Mode B toolchain validation failed" in res.stdout or "Reverting Mode B activation to Mode A" in res.stdout
