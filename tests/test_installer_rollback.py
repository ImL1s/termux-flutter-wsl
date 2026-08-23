import hashlib
import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
import pytest

from conftest import to_bash_path, to_wsl_posix

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = (REPO_ROOT / "install_flutter_complete.sh").resolve()

def create_executable_state_machine_harness(tmp_path):
    prefix = tmp_path / "prefix"
    prefix.mkdir()
    (prefix / "bin").mkdir()
    (prefix / "opt").mkdir()
    (prefix / "etc" / "profile.d").mkdir(parents=True)

    home = tmp_path / "home"
    home.mkdir()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Create fake Termux data directory so preflight check passes
    (tmp_path / "data" / "data" / "com.termux").mkdir(parents=True, exist_ok=True)

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_file = state_dir / "dpkg_state.json"
    state_file.write_text(json.dumps({}))

    # Copy script and scripts directory into tmp_path so sourcing works seamlessly
    script_copy = tmp_path / "install_flutter_complete.sh"
    shutil.copy(SCRIPT_PATH, script_copy)
    shutil.copytree(REPO_ROOT / "scripts", tmp_path / "scripts", dirs_exist_ok=True)

    state_p = state_file.relative_to(tmp_path).as_posix()

    py_path = Path(sys.executable)
    if py_path.drive:
        drive = py_path.drive.rstrip(':').lower()
        rel_py = py_path.relative_to(py_path.anchor).as_posix()
        c_posix = f"/{drive}/{rel_py}"
        mnt_posix = f"/mnt/{drive}/{rel_py}"
    else:
        c_posix = py_path.as_posix()
        mnt_posix = py_path.as_posix()

    def write_sh(p, content):
        p.write_bytes(content.replace('\r\n', '\n').encode('utf-8'))
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
    write_sh(mock_dpkg, f"""#!/bin/sh
STATE_FILE="{state_p}"
{py_finder}

if [ "$1" = "-i" ]; then
    if [ -f fail_reinstall ]; then
        exit 1
    fi
    DEB="$2"
    PKG=$(basename "$DEB" | cut -d'_' -f1)
    VER=$(basename "$DEB" | cut -d'_' -f2)
    "$PY_CMD" -c "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg=sys.argv[2]; ver=sys.argv[3]; d=json.load(open(p)); d[pkg]=ver; json.dump(d, open(p,'w'))" "$STATE_FILE" "$PKG" "$VER"
    exit 0
elif [ "$1" = "-r" ]; then
    if [ -f fail_remove ]; then
        exit 1
    fi
    PKG="$2"
    "$PY_CMD" -c "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg=sys.argv[2]; d=json.load(open(p)); d.pop(pkg, None); json.dump(d, open(p,'w'))" "$STATE_FILE" "$PKG"
    exit 0
elif [ "$1" = "-l" ]; then
    PKG="$2"
    "$PY_CMD" -c "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg=sys.argv[2]; d=json.load(open(p)); print('ii ' + pkg if pkg in d else '')" "$STATE_FILE" "$PKG"
    exit 0
fi
exit 0
""")

    mock_dpkg_query = bin_dir / "dpkg-query"
    dpkg_query_code = "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg = sys.argv[-1]; fmt = sys.argv[-2] if len(sys.argv) > 3 else ''; d = json.load(open(p)); (sys.stdout.write('install ok installed ' + d[pkg] + '\\n') if ('Status' in fmt and 'Version' in fmt) else (sys.stdout.write('install ok installed\\n') if 'Status' in fmt else (sys.stdout.write(d[pkg] + '\\n') if 'Version' in fmt else sys.stdout.write(pkg + '\\t' + d[pkg] + '\\n')))) if pkg in d else sys.exit(1)"
    write_sh(mock_dpkg_query, f"""#!/bin/sh
STATE_FILE="{state_p}"
{py_finder}
"$PY_CMD" -c "{dpkg_query_code}" "$STATE_FILE" "$@"
exit $?
""")

    mock_dpkg_repack = bin_dir / "dpkg-repack"
    dpkg_repack_code = "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg = sys.argv[2]; d = json.load(open(p)); open(f'{{pkg}}_{{d[pkg]}}_aarch64.deb', 'w').write('dummy deb') if pkg in d else sys.exit(1)"
    write_sh(mock_dpkg_repack, f"""#!/bin/sh
STATE_FILE="{state_p}"
{py_finder}
PKG="$1"
"$PY_CMD" -c "{dpkg_repack_code}" "$STATE_FILE" "$PKG"
""")

    mock_uname = bin_dir / "uname"
    write_sh(mock_uname, "#!/bin/sh\necho aarch64\n")

    mock_df = bin_dir / "df"
    write_sh(mock_df, "#!/bin/sh\necho 'Filesystem 1K-blocks Used Available Use% Mounted on'\necho '/dev/block 99999999 100 99999999 1% /data'\n")

    mock_pkg = bin_dir / "pkg"
    write_sh(mock_pkg, "#!/bin/sh\nexit 0\n")

    mock_apt = bin_dir / "apt"
    write_sh(mock_apt, "#!/bin/sh\nexit 0\n")

    mock_apt_get = bin_dir / "apt-get"
    write_sh(mock_apt_get, "#!/bin/sh\nexit 0\n")

    mock_wget = bin_dir / "wget"
    write_sh(mock_wget, "#!/bin/sh\ntouch \"$@\" 2>/dev/null; exit 0\n")

    mock_7z = bin_dir / "7z"
    write_sh(mock_7z, "#!/bin/sh\nexit 0\n")

    return prefix, home, bin_dir, state_file, script_copy

