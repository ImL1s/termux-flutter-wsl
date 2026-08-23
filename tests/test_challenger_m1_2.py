import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = (REPO_ROOT / "install_flutter_complete.sh").resolve()
LIB_COMMON = REPO_ROOT / "scripts" / "install" / "lib_common.sh"


def to_wsl_posix(p):
    s = p.as_posix() if isinstance(p, Path) else str(p)
    if len(s) > 1 and s[1:3] == ":/":
        return f"/{s[0].lower()}{s[2:]}"
    return s


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


# ==============================================================================
# 1. NDK 7z Extraction Failure Modes & Staging Debris Tests
# ==============================================================================

def test_adversarial_ndk_corrupt_archive_leaves_zero_debris(tmp_path):
    """Verify that corrupt 7z archive failure cleans up ndk_stage and creates zero debris in $ANDROID_HOME/ndk."""
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    android_home.mkdir(parents=True, exist_ok=True)
    ndk_parent = android_home / "ndk"
    ndk_parent.mkdir(parents=True, exist_ok=True)

    # Corrupt 7z mock that writes corrupt partial chunks before failing
    mock_7z = bin_dir / "7z"
    mock_7z.write_bytes(
        b"#!/bin/sh\n"
        b"for arg in \"$@\"; do\n"
        b"  case \"$arg\" in -o*) out_dir=\"${arg#-o}\"; mkdir -p \"$out_dir/android-ndk-r29/toolchains\"; touch \"$out_dir/android-ndk-r29/toolchains/corrupt_llvm.bin\" ;; esac\n"
        b"done\n"
        b"echo 'ERROR: Corrupted archive header CRC mismatch' >&2\n"
        b"exit 2\n"
    )
    mock_7z.chmod(0o755)

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_wsl_posix(android_home)
    work_dir = tmp_path / "staging_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    work_posix = to_wsl_posix(work_dir)
    archive_posix = to_wsl_posix(work_dir / "corrupted_ndk.7z")
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
        f"NDK_STAGE='{stage_posix}'; "
        f"rm -rf '{stage_posix}' 2>/dev/null || true; "
        f"mkdir -p '{stage_posix}'; "
        f"if ! 7z x -y '{archive_posix}' '-o{stage_posix}' >/dev/null; then "
        f"    echo 'NDK extraction failed'; "
        f"    rm -rf '{stage_posix}' 2>/dev/null || true; "
        f"    INSTALL_FAILED=true; "
        f"    (exit 40); "
        f"    cleanup_and_exit; "
        f"fi"
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 40, f"Expected returncode 40, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"

    # Verify staging is cleaned up
    assert not (work_dir / "ndk_stage").exists(), "Staging directory ndk_stage must be removed"
    # Verify android_home/ndk has ZERO dirty debris
    assert list(ndk_parent.iterdir()) == [], f"Expected $ANDROID_HOME/ndk to be completely clean, found: {list(ndk_parent.iterdir())}"


def test_adversarial_ndk_abort_mid_unpacking_cleans_up(tmp_path):
    """Simulate a mid-unpacking abort (e.g. 7z killed or partial uncompressed tree) and verify no dirty files in target."""
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    android_home.mkdir(parents=True, exist_ok=True)
    ndk_parent = android_home / "ndk"
    ndk_parent.mkdir(parents=True, exist_ok=True)

    # 7z mock that creates a deeply nested directory tree with files and aborts with code 137 (SIGKILL)
    mock_7z = bin_dir / "7z"
    mock_7z.write_bytes(
        b"#!/bin/sh\n"
        b"for arg in \"$@\"; do\n"
        b"  case \"$arg\" in -o*) out_dir=\"${arg#-o}\"; "
        b"    mkdir -p \"$out_dir/android-ndk-r29/platforms/android-34/arch-arm64\"; "
        b"    mkdir -p \"$out_dir/android-ndk-r29/toolchains/llvm/prebuilt/linux-x86_64/bin\"; "
        b"    touch \"$out_dir/android-ndk-r29/toolchains/llvm/prebuilt/linux-x86_64/bin/partial_clang\"; "
        b"    echo 'halfway written data' > \"$out_dir/android-ndk-r29/platforms/android-34/arch-arm64/libandroid.so\"; "
        b"  ;; esac\n"
        b"done\n"
        b"exit 137\n"
    )
    mock_7z.chmod(0o755)

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_wsl_posix(android_home)
    work_dir = tmp_path / "work_mid_abort"
    work_dir.mkdir(parents=True, exist_ok=True)
    work_posix = to_wsl_posix(work_dir)
    archive_posix = to_wsl_posix(work_dir / "ndk.7z")
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
    assert res.returncode == 40
    assert not (work_dir / "ndk_stage").exists()
    assert list(ndk_parent.iterdir()) == []


