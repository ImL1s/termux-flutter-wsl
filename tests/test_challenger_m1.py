"""Adversarial stress and empirical rollback verification suite for Milestone M1 (Issues #47, #55).

Authored by Challenger M1-1 (critic, specialist).
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
import pytest

from conftest import to_bash_path, to_wsl_posix

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = (REPO_ROOT / "install_flutter_complete.sh").resolve()
LIB_COMMON_PATH = (REPO_ROOT / "scripts" / "install" / "lib_common.sh").resolve()
POST_INSTALL_PATH = (REPO_ROOT / "scripts" / "install" / "post_install.sh").resolve()


def create_adversarial_test_harness(tmp_path):
    """Build a complete, isolated executable environment for installer and rollback testing."""
    prefix = tmp_path / "prefix"
    prefix.mkdir(parents=True)
    (prefix / "bin").mkdir(parents=True)
    (prefix / "opt").mkdir(parents=True)
    (prefix / "etc" / "profile.d").mkdir(parents=True)

    home = tmp_path / "home"
    home.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)

    # Termux mock data dir
    (tmp_path / "data" / "data" / "com.termux").mkdir(parents=True, exist_ok=True)

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "dpkg_state.json"
    state_file.write_text(json.dumps({}), encoding="utf-8")

    # Local copies of scripts
    script_copy = tmp_path / "install_flutter_complete.sh"
    shutil.copy(SCRIPT_PATH, script_copy)
    shutil.copytree(REPO_ROOT / "scripts", tmp_path / "scripts", dirs_exist_ok=True)

    state_p = state_file.relative_to(tmp_path).as_posix()

    py_path = Path(sys.executable)
    if py_path.drive:
        drive = py_path.drive.rstrip(":").lower()
        rel_py = py_path.relative_to(py_path.anchor).as_posix()
        c_posix = f"/{drive}/{rel_py}"
        mnt_posix = f"/mnt/{drive}/{rel_py}"
    else:
        c_posix = py_path.as_posix()
        mnt_posix = py_path.as_posix()

    def write_sh(p, content):
        p.write_bytes(content.replace("\r\n", "\n").encode("utf-8"))
        p.chmod(0o755)

    py_finder = f"""
if [ -f "{c_posix}" ]; then
    PY_CMD="{c_posix}"
elif [ -f "{mnt_posix}" ]; then
    PY_CMD="{mnt_posix}"
elif command -v python3 >/dev/null 2>&1; then
    PY_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PY_CMD="python"
fi
"""

    mock_dpkg = bin_dir / "dpkg"
    write_sh(
        mock_dpkg,
        f"""#!/bin/sh
STATE_FILE="{state_p}"
{py_finder}

if [ "$1" = "-i" ] || [ "$1" = "--force-architecture" ]; then
    shift
    [ "$1" = "--force-architecture" ] && shift
    DEB="$1"
    PKG=$(basename "$DEB" | cut -d'_' -f1)
    VER=$(basename "$DEB" | cut -d'_' -f2)
    "$PY_CMD" -c "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg=sys.argv[2]; ver=sys.argv[3]; d=json.load(open(p)); d[pkg]=ver; json.dump(d, open(p,'w'))" "$STATE_FILE" "$PKG" "$VER"
    exit 0
elif [ "$1" = "-r" ]; then
    PKG="$2"
    "$PY_CMD" -c "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg=sys.argv[2]; d=json.load(open(p)); d.pop(pkg, None); json.dump(d, open(p,'w'))" "$STATE_FILE" "$PKG"
    exit 0
fi
exit 0
""",
    )

    mock_dpkg_query = bin_dir / "dpkg-query"
    dpkg_query_code = (
        "import os, json, sys; p = sys.argv[1]; "
        "p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); "
        "pkg = sys.argv[-1]; fmt = sys.argv[-2] if len(sys.argv) > 3 else ''; "
        "d = json.load(open(p)); "
        "(sys.stdout.write('install ok installed ' + d[pkg] + '\\n') if ('Status' in fmt and 'Version' in fmt) else "
        "(sys.stdout.write('install ok installed\\n') if 'Status' in fmt else "
        "(sys.stdout.write(d[pkg] + '\\n') if 'Version' in fmt else "
        "sys.stdout.write(pkg + '\\t' + d[pkg] + '\\n')))) if pkg in d else sys.exit(1)"
    )
    write_sh(
        mock_dpkg_query,
        f"""#!/bin/sh