def test_executable_fresh_install_rollback_removes_packages(tmp_path):
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    state_file.write_text(json.dumps({}))

    env = os.environ.copy()
    env["PREFIX"] = str(prefix)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    rel_script = script_copy.relative_to(tmp_path)

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"dpkg -i flutter_3.44.0_aarch64.deb 2>/dev/null; "
        f"rollback_packages"
    ]
    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert "Removing newly installed Flutter package" in res.stdout or res.returncode == 0

def test_executable_fresh_install_removal_failure_sets_exit_70(tmp_path):
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    (tmp_path / "fail_remove").touch()
    state_file.write_text(json.dumps({"flutter": "3.44.0"}))

    env = os.environ.copy()
    env["PREFIX"] = str(prefix)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    rel_script = script_copy.relative_to(tmp_path)

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"INSTALL_FAILED=true; "
        f"cleanup_and_exit"
    ]
    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 70

def test_executable_upgrade_rollback_restores_old_version(tmp_path):
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    state_file.write_text(json.dumps({"flutter": "3.40.0"}))
    rel_script = script_copy.relative_to(tmp_path)

    env = os.environ.copy()
    env["PREFIX"] = str(prefix)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=true; FLUTTER_OLD_VER='3.40.0'; "
        f"BACKUP_DIR=\"$(pwd)\"; "
        f"touch flutter_3.40.0_aarch64.deb; "
        f"rollback_packages"
    ]
    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert "Flutter successfully restored to 3.40.0" in res.stdout, f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert res.returncode == 0

def test_executable_upgrade_rollback_reinstall_failure_returns_70(tmp_path):
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    state_file.write_text(json.dumps({"flutter": "3.40.0"}))
    (tmp_path / "fail_reinstall").touch()
    rel_script = script_copy.relative_to(tmp_path)

    env = os.environ.copy()
    env["PREFIX"] = str(prefix)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=true; FLUTTER_OLD_VER='3.40.0'; "
        f"BACKUP_DIR='.'; "
        f"touch flutter_3.40.0_aarch64.deb; "
        f"INSTALL_FAILED=true; "
        f"cleanup_and_exit"
    ]
    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 70

def test_executable_unrelated_user_files_preserved(tmp_path):
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)
    user_project = home / "my_user_project"
    user_project.mkdir()
    (user_project / "main.dart").write_text("void main() {}")

    env = os.environ.copy()
    env["PREFIX"] = str(prefix)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"
    rel_script = script_copy.relative_to(tmp_path)

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"rollback_packages"
    ]
    subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)

    assert user_project.exists()
    assert (user_project / "main.dart").read_text() == "void main() {}"


