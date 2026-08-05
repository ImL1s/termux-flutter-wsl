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
    (android_sdk / "platforms" / "android-36").mkdir(parents=True, exist_ok=True)
    (android_sdk / "platforms" / "android-36" / "android.jar").touch()
    (android_sdk / "build-tools").mkdir(parents=True, exist_ok=True)
    (android_sdk / "cmdline-tools" / "latest").mkdir(parents=True, exist_ok=True)
    (prefix / "bin").mkdir(parents=True, exist_ok=True)
    (prefix / "share" / "flutter").mkdir(parents=True, exist_ok=True)
    (prefix / "tmp").mkdir(parents=True, exist_ok=True)

    # Dummy snapshot and dart binary so downloads and pub get are skipped
    (flutter_root / "bin" / "cache" / "dart-sdk" / "bin" / "snapshots" / "dds_aot.dart.snapshot").write_text("snapshot\n", newline="\n")
    mock_dart = flutter_root / "bin" / "cache" / "dart-sdk" / "bin" / "dart"
    mock_dart.write_text("#!/bin/sh\nexit 0\n", newline="\n")
    mock_dart.chmod(0o755)

    pkg_cfg = flutter_root / "packages" / "flutter_tools" / ".dart_tool" / "package_config.json"
    pkg_cfg.parent.mkdir(parents=True, exist_ok=True)
    pkg_cfg.write_text("{}\n", newline="\n")

    (flutter_root / "bin" / "internal" / "engine.version").write_text("dummy_version\n", newline="\n")
    (flutter_root / "version").write_text("3.44.0\n", newline="\n")

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
        path.write_text(content, newline="\n")

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


def test_mode_b_regex_slashes_empirical():
    """Verify that regex 'Android[/\\\\]Sdk' matches both POSIX / and Windows \\ slashes, case-insensitively."""
    pattern = r"Android[/\\]Sdk"
    regex = re.compile(pattern, re.IGNORECASE)

    valid_paths = [
        "/data/Android/Sdk/build-tools/35.0.0/aapt2",
        r"C:\Users\admin\AppData\Local\Android\Sdk\build-tools\35.0.0\aapt2",
        r"C:\android\sdk\aapt2",
        "/usr/local/ANDROID/SDK/aapt2",
        r"D:\some_dir\Android\Sdk\aapt2",
    ]

    invalid_paths = [
        "/data/data/com.termux/files/usr/bin/aapt2",
        "/opt/android-sdk/build-tools/35.0.0/aapt2",
        "/tmp/custom_sdk/aapt2",
    ]

    for p in valid_paths:
        assert regex.search(p), f"Regex failed to match valid path: {p}"

    for p in invalid_paths:
        assert not regex.search(p), f"Regex incorrectly matched invalid path: {p}"


def test_no_cmake_force_write_in_post_install():
    """Empirically check that CMAKE_C_COMPILER_WORKS force-writes are removed."""
    content = POST_INSTALL.read_text(encoding="utf-8")
    assert "CMAKE_C_COMPILER_WORKS" not in content
    assert "CMAKE_CXX_COMPILER_WORKS" not in content


def test_split_select_stub_exits_nonzero(tmp_path):
    """Empirically test that split-select stub created by post_install.sh exits with non-zero status."""
    bt_dir = tmp_path / "35.0.0"
    bt_dir.mkdir(parents=True)
    split_select = bt_dir / "split-select"
    split_select.write_text("#!/bin/sh\necho \"split-select is not available on Termux ARM64\"\nexit 1\n", newline="\n")
    split_select.chmod(0o755)

    ss_path = to_bash_path(split_select)
    res = subprocess.run(["bash", "-c", f"bash '{ss_path}'"], capture_output=True, text=True)
    assert res.returncode != 0, f"Expected non-zero exit code from split-select, got {res.returncode}"


