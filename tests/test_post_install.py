import hashlib
import os
import re
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
POST_INSTALL = REPO_ROOT / "scripts" / "install" / "post_install.sh"


from conftest import to_bash_path


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
    (flutter_root / "packages" / "flutter_tools" / "bin" / "flutter_tools.dart").write_text("void main() {}\n", newline="\n")
    (flutter_root / "bin" / "cache" / "dart-sdk" / "bin" / "snapshots" / "dds_aot.dart.snapshot").write_text("snapshot", newline="\n")
    mock_dart = flutter_root / "bin" / "cache" / "dart-sdk" / "bin" / "dart"
    mock_dart_script = (
        "#!/bin/sh\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in\n"
        "    --snapshot=*) out=\"${arg#*=}\"; touch \"$out\"; echo \"MOCK_SNAPSHOT_BYTES\" > \"$out\" ;;\n"
        "  esac\n"
        "done\n"
        "exit 0\n"
    ).replace("\r\n", "\n")
    mock_dart.write_text(mock_dart_script, newline="\n")
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
        flutter_root / "packages" / "flutter_tools" / "bin" / "flutter_tools.dart": "void main() {}\n",
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


def compute_dir_tree_hash(root_dir):
    """Compute deterministic SHA-256 hash of all files and structure in a directory."""
    hasher = hashlib.sha256()
    for root, dirs, files in os.walk(root_dir):
        dirs.sort()
        for f in sorted(files):
            full_path = Path(root) / f
            rel_path = full_path.relative_to(root_dir).as_posix()
            hasher.update(rel_path.encode('utf-8'))
            if full_path.is_file() and not full_path.is_symlink():
                hasher.update(full_path.read_bytes())
    return hasher.hexdigest()


def test_post_install_read_only_tree_byte_identical(tmp_path):
    """Verify post_install --status and --check do not modify any files or sentinels in mock trees (byte-identical tree hashes)."""
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)

    # 1. flutter_tools.stamp and flutter_tools.snapshot
    cache_dir = flutter_root / "bin" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    stamp_file = cache_dir / "flutter_tools.stamp"
    snapshot_file = cache_dir / "flutter_tools.snapshot"
    stamp_file.write_text("sentinel_stamp_v1", encoding="utf-8")
    snapshot_file.write_text("sentinel_snapshot_v1", encoding="utf-8")

    # 2. patch_state.json and backups
    flutter_share = prefix / "share" / "flutter"
    flutter_share.mkdir(parents=True, exist_ok=True)
    patch_state_file = flutter_share / "patch_state.json"
    backup_dir = flutter_share / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    patch_state_file.write_text('{"mock_patch": {"status": "applied"}}', encoding="utf-8")
    (backup_dir / "sentinel_backup.orig").write_text("sentinel_backup_content", encoding="utf-8")

    # 3. NDK wrapper and Android SDK files
    ndk_bin = android_sdk / "ndk" / "27.2.12479018" / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin"
    ndk_bin.mkdir(parents=True, exist_ok=True)
    (ndk_bin / "clang").write_text("sentinel_clang_wrapper", encoding="utf-8")
    bt_dir = android_sdk / "build-tools" / "35.0.0"
    bt_dir.mkdir(parents=True, exist_ok=True)
    (bt_dir / "aapt2").write_text("sentinel_aapt2_binary", encoding="utf-8")

    hash_flut_before = compute_dir_tree_hash(flutter_root)
    hash_sdk_before = compute_dir_tree_hash(android_sdk)
    hash_pref_before = compute_dir_tree_hash(prefix)

    res_status = run_post_install(flutter_root, android_sdk, prefix, ["--status"])
    assert res_status.returncode == 0, f"--status failed: {res_status.stderr}"

    assert compute_dir_tree_hash(flutter_root) == hash_flut_before, "flutter_root tree mutated during --status"
    assert compute_dir_tree_hash(android_sdk) == hash_sdk_before, "android_sdk tree mutated during --status"
    assert compute_dir_tree_hash(prefix) == hash_pref_before, "prefix tree mutated during --status"
    assert stamp_file.read_text(encoding="utf-8") == "sentinel_stamp_v1"
    assert snapshot_file.read_text(encoding="utf-8") == "sentinel_snapshot_v1"

    res_check = run_post_install(flutter_root, android_sdk, prefix, ["--check"])
    assert res_check.returncode == 0, f"--check failed: {res_check.stderr}"

    assert compute_dir_tree_hash(flutter_root) == hash_flut_before, "flutter_root tree mutated during --check"
    assert compute_dir_tree_hash(android_sdk) == hash_sdk_before, "android_sdk tree mutated during --check"
    assert compute_dir_tree_hash(prefix) == hash_pref_before, "prefix tree mutated during --check"
    assert stamp_file.read_text(encoding="utf-8") == "sentinel_stamp_v1"
    assert snapshot_file.read_text(encoding="utf-8") == "sentinel_snapshot_v1"