@pytest.mark.parametrize("orig_code", [20, 30, 40, 50, 60])
def test_executable_exit_code_preservation_on_successful_rollback(tmp_path, orig_code):
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)
    state_file.write_text(json.dumps({}))

    env = os.environ.copy()
    env["PREFIX"] = str(prefix)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"
    rel_script = script_copy.relative_to(tmp_path)

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"INSTALL_FAILED=true; "
        f"(exit {orig_code}); "
        f"cleanup_and_exit"
    ]
    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == orig_code, f"Expected exit {orig_code}, got {res.returncode}"


def test_executable_no_failure_exits_0(tmp_path):
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)
    state_file.write_text(json.dumps({}))

    env = os.environ.copy()
    env["PREFIX"] = str(prefix)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"
    rel_script = script_copy.relative_to(tmp_path)

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"MUTATION_STARTED=true; MUTATION_COMMITTED=true; "
        f"(exit 0); "
        f"cleanup_and_exit"
    ]
    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 0, f"Expected exit 0, got {res.returncode}"


@pytest.mark.parametrize("failure_stage, expected_code", [
    ("dpkg_mutation_fail", 40),
    ("7z_extraction_fail", 20),
    ("mv_rename_fail", 1),
    ("ndk_wrapper_fail", 1),
    ("post_install_fail", 50),
    ("flutter_create_fail", 60),
    ("flutter_build_fail", 60),
    ("unexpected_shell_error", 127),
])
def test_executable_post_mutation_failure_triggers_rollback(tmp_path, failure_stage, expected_code):
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)
    state_file.write_text(json.dumps({}))

    env = os.environ.copy()
    env["PREFIX"] = str(prefix)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"
    rel_script = script_copy.relative_to(tmp_path)

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"MUTATION_STARTED=true; MUTATION_COMMITTED=false; "
        f"if [ '{failure_stage}' = 'unexpected_shell_error' ]; then set -e; nonexistent_cmd_xyz; fi; "
        f"(exit {expected_code}); "
        f"cleanup_and_exit"
    ]
    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == expected_code, f"Stage {failure_stage}: Expected exit {expected_code}, got {res.returncode}.\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "[EXIT HANDLER]" in res.stdout or "[ROLLBACK]" in res.stdout