def test_adversarial_ndk_extraction_failure_with_preexisting_ndk_preserves_intact(tmp_path):
    """Verify that if NDK extraction fails when another pre-existing NDK is installed, the pre-existing NDK is untouched."""
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    android_home = prefix / "opt" / "android-sdk"
    preexisting_ndk = android_home / "ndk" / "26.1.10909125"
    preexisting_ndk.mkdir(parents=True, exist_ok=True)
    orig_file = preexisting_ndk / "source.properties"
    orig_file.write_text("Pkg.Desc = Android NDK\nPkg.Revision = 26.1.10909125\n")
    orig_hash = hashlib.sha256(orig_file.read_bytes()).hexdigest()

    mock_7z = bin_dir / "7z"
    mock_7z.write_bytes(b"#!/bin/sh\nexit 1\n")
    mock_7z.chmod(0o755)

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_wsl_posix(android_home)
    work_dir = tmp_path / "work_preexist"
    work_dir.mkdir(parents=True, exist_ok=True)
    work_posix = to_wsl_posix(work_dir)
    archive_posix = to_wsl_posix(work_dir / "ndk.7z")
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
    assert res.returncode == 40
    # Pre-existing NDK must be 100% intact
    assert preexisting_ndk.exists()
    assert hashlib.sha256(orig_file.read_bytes()).hexdigest() == orig_hash
    # New NDK path must not exist
    assert not (android_home / "ndk" / "29.0.14206865").exists()


# ==============================================================================
# 2. Signal Interruptions (SIGINT, SIGTERM, SIGHUP, ERR) & Trap Cleanup Tests
# ==============================================================================

@pytest.mark.parametrize("sig_name, sig_num", [
    ("INT", 2),
    ("TERM", 15),
    ("HUP", 1),
])
def test_adversarial_signal_interruption_cleans_up_staging_and_rolls_back(tmp_path, sig_name, sig_num):
    """Verify that when installer receives SIGINT, SIGTERM, or SIGHUP during mutation, cleanup trap fires, rolls back, and removes $WORK_DIR."""
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    state_file.write_text(json.dumps({}))

    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    work_dir = tmp_path / f"work_sig_{sig_name}"
    work_dir.mkdir(parents=True, exist_ok=True)
    work_posix = to_wsl_posix(work_dir)
    staging_file = work_dir / "staging_leak_check.tmp"
    staging_file.write_text("staging content")

    rel_script = script_copy.relative_to(tmp_path)

    # In bash, triggering kill -SIG $$ inside subshell sends signal to the bash process
    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"WORK_DIR='{work_posix}'; "
        f"MUTATION_STARTED=true; MUTATION_COMMITTED=false; "
        f"dpkg -i flutter_3.44.0_aarch64.deb 2>/dev/null; "
        f"kill -{sig_name} $$"
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    # Bash signal exit code is typically 128 + sig_num, or rollback handler exit code
    assert res.returncode != 0
    # Assert WORK_DIR was completely purged by the trap
    assert not work_dir.exists(), f"WORK_DIR {work_dir} must be removed on signal {sig_name}"
    # Assert rollback occurred: dpkg state should not contain flutter
    current_state = json.loads(state_file.read_text())
    assert "flutter" not in current_state, f"Flutter package must be rolled back on signal {sig_name}"