def test_post_install_fresh_shell_unset_dart_sdk(tmp_path):
    """Regression test: verify post_install.sh succeeds when DART_SDK is unset in environment."""
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    post_install_path = to_bash_path(POST_INSTALL)
    flut_path = to_bash_path(flutter_root)
    sdk_path = to_bash_path(android_sdk)
    pref_path = to_bash_path(prefix)

    cmd = (
        f"unset DART_SDK && "
        f"export FLUTTER_ROOT='{flut_path}' && "
        f"export ANDROID_SDK='{sdk_path}' && "
        f"export PREFIX='{pref_path}' && "
        f"bash '{post_install_path}' --apply"
    )
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"post_install failed in fresh shell with unset DART_SDK:\nstdout: {res.stdout}\nstderr: {res.stderr}"
    assert "Dart compiler missing at /bin/dart" not in res.stderr
    assert (flutter_root / "bin" / "cache" / "flutter_tools.stamp").exists()


def test_post_install_ensures_profile_env_flutter_sh(tmp_path):
    """Verify post_install.sh creates $PREFIX/etc/profile.d/flutter.sh if missing."""
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    post_install_path = to_bash_path(POST_INSTALL)
    flut_path = to_bash_path(flutter_root)
    sdk_path = to_bash_path(android_sdk)
    pref_path = to_bash_path(prefix)

    profile_sh = prefix / "etc" / "profile.d" / "flutter.sh"
    assert not profile_sh.exists()

    cmd = (
        f"export FLUTTER_ROOT='{flut_path}' && "
        f"export ANDROID_SDK='{sdk_path}' && "
        f"export PREFIX='{pref_path}' && "
        f"bash '{post_install_path}' --apply"
    )
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"post_install failed: {res.stderr}"
    assert profile_sh.exists(), "post_install.sh failed to create $PREFIX/etc/profile.d/flutter.sh"
    profile_content = profile_sh.read_text(encoding="utf-8")
    assert "export PATH=${PREFIX}/opt/flutter/bin:${PATH}" in profile_content
    assert "export ANDROID_NDK_HOME=" in profile_content


def test_post_install_preserves_existing_flutter_sh(tmp_path):
    """Verify post_install.sh does not overwrite an existing $PREFIX/etc/profile.d/flutter.sh."""
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    post_install_path = to_bash_path(POST_INSTALL)
    flut_path = to_bash_path(flutter_root)
    sdk_path = to_bash_path(android_sdk)
    pref_path = to_bash_path(prefix)

    profile_sh = prefix / "etc" / "profile.d" / "flutter.sh"
    profile_sh.parent.mkdir(parents=True, exist_ok=True)
    custom_content = "# Custom user flutter.sh profile\nexport CUSTOM_FLAG=1\n"
    profile_sh.write_text(custom_content, encoding="utf-8")

    cmd = (
        f"export FLUTTER_ROOT='{flut_path}' && "
        f"export ANDROID_SDK='{sdk_path}' && "
        f"export PREFIX='{pref_path}' && "
        f"bash '{post_install_path}' --apply"
    )
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"post_install failed: {res.stderr}"
    assert profile_sh.read_text(encoding="utf-8") == custom_content


def test_post_install_dummy_git_repo_stable_branch_and_version_json(tmp_path):
    """Verify post_install.sh initializes synthetic git repository on stable branch with canonical provenance."""
    import json
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)

    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode == 0, f"post_install failed: {res.stderr}"

    # Verify synthetic git repo branch is stable
    branch_res = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=str(flutter_root), capture_output=True, text=True)
    assert branch_res.returncode == 0
    assert branch_res.stdout.strip() == "stable"

    # Verify git tag points at HEAD
    tag_res = subprocess.run(["git", "tag", "--points-at", "HEAD"], cwd=str(flutter_root), capture_output=True, text=True)
    assert tag_res.returncode == 0
    assert "3.44.0" in tag_res.stdout.splitlines()

    # Verify total tag count is exactly 1
    all_tags = subprocess.run(["git", "tag", "-l"], cwd=str(flutter_root), capture_output=True, text=True).stdout.splitlines()
    assert len(all_tags) == 1

    # Verify termux_synthetic marker
    marker = flutter_root / ".git" / "termux_synthetic"
    assert marker.is_file()

    # Verify flutter.version.json contains authoritative canonical provenance
    version_json_file = flutter_root / "bin" / "cache" / "flutter.version.json"
    assert version_json_file.is_file(), "flutter.version.json was not created"
    data = json.loads(version_json_file.read_text(encoding="utf-8"))
    assert data["channel"] == "stable"
    assert data["frameworkVersion"] == "3.44.0"
    assert data["flutterVersion"] == "3.44.0"
    assert data["repositoryUrl"] == "https://github.com/flutter/flutter.git"
    assert data["frameworkRevision"] == "6b182d2c7585eba26d4edce0f97630effd256c33"
    assert data["frameworkCommitDate"] == "2026-08-05 17:04:07 +0000"
    assert data["dartSdkVersion"] == "3.12.2"
    assert data["devToolsVersion"] == "2.42.0"


