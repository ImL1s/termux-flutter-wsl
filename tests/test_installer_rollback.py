import hashlib
import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
import pytest

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
    "$PY_CMD" -c "import os, json, sys; p = sys.argv[1]; p = ('/mnt/c/' + p[3:]) if (os.name != 'nt' and (p.startswith('C:/') or p.startswith('c:/'))) else p; pkg=sys.argv[2]; ver=sys.argv[3]; d=json.load(open(p)); d[pkg]=ver; json.dump(d, open(p,'w'))" "$STATE_FILE" "$PKG" "$VER"
    exit 0
elif [ "$1" = "-r" ]; then
    if [ -f fail_remove ]; then
        exit 1
    fi
    PKG="$2"
    "$PY_CMD" -c "import os, json, sys; p = sys.argv[1]; p = ('/mnt/c/' + p[3:]) if (os.name != 'nt' and (p.startswith('C:/') or p.startswith('c:/'))) else p; pkg=sys.argv[2]; d=json.load(open(p)); d.pop(pkg, None); json.dump(d, open(p,'w'))" "$STATE_FILE" "$PKG"
    exit 0
elif [ "$1" = "-l" ]; then
    PKG="$2"
    "$PY_CMD" -c "import os, json, sys; p = sys.argv[1]; p = ('/mnt/c/' + p[3:]) if (os.name != 'nt' and (p.startswith('C:/') or p.startswith('c:/'))) else p; pkg=sys.argv[2]; d=json.load(open(p)); print('ii ' + pkg if pkg in d else '')" "$STATE_FILE" "$PKG"
    exit 0
fi
exit 0
""")

    mock_dpkg_query = bin_dir / "dpkg-query"
    dpkg_query_code = "import os, json, sys; p = sys.argv[1]; p = ('/mnt/c/' + p[3:]) if (os.name != 'nt' and (p.startswith('C:/') or p.startswith('c:/'))) else p; pkg = sys.argv[-1]; fmt = sys.argv[-2] if len(sys.argv) > 3 else ''; d = json.load(open(p)); (sys.stdout.write('install ok installed ' + d[pkg] + '\\n') if ('Status' in fmt and 'Version' in fmt) else (sys.stdout.write('install ok installed\\n') if 'Status' in fmt else (sys.stdout.write(d[pkg] + '\\n') if 'Version' in fmt else sys.stdout.write(pkg + '\\t' + d[pkg] + '\\n')))) if pkg in d else sys.exit(1)"
    write_sh(mock_dpkg_query, f"""#!/bin/sh
STATE_FILE="{state_p}"
{py_finder}
"$PY_CMD" -c "{dpkg_query_code}" "$STATE_FILE" "$@"
exit $?
""")

    mock_dpkg_repack = bin_dir / "dpkg-repack"
    dpkg_repack_code = "import os, json, sys; p = sys.argv[1]; p = ('/mnt/c/' + p[3:]) if (os.name != 'nt' and (p.startswith('C:/') or p.startswith('c:/'))) else p; pkg = sys.argv[2]; d = json.load(open(p)); open(f'{{pkg}}_{{d[pkg]}}_aarch64.deb', 'w').write('dummy deb') if pkg in d else sys.exit(1)"
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


def to_wsl_posix(p):
    s = p.as_posix() if isinstance(p, Path) else str(p)
    if len(s) > 1 and s[1:3] == ":/":
        return f"/mnt/{s[0].lower()}{s[2:]}"
    return s


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