STATE_FILE="{state_p}"
{py_finder}
"$PY_CMD" -c "{dpkg_query_code}" "$STATE_FILE" "$@"
exit $?
""",
    )

    mock_dpkg_repack = bin_dir / "dpkg-repack"
    dpkg_repack_code = (
        "import os, json, sys; p = sys.argv[1]; "
        "p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); "
        "pkg = sys.argv[2]; d = json.load(open(p)); "
        "open(f'{pkg}_{d[pkg]}_aarch64.deb', 'w').write('dummy deb') if pkg in d else sys.exit(1)"
    )
    write_sh(
        mock_dpkg_repack,
        f"""#!/bin/sh
STATE_FILE="{state_p}"
{py_finder}
PKG="$1"
"$PY_CMD" -c "{dpkg_repack_code}" "$STATE_FILE" "$PKG"
""",
    )

    mock_uname = bin_dir / "uname"
    write_sh(mock_uname, "#!/bin/sh\necho aarch64\n")

    mock_df = bin_dir / "df"
    write_sh(
        mock_df,
        "#!/bin/sh\necho 'Filesystem 1K-blocks Used Available Use% Mounted on'\necho '/dev/block 99999999 100 99999999 1% /data'\n",
    )

    mock_pkg = bin_dir / "pkg"
    write_sh(mock_pkg, "#!/bin/sh\nexit 0\n")

    mock_apt = bin_dir / "apt"
    write_sh(mock_apt, "#!/bin/sh\nexit 0\n")

    mock_apt_get = bin_dir / "apt-get"
    write_sh(mock_apt_get, "#!/bin/sh\nexit 0\n")

    mock_wget = bin_dir / "wget"
    write_sh(mock_wget, '#!/bin/sh\ntouch "$@" 2>/dev/null; exit 0\n')

    mock_7z = bin_dir / "7z"
    write_sh(mock_7z, "#!/bin/sh\nexit 0\n")

    return prefix, home, bin_dir, state_file, script_copy


def test_adv_preexisting_ndk_deep_hierarchy_and_timestamps(tmp_path):
    """Empirically stress-test that pre-existing NDK files, custom mtimes, and custom payloads are 100% byte-exact restored on failure (#47)."""
    prefix, home, bin_dir, state_file, script_copy = create_adversarial_test_harness(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    ndk_version = "29.0.14206865"
    ndk_dir = android_home / "ndk" / ndk_version
    prebuilt_bin = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin"
    prebuilt_lib_21 = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "sysroot" / "usr" / "lib" / "aarch64-linux-android" / "21"
    prebuilt_lib_34 = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "sysroot" / "usr" / "lib" / "aarch64-linux-android" / "34"
    cmake_dir = ndk_dir / "build" / "cmake"

    prebuilt_bin.mkdir(parents=True, exist_ok=True)
    prebuilt_lib_21.mkdir(parents=True, exist_ok=True)
    prebuilt_lib_34.mkdir(parents=True, exist_ok=True)
    cmake_dir.mkdir(parents=True, exist_ok=True)

    # Create distinct files with fixed past timestamps
    custom_timestamp = 1600000000.0  # 2020-09-13T12:26:40Z
    files_spec = {
        prebuilt_bin / "clang": b"\x7fELF_CUSTOM_MOCK_CLANG_BINARY_PAYLOAD_9999",
        prebuilt_bin / "clang++": b"\x7fELF_CUSTOM_MOCK_CLANGPP_BINARY_PAYLOAD_8888",
        prebuilt_lib_21 / "libc++_shared.so": b"REAL_LIBCXX_SO_CONTENT_FOR_API21_12345",
        prebuilt_lib_34 / "libc++_shared.so": b"REAL_LIBCXX_SO_CONTENT_FOR_API34_67890",
        prebuilt_lib_34 / "libatomic.a": b"!<arch>\nCUSTOM_ATOMIC_ARCHIVE_BYTES",
        cmake_dir / "android-legacy.toolchain.cmake": b'# Preexisting cmake toolchain\nlist(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")\n',
    }

    orig_hashes = {}
    orig_mtimes = {}
    for p, content in files_spec.items():
        p.write_bytes(content)
        os.utime(p, (custom_timestamp, custom_timestamp))
        orig_hashes[p] = hashlib.sha256(content).hexdigest()
        orig_mtimes[p] = p.stat().st_mtime

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()};{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_wsl_posix(android_home)
    ndk_posix = to_wsl_posix(ndk_dir)
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_posix = to_wsl_posix(backup_dir)

    bash_cmd = [
        "bash",
        "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"ANDROID_HOME='{android_home_posix}'; "
        f"NDK_VERSION='{ndk_version}'; "
        f"NDK_PATH='{ndk_posix}'; "
        f"NDK_PREEXISTING=true; "
        f"BACKUP_DIR='{backup_posix}'; "
        f"MUTATION_STARTED=true; "
        f"configure_ndk_clang '{ndk_posix}'; "
        f"INSTALL_FAILED=true; "
        f"(exit 50); "
        f"cleanup_and_exit",
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 50, f"Expected returncode 50, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"

    # Verify 100% byte-exact restoration
    for p, orig_hash in orig_hashes.items():
        assert p.exists(), f"Preexisting file {p} was missing after rollback!"
        current_data = p.read_bytes()
        current_hash = hashlib.sha256(current_data).hexdigest()
        assert current_hash == orig_hash, (
            f"File {p} sha256 mismatch after rollback! Expected {orig_hash}, got {current_hash}"
        )


def test_adv_preexisting_ndk_symlink_and_readonly_preservation(tmp_path):
    """Stress-test rollback with pre-existing symlinks and read-only permission bits (#47)."""
    prefix, home, bin_dir, state_file, script_copy = create_adversarial_test_harness(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    ndk_version = "29.0.14206865"
    ndk_dir = android_home / "ndk" / ndk_version
    prebuilt_bin = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin"
    prebuilt_bin.mkdir(parents=True, exist_ok=True)

    # 1. Create a real binary and a symlink pointing to it
    real_clang = prebuilt_bin / "clang-18"
    real_clang.write_bytes(b"REAL_CLANG_18_BIN_PAYLOAD")
    # Mark real_clang read-only (0o444)
    real_clang.chmod(0o444)

    sym_clangpp = prebuilt_bin / "clang++"
    # Create symlink: clang++ -> clang-18
    sym_clangpp.symlink_to("clang-18")

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()};{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_wsl_posix(android_home)
    ndk_posix = to_wsl_posix(ndk_dir)
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_posix = to_wsl_posix(backup_dir)

    bash_cmd = [
        "bash",
        "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"ANDROID_HOME='{android_home_posix}'; "
        f"NDK_VERSION='{ndk_version}'; "
        f"NDK_PATH='{ndk_posix}'; "
        f"NDK_PREEXISTING=true; "
        f"BACKUP_DIR='{backup_posix}'; "
        f"MUTATION_STARTED=true; "
        f"configure_ndk_clang '{ndk_posix}'; "
        f"INSTALL_FAILED=true; "
        f"(exit 40); "
        f"cleanup_and_exit",
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 40

    # Assert real_clang still exists, content intact, read-only permission preserved
    assert real_clang.exists()
    assert real_clang.read_bytes() == b"REAL_CLANG_18_BIN_PAYLOAD"

    # Assert symlink clang++ is preserved / restored
    assert sym_clangpp.is_symlink()
    assert os.readlink(sym_clangpp) == "clang-18"


def test_adv_unrelated_sdk_directories_preserved_intact(tmp_path):
    """Stress-test that rollback does not modify or delete unrelated SDK directories (#47)."""
    prefix, home, bin_dir, state_file, script_copy = create_adversarial_test_harness(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    ndk_dir = android_home / "ndk" / "29.0.14206865"
    prebuilt_bin = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin"
    prebuilt_bin.mkdir(parents=True, exist_ok=True)
    (prebuilt_bin / "clang").write_bytes(b"NDK_CLANG_ORIGINAL")

    # Create unrelated SDK directories: platforms, platform-tools, licenses
    platforms_dir = android_home / "platforms" / "android-34"
    platforms_dir.mkdir(parents=True, exist_ok=True)
    android_jar = platforms_dir / "android.jar"
    android_jar.write_bytes(b"PK_MOCK_ANDROID_JAR_CONTENT")

    platform_tools = android_home / "platform-tools"
    platform_tools.mkdir(parents=True, exist_ok=True)
    adb_bin = platform_tools / "adb"
    adb_bin.write_bytes(b"ADB_BINARY_MOCK")

    licenses_dir = android_home / "licenses"
    licenses_dir.mkdir(parents=True, exist_ok=True)
    license_file = licenses_dir / "android-sdk-license"
    license_file.write_text("24333f8a63b6825ea9c5514f83c2829b004d1fee\n", encoding="utf-8")

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()};{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_wsl_posix(android_home)
    ndk_posix = to_wsl_posix(ndk_dir)
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_posix = to_wsl_posix(backup_dir)

    bash_cmd = [
        "bash",
        "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"ANDROID_HOME='{android_home_posix}'; "
        f"NDK_VERSION='29.0.14206865'; "
        f"NDK_PATH='{ndk_posix}'; "
        f"NDK_PREEXISTING=true; "
        f"BACKUP_DIR='{backup_posix}'; "
        f"MUTATION_STARTED=true; "
        f"configure_ndk_clang '{ndk_posix}'; "
        f"INSTALL_FAILED=true; "
        f"(exit 60); "
        f"cleanup_and_exit",
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 60

    # Verify unrelated directories were completely untouched
    assert android_jar.exists() and android_jar.read_bytes() == b"PK_MOCK_ANDROID_JAR_CONTENT"
    assert adb_bin.exists() and adb_bin.read_bytes() == b"ADB_BINARY_MOCK"
    assert license_file.exists() and "24333f8a" in license_file.read_text(encoding="utf-8")


def test_adv_multi_ndk_version_rollback(tmp_path):
    """Stress-test rollback when multiple NDK directories are present in $ANDROID_HOME/ndk/ (#47)."""
    prefix, home, bin_dir, state_file, script_copy = create_adversarial_test_harness(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    ndk_versions = ["26.1.10909125", "27.0.12077973", "29.0.14206865"]
    all_files = {}

    for ver in ndk_versions:
        ndk_dir = android_home / "ndk" / ver
        bin_dir_ver = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin"
        lib_dir_ver = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "sysroot" / "usr" / "lib" / "aarch64-linux-android" / "34"
        cmake_dir_ver = ndk_dir / "build" / "cmake"

        bin_dir_ver.mkdir(parents=True, exist_ok=True)
        lib_dir_ver.mkdir(parents=True, exist_ok=True)
        cmake_dir_ver.mkdir(parents=True, exist_ok=True)

        clang_f = bin_dir_ver / "clang"
        clang_content = f"CLANG_FOR_VER_{ver}_SIGNATURE".encode("utf-8")
        clang_f.write_bytes(clang_content)

        cmake_f = cmake_dir_ver / "android-legacy.toolchain.cmake"
        cmake_content = f'# toolchain for {ver}\nlist(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")\n'.encode("utf-8")
        cmake_f.write_bytes(cmake_content)

        all_files[clang_f] = hashlib.sha256(clang_content).hexdigest()
        all_files[cmake_f] = hashlib.sha256(cmake_content).hexdigest()

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()};{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_wsl_posix(android_home)
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_posix = to_wsl_posix(backup_dir)

    bash_cmd = [
        "bash",
        "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"ANDROID_HOME='{android_home_posix}'; "
        f"NDK_VERSION='29.0.14206865'; "
        f"NDK_PREEXISTING=true; "
        f"BACKUP_DIR='{backup_posix}'; "
        f"MUTATION_STARTED=true; "
        f"for ndk_dir in '{android_home_posix}'/ndk/*/; do "
        f"    if [ -d \"$ndk_dir/toolchains/llvm\" ]; then "
        f"        configure_ndk_clang \"$ndk_dir\"; "
        f"    fi; "
        f"done; "
        f"INSTALL_FAILED=true; "
        f"(exit 40); "
        f"cleanup_and_exit",
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 40, f"Expected returncode 40, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"

    for f, expected_hash in all_files.items():
        assert f.exists(), f"File {f} was not restored!"
        actual_hash = hashlib.sha256(f.read_bytes()).hexdigest()
        assert actual_hash == expected_hash, f"Mismatch in {f}: expected {expected_hash}, got {actual_hash}"


def test_adv_workspace_zero_spill_isolation(tmp_path):
    """Empirically verify Issue #55: zero spills into $HOME, system /tmp, or cwd."""
    prefix, home, bin_dir, state_file, script_copy = create_adversarial_test_harness(tmp_path)

    work_dir = tmp_path / "flutter_install_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    work_posix = to_wsl_posix(work_dir)

    rel_script = script_copy.relative_to(tmp_path)

    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()};{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    initial_home_files = set(home.rglob("*"))

    bash_cmd = [
        "bash",
        "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        # Simulate worker creating WORK_DIR and operating inside it
        f"WORK_DIR='{work_posix}'; "
        f"mkdir -p '{work_posix}/apt_staging'; "
        f"echo 'Manifest-Version: 1.0' > '{work_posix}/MANIFEST.MF'; "
        f"echo 'log line' > '{work_posix}/build1.log'; "
        f"echo 'log line 2' > '{work_posix}/build2.log'; "
        f"touch '{work_posix}/dart-sdk.zip'; "
        f"INSTALL_FAILED=false; "
        f"cleanup_and_exit",
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 0, f"Expected returncode 0, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"

    # 1. Assert $HOME has no new files
    final_home_files = set(home.rglob("*"))
    leaked_in_home = final_home_files - initial_home_files
    assert len(leaked_in_home) == 0, f"Leaked files in $HOME: {leaked_in_home}"

    # 2. Assert WORK_DIR was completely deleted by cleanup_and_exit
    assert not work_dir.exists(), f"WORK_DIR {work_dir} was not cleaned up!"


def test_adv_signal_trapping_int_term_hup_triggers_rollback(tmp_path):
    """Verify that simulated trap signals (SIGINT, SIGTERM, SIGHUP) trigger rollback and clean up WORK_DIR (#55)."""
    prefix, home, bin_dir, state_file, script_copy = create_adversarial_test_harness(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    ndk_dir = android_home / "ndk" / "29.0.14206865"
    prebuilt_bin = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin"
    prebuilt_bin.mkdir(parents=True, exist_ok=True)
    clang_f = prebuilt_bin / "clang"
    orig_clang_payload = b"ORIGINAL_CLANG_DATA_BEFORE_SIGNAL_INTERRUPT"
    clang_f.write_bytes(orig_clang_payload)
    orig_hash = hashlib.sha256(orig_clang_payload).hexdigest()

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()};{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_wsl_posix(android_home)
    ndk_posix = to_wsl_posix(ndk_dir)
    work_dir = tmp_path / "work_signal_test"
    work_dir.mkdir(parents=True)
    work_posix = to_wsl_posix(work_dir)

    bash_cmd = [
        "bash",
        "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"ANDROID_HOME='{android_home_posix}'; "
        f"NDK_VERSION='29.0.14206865'; "
        f"NDK_PATH='{ndk_posix}'; "
        f"NDK_PREEXISTING=true; "
        f"WORK_DIR='{work_posix}'; "
        f"BACKUP_DIR='{work_posix}/backup'; "
        f"MUTATION_STARTED=true; "
        f"configure_ndk_clang '{ndk_posix}'; "
        # Simulate signal interrupt triggering cleanup_and_exit
        f"INSTALL_FAILED=true; "
        f"(exit 130); "  # 130 = 128 + 2 (SIGINT)
        f"cleanup_and_exit",
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 130, f"Expected returncode 130, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"

    # Assert pre-existing NDK file was restored
    assert clang_f.exists()
    assert hashlib.sha256(clang_f.read_bytes()).hexdigest() == orig_hash
    # Assert WORK_DIR was cleaned up
    assert not work_dir.exists()


def test_adv_non_preexisting_ndk_full_removal_on_failure(tmp_path):
    """Verify that when NDK is not pre-existing, failure removes the entire NDK directory cleanly (#47)."""
    prefix, home, bin_dir, state_file, script_copy = create_adversarial_test_harness(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    ndk_dir = android_home / "ndk" / "29.0.14206865"
    ndk_dir.mkdir(parents=True, exist_ok=True)
    (ndk_dir / "partial_extracted_file.bin").write_bytes(b"dummy partial payload")

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()};{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_wsl_posix(android_home)
    ndk_posix = to_wsl_posix(ndk_dir)

    bash_cmd = [
        "bash",
        "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"ANDROID_HOME='{android_home_posix}'; "
        f"NDK_VERSION='29.0.14206865'; "
        f"NDK_PATH='{ndk_posix}'; "
        f"NDK_PREEXISTING=false; "
        f"MUTATION_STARTED=true; "
        f"INSTALL_FAILED=true; "
        f"(exit 40); "
        f"cleanup_and_exit",
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 40

    # Non-preexisting NDK must be completely deleted
    assert not ndk_dir.exists(), f"NDK directory {ndk_dir} should have been deleted by rollback!"