def test_post_install_contaminated_synthetic_repo_repair(tmp_path):
    """Verify post_install.sh cleans up tag contamination, corrupted version JSON, and bad branches on synthetic repos."""
    import json
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)

    # Initialize a legacy synthetic repo with master branch, 50 contaminated upstream tags, and FETCH_HEAD
    subprocess.run(["git", "init", "-q"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "checkout", "-B", "trunk"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Init framework"], cwd=str(flutter_root), check=True)

    # Create 50 fake upstream tags
    for i in range(50):
        subprocess.run(["git", "tag", f"upstream-tag-{i}"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "tag", "3.48.0-0.2.pre"], cwd=str(flutter_root), check=True)

    # Create fake FETCH_HEAD
    (flutter_root / ".git" / "FETCH_HEAD").write_text("dummy upstream fetch record\n")

    # Create corrupted flutter.version.json
    corrupted_json = {
        "frameworkVersion": "3.48.0-0.2.pre",
        "channel": "master",
        "repositoryUrl": "https://github.com/flutter/flutter.git",
        "frameworkRevision": "corrupted_hash",
        "flutterVersion": "3.48.0-0.2.pre"
    }
    (flutter_root / "bin" / "cache" / "flutter.version.json").write_text(json.dumps(corrupted_json))

    # Run post_install.sh --apply
    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode == 0, f"post_install failed: {res.stderr}"

    # Verify branch was sanitized to stable
    branch_after = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=str(flutter_root), capture_output=True, text=True).stdout.strip()
    assert branch_after == "stable"

    # Verify all 51 contaminated tags were purged and exactly 1 canonical tag remains
    tags_after = subprocess.run(["git", "tag", "-l"], cwd=str(flutter_root), capture_output=True, text=True).stdout.splitlines()
    assert tags_after == ["3.44.0"]

    # Verify tag points at HEAD
    tag_head = subprocess.run(["git", "tag", "--points-at", "HEAD"], cwd=str(flutter_root), capture_output=True, text=True).stdout.splitlines()
    assert "3.44.0" in tag_head

    # Verify FETCH_HEAD was removed
    assert not (flutter_root / ".git" / "FETCH_HEAD").exists()

    # Verify flutter.version.json was regenerated with canonical metadata
    version_json_file = flutter_root / "bin" / "cache" / "flutter.version.json"
    data = json.loads(version_json_file.read_text(encoding="utf-8"))
    assert data["frameworkVersion"] == "3.44.0"
    assert data["channel"] == "stable"
    assert data["frameworkRevision"] == "6b182d2c7585eba26d4edce0f97630effd256c33"


def test_post_install_real_user_repo_preserved_non_destructive(tmp_path):
    """Verify post_install.sh refuses to destructively rewrite branches or tags on non-synthetic / real Git checkouts."""
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)

    # Initialize a non-synthetic repository with multiple user commits and a user branch
    subprocess.run(["git", "init", "-q"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "checkout", "-B", "user/feature-custom"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "config", "user.email", "user@developer.com"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "config", "user.name", "Developer"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Commit 1 by developer"], cwd=str(flutter_root), check=True)

    # Add second commit
    (flutter_root / "my_custom_file.txt").write_text("custom code")
    subprocess.run(["git", "add", "my_custom_file.txt"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Commit 2 by developer"], cwd=str(flutter_root), check=True)
    subprocess.run(["git", "tag", "user-custom-tag-v1"], cwd=str(flutter_root), check=True)

    # Run post_install.sh --apply
    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode == 0, f"post_install failed: {res.stderr}"

    # Verify user branch was NOT modified or renamed to stable
    branch_after = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=str(flutter_root), capture_output=True, text=True).stdout.strip()
    assert branch_after == "user/feature-custom"

    # Verify user tags were NOT deleted
    tags_after = subprocess.run(["git", "tag", "-l"], cwd=str(flutter_root), capture_output=True, text=True).stdout.splitlines()
    assert "user-custom-tag-v1" in tags_after


def test_post_install_dart_sdk_version_semantic_not_stamp(tmp_path):
    """Verify dartSdkVersion in flutter.version.json is a semantic version, never engine cache stamp."""
    import json
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)

    # Write engine commit hash into dart-sdk.stamp
    (flutter_root / "bin" / "cache" / "dart-sdk.stamp").write_text("5a2a6a42cce67f965cf540fcecf616faca624aa1\n")

    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode == 0

    version_json = flutter_root / "bin" / "cache" / "flutter.version.json"
    data = json.loads(version_json.read_text(encoding="utf-8"))
    assert data["dartSdkVersion"] == "3.12.2"
    assert "5a2a6a42" not in data["dartSdkVersion"]