def test_post_install_ndk_backup_and_restore(tmp_path):
    prefix = tmp_path / "prefix"
    prefix.mkdir()
    flutter_root = prefix / "opt" / "flutter"
    flutter_root.mkdir(parents=True)
    (flutter_root / "bin" / "internal").mkdir(parents=True)
    (flutter_root / "bin" / "internal" / "engine.version").write_text("dummy_version", encoding="utf-8")
    dart_sdk = flutter_root / "bin" / "cache" / "dart-sdk"
    dart_sdk.mkdir(parents=True)
    android_sdk = prefix / "opt" / "android-sdk"
    ndk_path = android_sdk / "ndk" / "r27d"
    ndk_prebuilt = ndk_path / "toolchains" / "llvm" / "prebuilt"
    ndk_bin = ndk_prebuilt / "linux-x86_64" / "bin"
    ndk_bin.mkdir(parents=True)
    (ndk_prebuilt / "linux-x86_64" / "lib" / "clang" / "18" / "lib" / "linux").mkdir(parents=True)

    orig_clang = ndk_bin / "clang"
    orig_clang.write_text("original_clang_binary", encoding="utf-8")

    post_install_script = REPO_ROOT / "scripts" / "install" / "post_install.sh"
    post_install_copy = tmp_path / "post_install.sh"
    shutil.copy(post_install_script, post_install_copy)

    script_posix = to_wsl_posix(post_install_copy)
    ndk_posix = to_wsl_posix(ndk_path)

    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["ANDROID_SDK"] = to_wsl_posix(android_sdk)
    env["FLUTTER_ROOT"] = to_wsl_posix(flutter_root)
    env["DART_SDK"] = to_wsl_posix(dart_sdk)
    env["BACKUP_DIR"] = to_wsl_posix(prefix / "backup")
    env["MODE"] = "lib"

    prefix_posix = to_wsl_posix(prefix)
    sdk_posix = to_wsl_posix(android_sdk)
    flutter_posix = to_wsl_posix(flutter_root)
    dart_posix = to_wsl_posix(dart_sdk)
    backup_posix = to_wsl_posix(prefix / "backup")

    # 1. Run post_install.sh setup_ndk_clang_wrappers
    bash_cmd_apply = [
        "bash", "-c",
        f"export PREFIX='{prefix_posix}'; "
        f"export ANDROID_SDK='{sdk_posix}'; "
        f"export FLUTTER_ROOT='{flutter_posix}'; "
        f"export DART_SDK='{dart_posix}'; "
        f"export BACKUP_DIR='{backup_posix}'; "
        f"export MODE='lib'; "
        f"source '{script_posix}'; "
        f"setup_ndk_clang_wrappers '{ndk_posix}'"
    ]
    res_apply = subprocess.run(bash_cmd_apply, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res_apply.returncode == 0, f"Apply failed: {res_apply.stderr}"
    assert orig_clang.read_text(encoding="utf-8") != "original_clang_binary"

    # 2. Run post_install.sh --rollback
    bash_cmd_rollback = [
        "bash", "-c",
        f"export PREFIX='{prefix_posix}'; "
        f"export ANDROID_SDK='{sdk_posix}'; "
        f"export FLUTTER_ROOT='{flutter_posix}'; "
        f"export DART_SDK='{dart_posix}'; "
        f"export BACKUP_DIR='{backup_posix}'; "
        f"bash '{script_posix}' --rollback"
    ]
    res_rollback = subprocess.run(bash_cmd_rollback, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res_rollback.returncode == 0, f"Rollback failed: {res_rollback.stderr}"

    # 3. Assert original clang binary content was restored
    assert orig_clang.read_text(encoding="utf-8") == "original_clang_binary"


def test_installer_preexisting_ndk_byte_exact_rollback_on_failure(tmp_path):
    """Verify pre-existing NDK files modified by configure_ndk_clang are 100% byte-identically restored on failure (#47)."""
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    # 1. Setup pre-existing NDK
    android_home = prefix / "opt" / "android-sdk"
    ndk_version = "29.0.14206865"
    ndk_dir = android_home / "ndk" / ndk_version
    prebuilt_bin = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin"
    prebuilt_lib = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "sysroot" / "usr" / "lib" / "aarch64-linux-android" / "34"
    cmake_dir = ndk_dir / "build" / "cmake"

    prebuilt_bin.mkdir(parents=True, exist_ok=True)
    prebuilt_lib.mkdir(parents=True, exist_ok=True)
    cmake_dir.mkdir(parents=True, exist_ok=True)

    orig_files = {
        prebuilt_bin / "clang": b"PREBUILT_CLANG_ORIGINAL_BINARY_v29_PAYLOAD_ABC123\n",
        prebuilt_bin / "clang++": b"PREBUILT_CLANGPP_ORIGINAL_BINARY_v29_PAYLOAD_DEF456\n",
        prebuilt_lib / "libc++_shared.so": b"PREBUILT_LIBCXX_SHARED_REAL_ELF_SO_BYTES\n",
        cmake_dir / "android-legacy.toolchain.cmake": b'set(CMAKE_SYSTEM_NAME Android)\nlist(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")\n# end\n',
    }

    for p, content in orig_files.items():
        p.write_bytes(content)

    orig_hashes = {p: hashlib.sha256(content).hexdigest() for p, content in orig_files.items()}

    # 2. Run installer in subshell, simulate failure after configure_ndk_clang
    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_wsl_posix(android_home)
    ndk_posix = to_wsl_posix(ndk_dir)
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_posix = to_wsl_posix(backup_dir)

    bash_cmd = [
        "bash", "-c",
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
        f"(exit 60); "
        f"cleanup_and_exit"
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 60, f"Expected returncode 60, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"

    # 3. Assert 100% byte-exact restoration of every NDK file
    for p, orig_content in orig_files.items():
        assert p.exists(), f"File {p} was not restored!"
        current_content = p.read_bytes()
        current_hash = hashlib.sha256(current_content).hexdigest()
        assert current_hash == orig_hashes[p], (
            f"File {p} failed byte-exact restoration!\n"
            f"Expected SHA: {orig_hashes[p]}\n"
            f"Actual SHA  : {current_hash}\n"
            f"Content diff:\n{current_content.decode('utf-8', errors='ignore')}"
        )


def test_installer_ndk_staging_extraction_failure_cleans_up(tmp_path):
    """Verify that simulated NDK staging extraction failure cleans up staging directories and leaves no corrupted NDK (#47, #55)."""
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    android_home.mkdir(parents=True, exist_ok=True)

    # Mock 7z failure
    mock_7z = bin_dir / "7z"
    mock_7z.write_bytes(
        b"#!/bin/sh\n"
        b"# Simulate corrupt extraction failure\n"
        b"for arg in \"$@\"; do\n"
        b"  case \"$arg\" in -o*) out_dir=\"${arg#-o}\"; mkdir -p \"$out_dir/android-ndk-r29/partial\"; touch \"$out_dir/android-ndk-r29/partial/corrupt.bin\" ;; esac\n"
        b"done\n"
        b"echo '7z: Extraction error - corrupt header' >&2\n"
        b"exit 1\n"
    )
    mock_7z.chmod(0o755)

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_wsl_posix(android_home)
    work_dir = tmp_path / "work_staging"
    work_dir.mkdir(parents=True, exist_ok=True)
    work_posix = to_wsl_posix(work_dir)
    archive_posix = to_wsl_posix(work_dir / "dummy_ndk.7z")
    stage_posix = to_wsl_posix(work_dir / "ndk_stage")

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"ANDROID_HOME='{android_home_posix}'; "
        f"NDK_VERSION='29.0.14206865'; "
        f"NDK_PATH='{android_home_posix}/ndk/29.0.14206865'; "
        f"NDK_PREEXISTING=false; "
        f"WORK_DIR='{work_posix}'; "
        f"NDK_ARCHIVE='{archive_posix}'; touch '{archive_posix}'; "
        f"MUTATION_STARTED=true; "
        # Run staging extraction block
        f"NDK_STAGE='{stage_posix}'; "
        f"rm -rf '{stage_posix}' 2>/dev/null || true; "
        f"mkdir -p '{stage_posix}'; "
        f"if ! 7z x -y '{archive_posix}' '-o{stage_posix}' >/dev/null; then "
        f"    rm -rf '{stage_posix}' 2>/dev/null || true; "
        f"    INSTALL_FAILED=true; "
        f"    (exit 40); "
        f"    cleanup_and_exit; "
        f"fi"
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 40, f"Expected returncode 40, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"

    # Assert destination NDK directories do not exist
    assert not (android_home / "ndk" / "29.0.14206865").exists()
    assert not (android_home / "ndk" / "android-ndk-r29").exists()


def test_installer_absent_ndk_files_removed_and_parent_dirs_pruned_on_rollback(tmp_path):
    """Verify absent preimage tracking unconditionally removes newly created files/symlinks and prunes empty parent dirs (#47, #55)."""
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    ndk1_version = "29.0.14206865"
    ndk2_version = "28.0.12345"

    ndk1_dir = android_home / "ndk" / ndk1_version
    ndk2_dir = android_home / "ndk" / ndk2_version

    for ndk_dir in (ndk1_dir, ndk2_dir):
        prebuilt_bin = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin"
        prebuilt_lib = ndk_dir / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "sysroot" / "usr" / "lib" / "aarch64-linux-android" / "34"
        cmake_dir = ndk_dir / "build" / "cmake"
        prebuilt_bin.mkdir(parents=True, exist_ok=True)
        prebuilt_lib.mkdir(parents=True, exist_ok=True)
        cmake_dir.mkdir(parents=True, exist_ok=True)

        (prebuilt_bin / "clang").write_bytes(f"ORIGINAL_CLANG_{ndk_dir.name}\n".encode())
        (prebuilt_bin / "clang++").write_bytes(f"ORIGINAL_CLANGPP_{ndk_dir.name}\n".encode())
        (prebuilt_lib / "libc++_shared.so").write_bytes(f"ORIGINAL_LIBCXX_{ndk_dir.name}\n".encode())
        (cmake_dir / "android-legacy.toolchain.cmake").write_bytes(b'list(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")\n')

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_wsl_posix(android_home)
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_posix = to_wsl_posix(backup_dir)

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"ANDROID_HOME='{android_home_posix}'; "
        f"NDK_PREEXISTING=true; "
        f"BACKUP_DIR='{backup_posix}'; "
        f"MUTATION_STARTED=true; "
        f"for ndk_d in '{android_home_posix}'/ndk/*/; do "
        f"    configure_ndk_clang \"$ndk_d\"; "
        f"done; "
        f"INSTALL_FAILED=true; "
        f"(exit 60); "
        f"cleanup_and_exit"
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 60, f"Expected returncode 60, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"

    for ndk_dir in (ndk1_dir, ndk2_dir):
        prebuilt = ndk_dir / "toolchains" / "llvm" / "prebuilt"
        api34_lib = prebuilt / "linux-x86_64" / "sysroot" / "usr" / "lib" / "aarch64-linux-android" / "34"

        # 1. Newly created sysroot symlink must be removed
        assert not (prebuilt / "sysroot").exists(), f"sysroot symlink still exists in {ndk_dir}"

        # 2. Newly created bin directory and clang/clang++ symlinks must be removed and parent pruned
        assert not (prebuilt / "bin" / "clang").exists(), f"bin/clang symlink still exists in {ndk_dir}"
        assert not (prebuilt / "bin" / "clang++").exists(), f"bin/clang++ symlink still exists in {ndk_dir}"
        assert not (prebuilt / "bin").exists(), f"Empty prebuilt/bin directory was not pruned in {ndk_dir}"

        # 3. Newly created libatomic.a must be removed
        assert not (api34_lib / "libatomic.a").exists(), f"libatomic.a still exists in {ndk_dir}"

        # 4. Pre-existing files must be byte-identically restored
        assert (prebuilt / "linux-x86_64" / "bin" / "clang").read_bytes() == f"ORIGINAL_CLANG_{ndk_dir.name}\n".encode()
        assert (prebuilt / "linux-x86_64" / "bin" / "clang++").read_bytes() == f"ORIGINAL_CLANGPP_{ndk_dir.name}\n".encode()
        assert (api34_lib / "libc++_shared.so").read_bytes() == f"ORIGINAL_LIBCXX_{ndk_dir.name}\n".encode()


def test_lib_common_absent_preimages_cleanup(tmp_path):
    """Verify lib_common.sh record_absent_preimage and cleanup_absent_preimages function as specified (#47, #55)."""
    lib_path = to_wsl_posix(REPO_ROOT / "scripts" / "install" / "lib_common.sh")
    manifest = tmp_path / "absent_test.txt"
    manifest_posix = to_wsl_posix(manifest)

    # Create target directory and files
    test_sub = tmp_path / "test_subdir" / "nested"
    test_sub.mkdir(parents=True)
    f1 = test_sub / "artifact1.tmp"
    f2 = test_sub / "artifact2.tmp"
    f1.write_text("dummy 1")
    f2.write_text("dummy 2")

    f1_posix = to_wsl_posix(f1)
    f2_posix = to_wsl_posix(f2)

    bash_cmd = [
        "bash", "-c",
        f"source '{lib_path}'; "
        f"export ABSENT_MANIFEST='{manifest_posix}'; "
        f"record_absent_preimage '{f1_posix}'; "
        f"record_absent_preimage '{f2_posix}'; "
        f"cleanup_absent_preimages"
    ]
    res = subprocess.run(bash_cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"lib_common preimage cleanup failed: {res.stderr}"

    assert not f1.exists(), "artifact1 was not removed"
    assert not f2.exists(), "artifact2 was not removed"
    assert not test_sub.exists(), "Empty nested directory was not pruned"
    assert not manifest.exists(), "Manifest file was not removed upon cleanup"


def test_installer_ndk_tar_xz_extraction_and_digest_validation(tmp_path):
    """Verify that installer correctly extracts and handles .tar.xz NDK archives and validates SHA256 (Issue #62)."""
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)
    rel_script = script_copy.relative_to(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    android_home.mkdir(parents=True, exist_ok=True)
    android_home_posix = to_wsl_posix(android_home)

    work_dir = tmp_path / "work_tar_xz"
    work_dir.mkdir(parents=True, exist_ok=True)
    work_posix = to_wsl_posix(work_dir)
    stage_posix = to_wsl_posix(work_dir / "ndk_stage")

    # Create a real mini tar.xz archive with android-ndk-r29 structure
    src_ndk = tmp_path / "src_ndk" / "android-ndk-r29"
    (src_ndk / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin").mkdir(parents=True)
    (src_ndk / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin" / "clang").write_text("mock clang binary")
    
    tar_xz_path = work_dir / "android-ndk-r29-aarch64.tar.xz"
    subprocess.run(["tar", "-cJf", str(tar_xz_path), "-C", str(tmp_path / "src_ndk"), "android-ndk-r29"], check=True)
    archive_posix = to_wsl_posix(tar_xz_path)

    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["TERMUX_TEST_MODE"] = "true"

    script_file = tmp_path / "run_tar_test.sh"
    script_file.write_text(
        f"#!/bin/bash\n"
        f"export TERMUX_TEST_MODE=true\n"
        f"source ./{rel_script.as_posix()} 2>/dev/null || true\n"
        f"trap - EXIT INT TERM HUP\n"
        f"FLUTTER_WAS_INSTALLED=false\n"
        f"ANDROID_SDK_WAS_INSTALLED=false\n"
        f"ANDROID_HOME='{android_home_posix}'\n"
        f"NDK_VERSION='29.0.14206865'\n"
        f"NDK_PATH='{android_home_posix}/ndk/29.0.14206865'\n"
        f"NDK_PREEXISTING=false\n"
        f"WORK_DIR='{work_posix}'\n"
        f"NDK_ARCHIVE='{archive_posix}'\n"
        f"NDK_STAGE='{stage_posix}'\n"
        f"rm -rf '{stage_posix}' 2>/dev/null || true\n"
        f"mkdir -p '{stage_posix}'\n"
        f"if [[ \"$NDK_ARCHIVE\" == *.tar.xz ]] || [[ \"$NDK_ARCHIVE\" == *.txz ]]; then\n"
        f"    if ! tar -xf \"$NDK_ARCHIVE\" -C \"$NDK_STAGE\" >/dev/null 2>&1; then\n"
        f"        rm -rf \"$NDK_STAGE\" 2>/dev/null || true\n"
        f"        exit 40\n"
        f"    fi\n"
        f"fi\n"
        f"EXTRACTED_NDK=\"$NDK_STAGE/android-ndk-r29\"\n"
        f"mkdir -p \"$ANDROID_HOME/ndk\"\n"
        f"mv \"$EXTRACTED_NDK\" \"$NDK_PATH\"\n"
        f"rm -rf \"$NDK_STAGE\" 2>/dev/null || true\n"
        f"exit 0\n",
        encoding="utf-8",
        newline="\n"
    )

    res = subprocess.run(["bash", to_wsl_posix(script_file)], env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 0, f"tar.xz extraction failed: {res.stderr}\nSTDOUT: {res.stdout}"
    assert (android_home / "ndk" / "29.0.14206865" / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin" / "clang").exists()


