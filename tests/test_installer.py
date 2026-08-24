import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
LIB_COMMON = REPO_ROOT / "scripts" / "install" / "lib_common.sh"
INSTALLER = REPO_ROOT / "install_flutter_complete.sh"


from conftest import to_bash_path


def test_verify_sha256_success(tmp_path):
    test_file = tmp_path / "sample.txt"
    content = b"hello world\n"
    test_file.write_bytes(content)
    expected_sha = hashlib.sha256(content).hexdigest()

    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(test_file)
    cmd = f"source '{lib_path}' && verify_sha256 '{file_path}' '{expected_sha}'"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Failed: stdout={res.stdout}, stderr={res.stderr}"
    assert test_file.exists()


def test_verify_sha256_mismatch_removes_file(tmp_path):
    test_file = tmp_path / "corrupt.txt"
    test_file.write_bytes(b"corrupted content\n")
    wrong_sha = "0000000000000000000000000000000000000000000000000000000000000000"

    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(test_file)
    cmd = f"source '{lib_path}' && verify_sha256 '{file_path}' '{wrong_sha}'"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode != 0
    assert not test_file.exists(), "File should be removed on sha256 mismatch"


def test_verify_sha256_missing_hasher_fails(tmp_path):
    test_file = tmp_path / "sample.txt"
    content = b"hello world\n"
    test_file.write_bytes(content)
    expected_sha = hashlib.sha256(content).hexdigest()

    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(test_file)
    mock_cmd = 'command() { if [ "$2" = "sha256sum" ] || [ "$2" = "shasum" ]; then return 1; fi; builtin command "$@"; };'
    cmd = f"{mock_cmd} source '{lib_path}' && verify_sha256 '{file_path}' '{expected_sha}'"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode != 0
    assert "Neither sha256sum nor shasum is available" in res.stdout or "Neither sha256sum nor shasum" in res.stdout


