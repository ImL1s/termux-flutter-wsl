import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build import Build
import utils
from test_installer_rollback import create_executable_state_machine_harness

REPO_ROOT = Path(__file__).parent.parent
LIB_COMMON = (REPO_ROOT / "scripts" / "install" / "lib_common.sh").resolve()
INSTALLER = (REPO_ROOT / "install_flutter_complete.sh").resolve()


def get_bash_cmd():
    return ["bash"]


def to_bash_posix(path):
    p = Path(path).resolve().as_posix()
    if len(p) > 1 and p[1] == ":":
        drive = p[0].lower()
        return f"/mnt/{drive}{p[2:]}"
    return p


# ==============================================================================
# 1. Directory Pruning Safety Boundaries in cleanup_absent_preimages
# ==============================================================================

def test_pruning_never_escapes_android_home(tmp_path):
    """Verify that pruning empty parent directories strictly stops at $ANDROID_HOME and never deletes $ANDROID_HOME itself."""
    android_home = tmp_path / "opt" / "android-sdk"
    ndk_bin = android_home / "ndk" / "28.0.12345" / "toolchains" / "llvm" / "prebuilt" / "bin"
    ndk_bin.mkdir(parents=True)
    created_file = ndk_bin / "clang"
    created_file.write_text("#!/bin/sh\necho clang")

    manifest = tmp_path / "absent.txt"
    manifest_posix = to_bash_posix(manifest)
    lib_posix = to_bash_posix(LIB_COMMON)
    file_posix = to_bash_posix(created_file)
    ah_posix = to_bash_posix(android_home)

    bash_cmd = get_bash_cmd() + [
        "-c",
        f"source '{lib_posix}'; "
        f"export ANDROID_HOME='{ah_posix}'; "
        f"export ABSENT_MANIFEST='{manifest_posix}'; "
        f"record_absent_preimage '{file_posix}'; "
        f"cleanup_absent_preimages"
    ]
    res = subprocess.run(bash_cmd, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 0, f"Cleanup failed: {res.stderr}"

    # Created file must be deleted
    assert not created_file.exists(), "Created file was not removed"
    # Empty intermediate directories should be pruned
    assert not (android_home / "ndk").exists(), "Empty ndk parent dir was not pruned"
    # ANDROID_HOME root directory MUST NOT be deleted even though it is now empty!
    assert android_home.exists(), "$ANDROID_HOME root directory was erroneously deleted!"


def test_pruning_never_escapes_prefix(tmp_path):
    """Verify that pruning stops at $PREFIX and never deletes $PREFIX root."""
    prefix = tmp_path / "data" / "data" / "com.termux" / "files" / "usr"
    sub_dir = prefix / "opt" / "nested" / "deep"
    sub_dir.mkdir(parents=True)
    created_file = sub_dir / "stub.so"
    created_file.write_text("stub")

    manifest = tmp_path / "absent.txt"
    manifest_posix = to_bash_posix(manifest)
    lib_posix = to_bash_posix(LIB_COMMON)
    file_posix = to_bash_posix(created_file)
    prefix_posix = to_bash_posix(prefix)

    bash_cmd = get_bash_cmd() + [
        "-c",
        f"source '{lib_posix}'; "
        f"export PREFIX='{prefix_posix}'; "
        f"export ABSENT_MANIFEST='{manifest_posix}'; "
        f"record_absent_preimage '{file_posix}'; "
        f"cleanup_absent_preimages"
    ]
    res = subprocess.run(bash_cmd, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 0, f"Cleanup failed: {res.stderr}"

    assert not created_file.exists()
    assert not (prefix / "opt").exists()
    assert prefix.exists(), "$PREFIX directory was erroneously deleted!"


def test_pruning_never_escapes_work_dir(tmp_path):
    """Verify that pruning stops at $WORK_DIR and never deletes $WORK_DIR root."""
    work_dir = tmp_path / "staging_work_dir"
    sub_dir = work_dir / "a" / "b" / "c"
    sub_dir.mkdir(parents=True)
    created_file = sub_dir / "temp.bin"
    created_file.write_text("temp")

    manifest = tmp_path / "absent.txt"
    manifest_posix = to_bash_posix(manifest)
    lib_posix = to_bash_posix(LIB_COMMON)
    file_posix = to_bash_posix(created_file)
    work_posix = to_bash_posix(work_dir)

    bash_cmd = get_bash_cmd() + [
        "-c",
        f"source '{lib_posix}'; "
        f"export WORK_DIR='{work_posix}'; "
        f"export ABSENT_MANIFEST='{manifest_posix}'; "
        f"record_absent_preimage '{file_posix}'; "
        f"cleanup_absent_preimages"
    ]
    res = subprocess.run(bash_cmd, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 0, f"Cleanup failed: {res.stderr}"

    assert not created_file.exists()
    assert not (work_dir / "a").exists()
    assert work_dir.exists(), "$WORK_DIR directory was erroneously deleted!"


def test_pruning_preserves_sibling_non_empty_directories(tmp_path):
    """Verify that if a parent directory contains non-absent sibling files, it is NOT pruned."""
    base_dir = tmp_path / "android-sdk" / "ndk" / "28.0.1" / "bin"
    base_dir.mkdir(parents=True)
    created_file = base_dir / "clang"
    created_file.write_text("new clang")
    sibling_file = base_dir / "existing_tool"
    sibling_file.write_text("preserve me")

    manifest = tmp_path / "absent.txt"
    manifest_posix = to_bash_posix(manifest)
    lib_posix = to_bash_posix(LIB_COMMON)
    file_posix = to_bash_posix(created_file)

    bash_cmd = get_bash_cmd() + [
        "-c",
        f"source '{lib_posix}'; "
        f"export ABSENT_MANIFEST='{manifest_posix}'; "
        f"record_absent_preimage '{file_posix}'; "
        f"cleanup_absent_preimages"
    ]
    res = subprocess.run(bash_cmd, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 0

    assert not created_file.exists()
    assert sibling_file.exists(), "Sibling file must NOT be deleted"
    assert sibling_file.read_text() == "preserve me"
    assert base_dir.exists(), "Directory containing non-absent sibling must NOT be pruned"


def test_pruning_handles_broken_symlinks_and_spaces(tmp_path):
    """Verify that cleanup_absent_preimages correctly removes broken symlinks and paths with spaces."""
    spaced_dir = tmp_path / "dir with spaces" / "sub dir"
    spaced_dir.mkdir(parents=True)
    
    # Broken symlink (target created, linked, then target removed)
    broken_symlink = spaced_dir / "broken_link.so"
    temp_target = spaced_dir / "target.so"
    
    lib_posix = to_bash_posix(LIB_COMMON)
    manifest = tmp_path / "absent.txt"
    manifest_posix = to_bash_posix(manifest)
    link_posix = to_bash_posix(broken_symlink)
    target_posix = to_bash_posix(temp_target)

    bash_cmd = get_bash_cmd() + [
        "-c",
        f"touch '{target_posix}'; "
        f"ln -s '{target_posix}' '{link_posix}'; "
        f"rm -f '{target_posix}'; "
        f"source '{lib_posix}'; "
        f"export ABSENT_MANIFEST='{manifest_posix}'; "
        f"record_absent_preimage '{link_posix}'; "
        f"cleanup_absent_preimages"
    ]
    res = subprocess.run(bash_cmd, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 0, f"Failed on broken symlink cleanup: {res.stderr}"

    assert not broken_symlink.exists() and not broken_symlink.is_symlink(), "Broken symlink must be removed"
    assert not spaced_dir.exists(), "Empty spaced directory must be pruned"


# ==============================================================================
# 2. Clone Staging & Transactional Activation in build.py
# ==============================================================================

def test_successful_clone_with_existing_out_path_cleans_up_backup(tmp_path, monkeypatch):
    """Verify that when clone replaces an existing directory successfully, the temporary backup directory is cleaned up."""
    out_dir = tmp_path / "flutter_sdk"
    out_dir.mkdir(parents=True)
    (out_dir / "old_version.txt").write_text("OLD")

    conf_path = tmp_path / "build.toml"
    package_yaml = tmp_path / "package.yaml"
    package_yaml.write_text("control:\n  Package: flutter\n  Version: 3.44.9\n", encoding="utf-8")

    flutter_str = str(out_dir).replace('\\', '/')
    package_str = str(package_yaml).replace('\\', '/')

    conf_content = f"""
    [flutter]
    tag = "3.44.9"
    path = "{flutter_str}"
    [package]
    conf = "{package_str}"
    """
    conf_path.write_text(conf_content, encoding="utf-8")

    import git
    def mock_clone(url, to_path, progress, branch):
        p = Path(to_path)
        p.mkdir(parents=True, exist_ok=True)
        (p / "bin").mkdir(parents=True, exist_ok=True)
        (p / "bin" / "flutter").write_text("#!/bin/sh\necho flutter")
        (p / "new_version.txt").write_text("NEW")

    monkeypatch.setattr(git.Repo, 'clone_from', mock_clone)
    monkeypatch.setattr(utils, 'flutter_tag', lambda path: '3.44.9')

    b = Build(conf=str(conf_path))
    b.clone(tag='3.44.9', force=True)

    # Check that out_dir contains new content
    assert out_dir.exists()
    assert (out_dir / "new_version.txt").exists()
    assert not (out_dir / "old_version.txt").exists()

    # Check if any backup directories linger
    parent_entries = [p.name for p in out_dir.parent.iterdir() if p.name != out_dir.name and p != conf_path and p != package_yaml]
    backups = [e for e in parent_entries if "backup_" in e or "staging_" in e]
    assert len(backups) == 0, f"Lingering backup/staging directories found after successful clone: {backups}"


def test_concurrent_clone_failure_does_not_corrupt_active_checkout(tmp_path, monkeypatch):
    """Verify that when one clone fails midway due to network/git error, the existing checkout remains untouched."""
    out_dir = tmp_path / "flutter_sdk"
    out_dir.mkdir(parents=True)
    (out_dir / "bin").mkdir(parents=True)
    (out_dir / "bin" / "flutter").write_text("EXISTING_FLUTTER")
    (out_dir / "sentinel.txt").write_text("CRITICAL_PREEXISTING_DATA")

    conf_path = tmp_path / "build.toml"
    package_yaml = tmp_path / "package.yaml"
    package_yaml.write_text("control:\n  Package: flutter\n  Version: 3.44.9\n", encoding="utf-8")

    flutter_str = str(out_dir).replace('\\', '/')
    package_str = str(package_yaml).replace('\\', '/')

    conf_content = f"""
    [flutter]
    tag = "3.44.9"
    path = "{flutter_str}"
    [package]
    conf = "{package_str}"
    """
    conf_path.write_text(conf_content, encoding="utf-8")

    import git
    def mock_failing_clone(url, to_path, progress, branch):
        p = Path(to_path)
        p.mkdir(parents=True, exist_ok=True)
        (p / "partial.tmp").write_text("partial")
        raise git.exc.GitCommandError("git clone", "Simulated fatal network disconnect")

    monkeypatch.setattr(git.Repo, 'clone_from', mock_failing_clone)

    b = Build(conf=str(conf_path))
    with pytest.raises(RuntimeError, match="Failed to clone flutter repo"):
        b.clone(tag='3.44.9', force=True)

    # Existing checkout must be fully preserved
    assert out_dir.exists(), "Existing checkout must remain intact on clone failure"
    assert (out_dir / "sentinel.txt").read_text() == "CRITICAL_PREEXISTING_DATA"

    # All staging directories must be cleaned up
    parent_entries = [p.name for p in out_dir.parent.iterdir() if p.name.startswith("flutter_sdk.staging_")]
    assert len(parent_entries) == 0, f"Found lingering staging directories: {parent_entries}"


def test_transactional_activation_multi_step_rollback(tmp_path, monkeypatch):
    """Verify that if activation rename fails, the original directory is restored byte-for-byte and error propagates."""
    out_dir = tmp_path / "flutter_sdk"
    out_dir.mkdir(parents=True)
    (out_dir / "important_data.txt").write_text("STAY_ALIVE")

    conf_path = tmp_path / "build.toml"
    package_yaml = tmp_path / "package.yaml"
    package_yaml.write_text("control:\n  Package: flutter\n  Version: 3.44.9\n", encoding="utf-8")

    flutter_str = str(out_dir).replace('\\', '/')
    package_str = str(package_yaml).replace('\\', '/')

    conf_content = f"""
    [flutter]
    tag = "3.44.9"
    path = "{flutter_str}"
    [package]
    conf = "{package_str}"
    """
    conf_path.write_text(conf_content, encoding="utf-8")

    import git
    def mock_clone(url, to_path, progress, branch):
        p = Path(to_path)
        p.mkdir(parents=True, exist_ok=True)
        (p / "new_data.txt").write_text("NEW")

    monkeypatch.setattr(git.Repo, 'clone_from', mock_clone)
    monkeypatch.setattr(utils, 'flutter_tag', lambda path: '3.44.9')

    orig_rename = os.rename
    rename_count = 0
    def failing_rename(src, dst):
        nonlocal rename_count
        rename_count += 1
        # First rename (out_dir -> backup) succeeds
        # Second rename (staging -> out_dir) fails
        if rename_count == 2:
            raise PermissionError("Simulated Access Denied on staging rename")
        return orig_rename(src, dst)

    monkeypatch.setattr(os, 'rename', failing_rename)

    b = Build(conf=str(conf_path))
    with pytest.raises(RuntimeError, match="Transactional activation failed for"):
        b.clone(tag='3.44.9', force=True)

    # Verify original dir was restored
    assert out_dir.exists()
    assert (out_dir / "important_data.txt").read_text() == "STAY_ALIVE"
    assert not (out_dir / "new_data.txt").exists()

    # Verify no backup or staging directories left behind
    entries = [p.name for p in out_dir.parent.iterdir() if p != conf_path and p != package_yaml and p != out_dir]
    assert len(entries) == 0, f"Found lingering directories: {entries}"


# ==============================================================================
# 3. Multi-NDK Absent Recording & Complex Rollback Scenarios
# ==============================================================================

def test_multi_ndk_deep_hierarchy_rollback_and_exit_code_preservation(tmp_path):
    """Verify that with multiple NDK versions, absent preimages are pruned across all NDKs and exit code is preserved."""
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    ndk_versions = ["26.1.10909125", "27.0.12077973", "28.0.12674721", "29.0.14206865"]
    for v in ndk_versions:
        ndk_dir = android_home / "ndk" / v
        bin_dir_ndk = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin"
        bin_dir_ndk.mkdir(parents=True)
        (bin_dir_ndk / "clang").write_text(f"original_clang_{v}")
        (bin_dir_ndk / "clang++").write_text(f"original_clangpp_{v}")

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(parents=True)

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_bash_posix(prefix)
    env["HOME"] = to_bash_posix(home)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    ah_posix = to_bash_posix(android_home)
    backup_posix = to_bash_posix(backup_dir)

    # Simulate configuring all NDKs, then failing with exit code 77
    bash_cmd = get_bash_cmd() + [
        "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"ANDROID_HOME='{ah_posix}'; "
        f"NDK_PREEXISTING=true; "
        f"BACKUP_DIR='{backup_posix}'; "
        f"MUTATION_STARTED=true; "
        f"for ndk_d in '{ah_posix}'/ndk/*/; do "
        f"    configure_ndk_clang \"$ndk_d\"; "
        f"done; "
        f"INSTALL_FAILED=true; "
        f"(exit 77); "
        f"cleanup_and_exit"
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 77, f"Expected exit code 77 preserved, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"

    # Verify each NDK:
    # 1. prebuilt/bin/clang and prebuilt/bin/clang++ created in prebuilt/bin must be deleted and prebuilt/bin pruned!
    # 2. prebuilt/sysroot symlink must be deleted!
    # 3. Original files in linux-x86_64/bin must be intact!
    for v in ndk_versions:
        ndk_dir = android_home / "ndk" / v
        prebuilt = ndk_dir / "toolchains" / "llvm" / "prebuilt"
        assert not (prebuilt / "bin").exists(), f"prebuilt/bin was not pruned in NDK {v}"
        assert not (prebuilt / "sysroot").exists(), f"prebuilt/sysroot was not removed in NDK {v}"
        orig_clang = prebuilt / "linux-x86_64" / "bin" / "clang"
        assert orig_clang.read_text() == f"original_clang_{v}"
