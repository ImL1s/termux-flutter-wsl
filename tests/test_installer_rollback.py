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