@pytest.mark.skipif(
    not Path('/data/data/com.termux/files/usr/bin/aapt2').exists() and os.environ.get('CI') == 'true',
    reason='Mode B validation requires Termux aapt2 binary, not available on CI runners'
)
def test_stress_broken_aapt2_symlink_handling(tmp_path):
    """Empirically test post_install.sh when $BT_DIR/35.0.0/aapt2 is a broken symlink."""
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)

    bt_dir = android_sdk / "build-tools" / "35.0.0"
    bt_dir.mkdir(parents=True, exist_ok=True)
    aapt2_link = bt_dir / "aapt2"

    # Create a broken symlink containing 'Android/Sdk' in target string
    target_nonexistent = tmp_path / "Android" / "Sdk" / "nonexistent_aapt2_bin"
    target_bash = to_bash_path(target_nonexistent)
    link_bash = to_bash_path(aapt2_link)

    subprocess.run(["bash", "-c", f"ln -sf '{target_bash}' '{link_bash}'"], check=True)

    # Run post_install --apply
    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])

    # Must complete successfully (exit code 0)
    assert res.returncode == 0, f"post_install failed with broken symlink: {res.stderr}"

    # Output should report Mode B validation failed and reverted to Mode A
    assert "Mode B toolchain validation failed" in res.stdout
    assert "Reverting Mode B activation to Mode A" in res.stdout

    # Verify aapt2 symlink was reset to Mode A default (/data/data/com.termux/files/usr/bin/aapt2)
    aapt2_post = bt_dir / "aapt2"
    aapt2_post_bash = to_bash_path(aapt2_post)
    link_target = subprocess.run(["bash", "-c", f"readlink '{aapt2_post_bash}'"], capture_output=True, text=True).stdout.strip()
    assert link_target == "/data/data/com.termux/files/usr/bin/aapt2", f"Expected Mode A fallback symlink target, got '{link_target}'"


def test_stress_dual_preimage_fresh_install_prepatched(tmp_path):
    """Test first-time install when files are ALREADY in postimage state (no state file)."""
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)

    # Convert all files to postimage state manually before running post_install.sh
    (flutter_root / "packages" / "flutter_tools" / "gradle" / "src" / "main" / "kotlin" / "FlutterExtension.kt").write_text("val compileSdkVersion: Int = 34\n")
    (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "commands" / "build_apk.dart").write_text(
        "static const _kDefaultJitArchs = <String>['android-arm64']\nstatic const _kDefaultAotArchs = <String>['android-arm64']\n"
    )
    (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "commands" / "build_aar.dart").write_text("defaultsTo: <String>['android-arm64']\n")
    (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "commands" / "build_appbundle.dart").write_text("defaultsTo: <String>['android-arm64']\n")
    (flutter_root / "packages" / "flutter_tools" / "gradle" / "src" / "main" / "kotlin" / "FlutterPluginUtils.kt").write_text(
        "fun forceNdkDownload() {\n        return // Termux: NDK already installed, skip CMake trick\n val forcingNotRequired: Boolean = true\n }\n"
    )
    (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "flutter_cache.dart").write_text(
        "final List<String>? binaryDirs = artifacts[_platform.isAndroid ? 'linux' : _platform.operatingSystem]; // Termux: map Android host to Linux artifacts\n"
    )
    (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "artifacts.dart").write_text("if (platform.isLinux || platform.isAndroid) {\n")
    (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "build_info.dart").write_text("if (globals.platform.isLinux || globals.platform.isAndroid) {\n")
    (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "web" / "chrome.dart").write_text("if (platform.isLinux || platform.isAndroid) {\n")
    (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "commands" / "build_linux.dart").write_text("if (false /* Termux: allow linux build */)\n!featureFlags.isLinuxEnabled /* Termux: visible */\n")
    (flutter_root / "packages" / "flutter_tools" / "lib" / "src" / "build_system" / "targets" / "icon_tree_shaker.dart").write_text("kIconTreeShakerFlag\nfalse /* Termux: const_finder unavailable */\n")
    (flutter_root / "bin" / "flutter").write_text("#!/data/data/com.termux/files/usr/bin/bash\necho flutter\n")

    # Run --check on fresh pre-patched env (no patch_state.json exists)
    res_check = run_post_install(flutter_root, android_sdk, prefix, ["--check"])
    assert res_check.returncode == 0, f"--check failed on pre-patched env: {res_check.stdout}"
    assert "already correct" in res_check.stdout
    assert "unknown upstream content" not in res_check.stdout

    # Run --apply on fresh pre-patched env
    res_apply = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res_apply.returncode == 0, f"--apply failed on pre-patched env: {res_apply.stdout}"
    assert "already correct" in res_apply.stdout


def test_stress_rollback_byte_identity_all_files(tmp_path):
    """Verify byte-for-byte identity of all targets after --apply and --rollback."""
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)

    # Capture byte hashes of all original files
    orig_hashes = {}
    for path in files.keys():
        orig_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()

    # Apply patches
    res_apply = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res_apply.returncode == 0

    # Ensure files modified
    modified_count = 0
    for path, h in orig_hashes.items():
        current_h = hashlib.sha256(path.read_bytes()).hexdigest()
        if current_h != h:
            modified_count += 1
    assert modified_count > 0

    # Rollback patches
    res_rb = run_post_install(flutter_root, android_sdk, prefix, ["--rollback"])
    assert res_rb.returncode == 0

    # Verify byte-for-byte SHA256 equality
    for path, expected_hash in orig_hashes.items():
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual_hash == expected_hash, f"Mismatch in restored file {path}: expected {expected_hash}, got {actual_hash}"