def test_installer_syntax():
    res = subprocess.run(["bash", "-n", to_bash_path(INSTALLER)], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"bash -n failed: {res.stderr}"


def test_lib_common_syntax():
    res = subprocess.run(["bash", "-n", to_bash_path(LIB_COMMON)], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"bash -n failed: {res.stderr}"


def test_installer_zero_unsafe_tmp_references():
    """Verify install_flutter_complete.sh contains zero raw /tmp hardcodings (#55)."""
    content = INSTALLER.read_text(encoding="utf-8")
    assert "/tmp/MANIFEST.MF" not in content, "/tmp/MANIFEST.MF must use $WORK_DIR"
    assert "/tmp/build1.log" not in content, "/tmp/build1.log must use $WORK_DIR"
    assert "/tmp/build2.log" not in content, "/tmp/build2.log must use $WORK_DIR"
    assert "tee /tmp/" not in content
    assert "> /tmp/" not in content


def test_installer_zero_home_spills():
    """Verify install_flutter_complete.sh never downloads to $HOME or runs rm *.deb in $HOME (#55)."""
    content = INSTALLER.read_text(encoding="utf-8")
    assert "$HOME/dart-sdk.zip" not in content, "Dart SDK zip download must use $WORK_DIR, not $HOME"
    assert "cd $HOME\n    apt download" not in content
    # Verify no rm -f *.deb directly inside $HOME scope
    assert not re.search(r"cd\s+\$HOME[\s\S]*?rm\s+-f\s+\*\.deb", content), "cd $HOME followed by wildcard rm *.deb leaks/damages $HOME"


def test_installer_trap_signal_registration():
    """Verify install_flutter_complete.sh traps EXIT, INT, TERM, HUP (#55)."""
    content = INSTALLER.read_text(encoding="utf-8")
    assert "trap cleanup_and_exit EXIT INT TERM HUP" in content, "Exit handler must trap EXIT INT TERM HUP"


# ==============================================================================
# Runtime Signal Trap & Workspace Safety Tests (#55)
# ==============================================================================

def create_installer_runtime_harness(tmp_path):
    """Create executable mock harness for testing installer runtime signal and exit traps."""
    prefix = tmp_path / "prefix"
    prefix.mkdir(parents=True, exist_ok=True)
    (prefix / "bin").mkdir(parents=True, exist_ok=True)
    (prefix / "opt").mkdir(parents=True, exist_ok=True)
    (prefix / "etc" / "profile.d").mkdir(parents=True, exist_ok=True)

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "data" / "com.termux").mkdir(parents=True, exist_ok=True)

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "dpkg_state.json"
    state_file.write_text(json.dumps({}))

    script_copy = tmp_path / "install_flutter_complete.sh"
    shutil.copy(INSTALLER, script_copy)
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
    write_sh(
        mock_dpkg,
        f"""#!/bin/sh
STATE_FILE="{state_p}"
{py_finder}
if [ "$1" = "-i" ]; then
    DEB="$2"
    PKG=$(basename "$DEB" | cut -d'_' -f1)
    VER=$(basename "$DEB" | cut -d'_' -f2)
    "$PY_CMD" -c "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg=sys.argv[2]; ver=sys.argv[3]; d=json.load(open(p)); d[pkg]=ver; json.dump(d, open(p,'w'))" "$STATE_FILE" "$PKG" "$VER"
    exit 0
elif [ "$1" = "-r" ]; then
    PKG="$2"
    "$PY_CMD" -c "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg=sys.argv[2]; d=json.load(open(p)); d.pop(pkg, None); json.dump(d, open(p,'w'))" "$STATE_FILE" "$PKG"
    exit 0
elif [ "$1" = "-l" ]; then
    PKG="$2"
    "$PY_CMD" -c "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg=sys.argv[2]; d=json.load(open(p)); print('ii ' + pkg if pkg in d else '')" "$STATE_FILE" "$PKG"
    exit 0
fi
exit 0
""",
    )

    mock_dpkg_query = bin_dir / "dpkg-query"
    dpkg_query_code = "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg = sys.argv[-1]; fmt = sys.argv[-2] if len(sys.argv) > 3 else ''; d = json.load(open(p)); (sys.stdout.write('install ok installed ' + d[pkg] + '\\n') if ('Status' in fmt and 'Version' in fmt) else (sys.stdout.write('install ok installed\\n') if 'Status' in fmt else (sys.stdout.write(d[pkg] + '\\n') if 'Version' in fmt else sys.stdout.write(pkg + '\\t' + d[pkg] + '\\n')))) if pkg in d else sys.exit(1)"
    write_sh(
        mock_dpkg_query,
        f"""#!/bin/sh
STATE_FILE="{state_p}"
{py_finder}
"$PY_CMD" -c "{dpkg_query_code}" "$STATE_FILE" "$@"
exit $?
""",
    )

    return prefix, home, bin_dir, state_file, script_copy


@pytest.mark.parametrize("sig_name", ["INT", "TERM", "HUP"])
def test_installer_runtime_signal_trap_cleans_up_and_rolls_back(tmp_path, sig_name):
    """Verify runtime signal interruption during uncommitted mutation triggers rollback, purges $WORK_DIR, and exits non-zero (#55)."""
    prefix, home, bin_dir, state_file, script_copy = create_installer_runtime_harness(tmp_path)
    work_dir = tmp_path / f"work_sig_{sig_name}"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "temp_payload.bin").write_bytes(b"ephemeral data")

    env = os.environ.copy()
    env["PREFIX"] = to_bash_path(prefix)
    env["HOME"] = to_bash_path(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    rel_script = script_copy.relative_to(tmp_path)
    work_posix = to_bash_path(work_dir)

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"WORK_DIR='{work_posix}'; "
        f"MUTATION_STARTED=true; MUTATION_COMMITTED=false; "
        f"dpkg -i flutter_3.44.9_aarch64.deb; "
        f"kill -{sig_name} $$"
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)

    # 1. Must exit with non-zero status code
    assert res.returncode != 0, f"Signal {sig_name} must exit non-zero, got {res.returncode}"
    # 2. $WORK_DIR must be purged completely
    assert not work_dir.exists(), f"Staging $WORK_DIR '{work_dir}' must be removed on signal {sig_name}"
    # 3. Mutated package must be rolled back
    state = json.loads(state_file.read_text())
    assert "flutter" not in state, f"Package 'flutter' must be rolled back on signal {sig_name}"