def test_adversarial_errexit_during_mutation_triggers_rollback(tmp_path):
    """Verify that an unexpected command error during mutation (set -e) triggers the cleanup_and_exit trap and rolls back."""
    prefix, home, bin_dir, state_file, script_copy = create_executable_state_machine_harness(tmp_path)

    state_file.write_text(json.dumps({}))

    env = os.environ.copy()
    env["PREFIX"] = to_wsl_posix(prefix)
    env["HOME"] = to_wsl_posix(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    work_dir = tmp_path / "work_errexit"
    work_dir.mkdir(parents=True, exist_ok=True)
    work_posix = to_wsl_posix(work_dir)

    rel_script = script_copy.relative_to(tmp_path)

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"WORK_DIR='{work_posix}'; "
        f"MUTATION_STARTED=true; MUTATION_COMMITTED=false; "
        f"dpkg -i flutter_3.44.0_aarch64.deb 2>/dev/null; "
        f"set -e; "
        f"false"
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode != 0
    assert not work_dir.exists(), "WORK_DIR must be removed after errexit"
    current_state = json.loads(state_file.read_text())
    assert "flutter" not in current_state, "State must be rolled back after errexit"


# ==============================================================================
# 3. .gitignore Adversarial Coverage & Untracked File Hygiene Tests
# ==============================================================================

def test_adversarial_gitignore_untracked_hygiene():
    """Verify that creating arbitrary temporary test artifacts in the repository is 100% ignored by git and does NOT pollute git status."""
    gitignore_path = REPO_ROOT / ".gitignore"
    assert gitignore_path.exists()

    test_artifacts = [
        REPO_ROOT / ".termux_project_config.json",
        REPO_ROOT / "patch_state.json",
        REPO_ROOT / "dpkg_state.json",
        REPO_ROOT / ".gclient_sync.receipt.json",
        REPO_ROOT / "temp_build.receipt.json",
        REPO_ROOT / "install_flutter_complete.sh.bak",
        REPO_ROOT / "build.py.bak.1",
        REPO_ROOT / "patch.orig",
        REPO_ROOT / "patch.rej",
        REPO_ROOT / "data.tmp",
        REPO_ROOT / "artifact.temp",
        REPO_ROOT / "scratch" / "test_scratch.py",
        REPO_ROOT / "temp_test_dir" / "test_file.txt",
        REPO_ROOT / "tmp_work_dir" / "dummy.bin",
        REPO_ROOT / ".coverage",
        REPO_ROOT / ".coverage.12345",
    ]

    created_paths = []
    created_dirs = []

    try:
        for p in test_artifacts:
            parent = p.parent
            if not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)
                created_dirs.append(parent)
            p.write_text("dummy test content for gitignore verification\n", encoding="utf-8")
            created_paths.append(p)

        # Run git check-ignore on all created paths
        for p in created_paths:
            rel = p.relative_to(REPO_ROOT).as_posix()
            res = subprocess.run(["git", "check-ignore", "-q", rel], cwd=str(REPO_ROOT))
            assert res.returncode == 0, f"Artifact '{rel}' MUST be ignored by .gitignore, but git did not ignore it!"

        # Run git status --porcelain to ensure zero untracked files are reported
        status_res = subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert status_res.returncode == 0
        untracked_lines = [
            line for line in status_res.stdout.splitlines()
            if line.startswith("??") and any(p.name in line for p in created_paths)
        ]
        assert untracked_lines == [], f"Found untracked test files in git status: {untracked_lines}"

    finally:
        # Clean up all created test files and temporary directories
        for p in created_paths:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        for d in created_dirs:
            if d.exists():
                try:
                    shutil.rmtree(d)
                except Exception:
                    pass


def test_adversarial_gitignore_preserves_vital_project_files():
    """Verify that no essential project source code, configuration, or documentation files are ignored."""
    vital_files = [
        "build.py",
        "package.py",
        "sysroot.py",
        "utils.py",
        "build.toml",
        "package.yaml",
        "install_flutter_complete.sh",
        "scripts/install/lib_common.sh",
        "scripts/install/post_install.sh",
        "scripts/install/flutter_project_config.sh",
        "scripts/ci/check_repo.py",
        "scripts/ci/check_version_drift.py",
        "tests/test_installer.py",
        "tests/test_installer_rollback.py",
        "tests/test_challenger_m1_2.py",
    ]

    for rel in vital_files:
        res = subprocess.run(["git", "check-ignore", "-q", rel], cwd=str(REPO_ROOT))
        assert res.returncode != 0, f"Vital project file '{rel}' is accidentally ignored by .gitignore!"