def test_installer_runtime_signal_trap_pre_mutation_safety(tmp_path):
    """Verify runtime signal interruption prior to mutation does not trigger spurious rollback and cleans $WORK_DIR (#55)."""
    prefix, home, bin_dir, state_file, script_copy = create_installer_runtime_harness(tmp_path)
    work_dir = tmp_path / "work_pre_mutation"
    work_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PREFIX"] = to_bash_path(prefix)
    env["HOME"] = to_bash_path(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    rel_script = script_copy.relative_to(tmp_path)
    work_posix = to_bash_path(work_dir)

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"WORK_DIR='{work_posix}'; "
        f"MUTATION_STARTED=false; MUTATION_COMMITTED=false; "
        f"kill -INT $$"
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert not work_dir.exists(), "WORK_DIR must be removed even when signal arrives pre-mutation"


def test_installer_runtime_normal_exit_with_commit_exits_zero(tmp_path):
    """Verify normal completion with MUTATION_COMMITTED=true exits 0 without rolling back (#55)."""
    prefix, home, bin_dir, state_file, script_copy = create_installer_runtime_harness(tmp_path)
    work_dir = tmp_path / "work_commit"
    work_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PREFIX"] = to_bash_path(prefix)
    env["HOME"] = to_bash_path(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    rel_script = script_copy.relative_to(tmp_path)
    work_posix = to_bash_path(work_dir)

    bash_cmd = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"WORK_DIR='{work_posix}'; "
        f"MUTATION_STARTED=true; MUTATION_COMMITTED=true; "
        f"dpkg -i flutter_3.44.9_aarch64.deb; "
        f"(exit 0); "
        f"cleanup_and_exit"
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 0, f"Committed installer must exit 0, got {res.returncode}"
    assert not work_dir.exists(), "WORK_DIR must be cleaned up on normal exit"
    state = json.loads(state_file.read_text())
    assert "flutter" in state, "Committed package must NOT be rolled back"


def test_gitignore_covers_bak_and_config_files():
    """Verify that .gitignore properly excludes all .bak, backup, and state files (#55)."""
    gitignore_path = REPO_ROOT / ".gitignore"
    assert gitignore_path.is_file()
    gitignore_content = gitignore_path.read_text(encoding="utf-8")

    assert "*.bak" in gitignore_content
    assert ".termux_project_config.json" in gitignore_content
    assert "patch_state.json" in gitignore_content
    assert "dpkg_state.json" in gitignore_content

    test_paths = [
        "android/gradle.properties.bak",
        "android/app/build.gradle.bak",
        "android/app/build.gradle.kts.bak",
        "packages/flutter_tools/gradle/src/main/kotlin/FlutterExtension.kt.bak",
        "some/nested/dir/foo.bak",
        "some_file.bak.1",
        "patch.orig",
        "conflict.rej",
        ".termux_project_config.json",
        "android/.termux_project_config.json",
        "my_project/.termux_project_config.json",
        "patch_state.json",
        ".gclient_sync.receipt.json",
        "dpkg_state.json",
        "scratch/test.py",
        "temp_work/file.txt",
        "tmp_work/file.txt",
        "data.tmp",
        "artifact.temp",
    ]

    patterns = [line.strip() for line in gitignore_content.splitlines() if line.strip() and not line.startswith("#")]

    for tp in test_paths:
        matched = False
        filename = Path(tp).name
        for pat in patterns:
            if pat.endswith("/"):
                dir_pat = pat.rstrip("/")
                if tp.startswith(dir_pat + "/") or f"/{dir_pat}/" in tp:
                    matched = True
                    break
            if fnmatch.fnmatch(tp, pat) or fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(tp, f"**/{pat}"):
                matched = True
                break
        assert matched, f"Path '{tp}' is not matched by any rule in .gitignore!"


def test_git_tracking_preserves_tracked_files():
    """Verify essential project files are NOT accidentally ignored by .gitignore (#55)."""
    essential = [
        "build.py",
        "package.yaml",
        "package.py",
        "sysroot.py",
        "utils.py",
        "install_flutter_complete.sh",
        "scripts/install/lib_common.sh",
        "scripts/install/post_install.sh",
        "scripts/install/flutter_project_config.sh",
        "scripts/ci/check_repo.py",
        "tests/test_installer.py",
        "tests/test_installer_rollback.py",
    ]
    for p in essential:
        res = subprocess.run(["git", "check-ignore", "-q", p], cwd=str(REPO_ROOT))
        assert res.returncode != 0, f"Essential file '{p}' was mistakenly ignored by .gitignore!"


def test_profile_script_safe_under_set_u_and_exports_java_home(tmp_path):
    """Verify generated profile.d/flutter.sh runs under set -euo pipefail without unbound variable crash."""
    import yaml
    with open(REPO_ROOT / "package.yaml", "r", encoding="utf-8") as f:
        pkg_data = yaml.safe_load(f)
    profile_src = pkg_data["resource"]["profile"]["source"]

    import string
    profile_rendered = string.Template(profile_src).safe_substitute(version="5a2a6a42cce67f965cf540fcecf616faca624aa1")

    profile_file = tmp_path / "flutter.sh"
    with open(profile_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(profile_rendered)

    # Simulate fake jvm directory
    fake_prefix = tmp_path / "usr"
    fake_jvm = fake_prefix / "lib" / "jvm" / "java-21-openjdk"
    fake_jvm.mkdir(parents=True)

    profile_bash_path = to_bash_path(profile_file)
    fake_prefix_bash_path = to_bash_path(fake_prefix)

    test_script = f"""set -euo pipefail
export PREFIX="{fake_prefix_bash_path}"
unset JAVA_HOME
source "{profile_bash_path}"
echo "JAVA_HOME=$JAVA_HOME"
"""
    res = subprocess.run(["bash"], input=test_script.encode("utf-8"), capture_output=True)
    assert res.returncode == 0, f"Failed under set -euo pipefail: stderr={res.stderr.decode('utf-8', errors='ignore')}"
    stdout = res.stdout.decode("utf-8", errors="ignore")
    assert "JAVA_HOME=" in stdout
    assert "java-21-openjdk" in stdout


def test_installer_has_openjdk17_and_java_home_configured():
    """Verify install_flutter_complete.sh installs openjdk-17 and configures JAVA_HOME dynamically."""
    content = INSTALLER.read_text(encoding="utf-8")
    assert "openjdk-17" in content, "install_flutter_complete.sh must include openjdk-17 to satisfy android-sdk dependency"
    assert "export JAVA_HOME=" in content, "install_flutter_complete.sh must export JAVA_HOME"
    assert "java-*-openjdk" in content, "install_flutter_complete.sh must resolve java-*-openjdk dynamically"


def test_all_installers_guard_profile_script_sourcing():
    """Verify install scripts and bashrc_fix guard profile.d/flutter.sh sourcing to prevent missing file errors."""
    scripts = [
        REPO_ROOT / "install_flutter_complete.sh",
        REPO_ROOT / "scripts" / "install" / "install_termux_flutter.sh",
        REPO_ROOT / "scripts" / "install" / "install.sh",
        REPO_ROOT / "scripts" / "install" / "post_install.sh",
        REPO_ROOT / "scripts" / "fix" / "bashrc_fix.sh",
        REPO_ROOT / "scripts" / "test" / "gh_e2e_test.sh",
    ]
    for s in scripts:
        content = s.read_text(encoding="utf-8")
        # Ensure no unguarded raw source $PREFIX/etc/profile.d/flutter.sh execution
        lines = [line.strip() for line in content.splitlines()]
        for idx, line in enumerate(lines, 1):
            if line.startswith("source \"$PREFIX/etc/profile.d/flutter.sh\"") or line.startswith("source $PREFIX/etc/profile.d/flutter.sh"):
                assert False, f"{s.name}:{idx} has unguarded profile source: '{line}'. Should be guarded with [ -f ... ]."
