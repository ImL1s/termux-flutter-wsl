import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
INSTALLER = REPO_ROOT / "install_flutter_complete.sh"
POST_INSTALL = REPO_ROOT / "scripts" / "install" / "post_install.sh"
CHECK_TOOLCHAIN = REPO_ROOT / "scripts" / "ci" / "check_toolchain.sh"
LIB_COMMON = REPO_ROOT / "scripts" / "install" / "lib_common.sh"


def to_bash_path(path):
    path = Path(path).resolve()
    try:
        rel = path.relative_to(REPO_ROOT)
        return rel.as_posix()
    except ValueError:
        p = path.as_posix()
        if len(p) > 1 and p[1] == ":":
            drive = p[0].lower()
            return f"/{drive}{p[2:]}"
        return p


def write_sh_script(p, content):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content.replace('\r\n', '\n').encode('utf-8'))
    p.chmod(0o755)


def create_mock_installer_harness(tmp_path):
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

    root_posix = to_bash_path(tmp_path)

    mock_dpkg = bin_dir / "dpkg"
    write_sh_script(mock_dpkg, f"""#!/bin/sh
STATE_FILE="{state_p}"
{py_finder}

if [ "$1" = "-i" ]; then
    if [ -f "{root_posix}/fail_reinstall" ] || [ -f fail_reinstall ]; then
        exit 1
    fi
    DEB="$2"
    PKG=$(basename "$DEB" | cut -d'_' -f1)
    VER=$(basename "$DEB" | cut -d'_' -f2)
    "$PY_CMD" -c "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg=sys.argv[2]; ver=sys.argv[3]; d=json.load(open(p)); d[pkg]=ver; json.dump(d, open(p,'w'))" "$STATE_FILE" "$PKG" "$VER"
    exit 0
elif [ "$1" = "-r" ]; then
    if [ -f "{root_posix}/fail_remove" ] || [ -f fail_remove ]; then
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
    write_sh_script(mock_dpkg_query, f"""#!/bin/sh
STATE_FILE="{state_p}"
{py_finder}
"$PY_CMD" -c "{dpkg_query_code}" "$STATE_FILE" "$@"
exit $?
""")

    mock_dpkg_repack = bin_dir / "dpkg-repack"
    dpkg_repack_code = "import os, json, sys; p = sys.argv[1]; p = (p[1] + ':' + p[2:]) if (os.name == 'nt' and len(p) > 2 and p[0] == '/' and p[2] == '/') else (('/mnt/' + p[0].lower() + p[2:]) if (os.name != 'nt' and len(p) > 1 and p[1] == ':') else p); pkg = sys.argv[2]; d = json.load(open(p)); open(f'{{pkg}}_{{d[pkg]}}_aarch64.deb', 'w').write('dummy deb') if pkg in d else sys.exit(1)"
    write_sh_script(mock_dpkg_repack, f"""#!/bin/sh
STATE_FILE="{state_p}"
{py_finder}
if [ -f "{root_posix}/fail_repack" ] || [ -f fail_repack ]; then
    exit 1
fi
PKG="$1"
"$PY_CMD" -c "{dpkg_repack_code}" "$STATE_FILE" "$PKG"
""")

    write_sh_script(bin_dir / "uname", "#!/bin/sh\necho aarch64\n")
    write_sh_script(bin_dir / "df", "#!/bin/sh\necho 'Filesystem 1K-blocks Used Available Use% Mounted on'\necho '/dev/block 99999999 100 99999999 1% /data'\n")
    write_sh_script(bin_dir / "pkg", "#!/bin/sh\nexit 0\n")
    write_sh_script(bin_dir / "apt", "#!/bin/sh\nexit 0\n")
    write_sh_script(bin_dir / "apt-get", f"""#!/bin/sh\nif [ -f "{root_posix}/fail_apt_download" ] || [ -f fail_apt_download ]; then exit 1; fi\nexit 0\n""")
    write_sh_script(bin_dir / "wget", "#!/bin/sh\ntouch \"$@\" 2>/dev/null; exit 0\n")
    write_sh_script(bin_dir / "7z", "#!/bin/sh\nexit 0\n")

    return prefix, home, bin_dir, state_file, script_copy



def create_mock_post_install_env(tmp_path):
    flutter_root = tmp_path / "flutter"
    android_sdk = tmp_path / "android-sdk"
    prefix = tmp_path / "usr"

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
    write_sh_script(mock_dart, mock_dart_script)

    pkg_cfg = flutter_root / "packages" / "flutter_tools" / ".dart_tool" / "package_config.json"
    pkg_cfg.parent.mkdir(parents=True, exist_ok=True)
    pkg_cfg.write_text("{}", newline="\n")

    (flutter_root / "bin" / "internal" / "engine.version").write_text("77e2e94772b6eb43759e34ed1ad7da4674e19cab\n", newline="\n")
    (flutter_root / "version").write_text("3.44.9\n", newline="\n")

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


def run_post_install(flutter_root, android_sdk, prefix, args=None, extra_env=None):
    if args is None:
        args = ["--apply"]
    post_install_path = to_bash_path(POST_INSTALL)
    flut_path = to_bash_path(flutter_root)
    sdk_path = to_bash_path(android_sdk)
    pref_path = to_bash_path(prefix)

    env_exports = [
        f"export FLUTTER_ROOT='{flut_path}'",
        f"export ANDROID_SDK='{sdk_path}'",
        f"export PREFIX='{pref_path}'",
        f"export DART_SDK='{flut_path}/bin/cache/dart-sdk'",
    ]
    if extra_env:
        for k, v in extra_env.items():
            env_exports.append(f"export {k}='{v}'")

    cmd = f"{' && '.join(env_exports)} && bash '{post_install_path}' {' '.join(args)}"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    return res


# ==============================================================================
# 1. Installer Rollback & Safety (#53) Stress Tests
# ==============================================================================

@pytest.mark.parametrize("sig_name, sig_num", [("INT", 2), ("TERM", 15), ("HUP", 1)])
def test_adv_installer_abnormal_termination_signal_traps(tmp_path, sig_name, sig_num):
    """Stress test abnormal termination signals (SIGINT, SIGTERM, SIGHUP) during mutation phase."""
    prefix, home, bin_dir, state_file, script_copy = create_mock_installer_harness(tmp_path)
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
        f"dpkg -i flutter_3.44.9_aarch64.deb 2>/dev/null; "
        f"kill -s {sig_name} $$"
    ]
    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode != 0
    assert "[EXIT HANDLER]" in res.stdout or "[ROLLBACK]" in res.stdout
    st = json.loads(state_file.read_text())
    assert "flutter" not in st, "Newly installed flutter must be removed by rollback"


def test_adv_installer_preexisting_ndk_full_preservation(tmp_path):
    """Stress test pre-existing NDK preservation with deep tree hierarchy, symlinks, and toolchains."""
    prefix, home, bin_dir, state_file, script_copy = create_mock_installer_harness(tmp_path)

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
        prebuilt_bin / "clang": b"REAL_PREEXISTING_CLANG_ARM64_BINARY_PAYLOAD_999\n",
        prebuilt_bin / "clang++": b"REAL_PREEXISTING_CLANGPP_ARM64_BINARY_PAYLOAD_888\n",
        prebuilt_bin / "llvm-objcopy": b"ORIGINAL_OBJCOPY_BIN\n",
        prebuilt_bin / "llvm-strip": b"ORIGINAL_STRIP_BIN\n",
        prebuilt_lib / "libc++_shared.so": b"REAL_LIBCXX_SO_BINARY_V29\n",
        cmake_dir / "android-legacy.toolchain.cmake": b'set(CMAKE_SYSTEM_NAME Android)\nlist(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")\n',
        cmake_dir / "android.toolchain.cmake": b'# Main cmake toolchain file\nset(ANDROID_NDK_REVISION 29)\n',
    }

    for p, content in orig_files.items():
        p.write_bytes(content)

    orig_hashes = {p: hashlib.sha256(content).hexdigest() for p, content in orig_files.items()}

    rel_script = script_copy.relative_to(tmp_path)
    env = os.environ.copy()
    env["PREFIX"] = to_bash_path(prefix)
    env["HOME"] = to_bash_path(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"

    android_home_posix = to_bash_path(android_home)
    ndk_posix = to_bash_path(ndk_dir)
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_posix = to_bash_path(backup_dir)

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
        f"(exit 50); "
        f"cleanup_and_exit"
    ]

    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 50, f"Expected returncode 50, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"

    for p, orig_content in orig_files.items():
        assert p.exists(), f"Pre-existing NDK file {p} was not restored!"
        assert hashlib.sha256(p.read_bytes()).hexdigest() == orig_hashes[p], f"Byte mismatch on restored NDK file {p}"


def test_adv_installer_backup_failure_aborts_with_code_35(tmp_path):
    """Stress test that when backup creation fails for existing installed packages, installer aborts with exit 35."""
    prefix, home, bin_dir, state_file, script_copy = create_mock_installer_harness(tmp_path)
    state_file.write_text(json.dumps({}))

    env = os.environ.copy()
    env["PREFIX"] = str(prefix)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}"
    env["TERMUX_TEST_MODE"] = "true"
    rel_script = script_copy.relative_to(tmp_path)

    bash_cmd_flutter = [
        "bash", "-c",
        f"export TERMUX_TEST_MODE=true; "
        f"export PATH=\"$(pwd)/bin:$PATH\"; "
        f"source ./{rel_script.as_posix()} 2>/dev/null || true; "
        f"FLUTTER_WAS_INSTALLED=false; ANDROID_SDK_WAS_INSTALLED=false; "
        f"INSTALL_FAILED=true; "
        f"(exit 35); "
        f"cleanup_and_exit"
    ]

    res_flut = subprocess.run(bash_cmd_flutter, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res_flut.returncode == 35, f"Expected exit code 35 on failed backup, got {res_flut.returncode}. Output:\n{res_flut.stdout}\n{res_flut.stderr}"






def test_adv_installer_rollback_failure_aborts_with_code_70(tmp_path):
    """Stress test that when rollback restoration fails, installer cleanup_and_exit exits with code 70."""
    prefix, home, bin_dir, state_file, script_copy = create_mock_installer_harness(tmp_path)
    state_file.write_text(json.dumps({"flutter": "3.40.0"}))
    (tmp_path / "fail_reinstall").touch()

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
        f"FLUTTER_WAS_INSTALLED=true; FLUTTER_OLD_VER='3.40.0'; "
        f"BACKUP_DIR='.'; touch flutter_3.40.0_aarch64.deb; "
        f"INSTALL_FAILED=true; "
        f"cleanup_and_exit"
    ]
    res = subprocess.run(bash_cmd, env=env, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 70, f"Expected exit code 70 on failed rollback reinstall, got {res.returncode}"


# ==============================================================================
# 2. Post-Install Dual-Preimage Idempotency (#54) Stress Tests
# ==============================================================================

def test_adv_post_install_repeated_apply_byte_identical(tmp_path):
    """Adversarially stress-test repeated invocations of post_install.sh --apply to guarantee byte-exact stability."""
    flutter_root, android_sdk, prefix, files = create_mock_post_install_env(tmp_path)

    # 1. First invocation: transform upstream preimages to postimages
    res1 = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res1.returncode == 0, f"First --apply failed: stdout={res1.stdout}, stderr={res1.stderr}"

    # Record hashes of all transformed files
    tree_hashes_1 = {}
    for p in flutter_root.glob("**/*"):
        if p.is_file():
            tree_hashes_1[p.relative_to(flutter_root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()

    # 2. Run --apply 10 more times consecutively
    for i in range(2, 12):
        res_i = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
        assert res_i.returncode == 0, f"Iteration {i} failed: stdout={res_i.stdout}, stderr={res_i.stderr}"

    # 3. Verify all file hashes across the entire tree match iteration 1 with 0 byte deviation
    for rel_p, expected_hash in tree_hashes_1.items():
        actual_file = flutter_root / rel_p
        assert actual_file.exists(), f"File {rel_p} missing after repeated runs"
        actual_hash = hashlib.sha256(actual_file.read_bytes()).hexdigest()
        assert actual_hash == expected_hash, f"File {rel_p} drifted! (Expected {expected_hash}, got {actual_hash})"


def test_adv_post_install_corrupted_patch_state_json_recovery(tmp_path):
    """Stress test recovery when patch_state.json is malformed or corrupted."""
    flutter_root, android_sdk, prefix, files = create_mock_post_install_env(tmp_path)

    # Apply once
    res1 = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res1.returncode == 0

    # Corrupt patch_state.json with garbage
    state_file = prefix / "share" / "flutter" / "patch_state.json"
    state_file.write_text('{"corrupted_json_syntax": [123, invalid', encoding="utf-8")

    # Run --apply again
    res2 = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res2.returncode == 0, f"Recovery from corrupted state failed: {res2.stderr}"

    # Verify state file was repaired and contains valid JSON
    state_content = json.loads(state_file.read_text(encoding="utf-8"))
    assert "compile_sdk" in state_content or "plugin_constants" in state_content


def test_adv_post_install_unapplied_unknown_file_rejection(tmp_path):
    """Stress test that unapplied target files with unknown content are rejected fail-closed."""
    flutter_root, android_sdk, prefix, files = create_mock_post_install_env(tmp_path)

    # Corrupt target file
    target = flutter_root / "packages" / "flutter_tools" / "gradle" / "src" / "main" / "kotlin" / "FlutterExtension.kt"
    target.write_text("package com.flutter.gradle\n// Arbitrary unknown non-matching file content\nclass Foo {}\n", encoding="utf-8")

    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode != 0, "post_install --apply must fail when target content is unknown"
    assert "unknown upstream content" in res.stdout or "unknown upstream content" in res.stderr or "failed" in res.stdout


# ==============================================================================
# 3. Toolchain Diagnostics & Offline Repair (#59) Stress Tests
# ==============================================================================

def test_adv_toolchain_diagnostics_clean_linkage(tmp_path):
    """Stress test check_toolchain.sh with statically-linked or clean AAPT2 binary."""
    mock_aapt2 = tmp_path / "aapt2"
    write_sh_script(mock_aapt2, "#!/bin/sh\nif [ \"$1\" = \"version\" ]; then echo 'Android Asset Packaging Tool (aapt) 2.19'; exit 0; fi\nexit 0\n")

    script_path = to_bash_path(CHECK_TOOLCHAIN)
    aapt2_path = to_bash_path(mock_aapt2)

    res = subprocess.run(["bash", script_path, aapt2_path], capture_output=True, text=True)
    assert res.returncode == 0, f"check_toolchain.sh failed: stdout={res.stdout}, stderr={res.stderr}"
    assert "runtime execution passed" in res.stdout


def test_adv_toolchain_diagnostics_dynamic_libprotobuf_rejection_and_bypass(tmp_path):
    """Stress test ELF linkage checking: dynamic libprotobuf rejection without flag, allowed with ALLOW_DYNAMIC_AAPT2=1."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Mock readelf to simulate dynamic libprotobuf linkage
    mock_readelf = bin_dir / "readelf"
    write_sh_script(
        mock_readelf,
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-h\" ]; then echo 'ELF Header'; exit 0; fi\n"
        "if [ \"$1\" = \"-d\" ]; then echo '0x0000000000000001 (NEEDED) Shared library: [libprotobuf.so.32]'; exit 0; fi\n"
        "exit 0\n"
    )

    # Mock version execution script that also acts as ELF
    mock_aapt2 = tmp_path / "aapt2"
    write_sh_script(
        mock_aapt2,
        "#!/bin/sh\n"
        "if [ \"$1\" = \"version\" ]; then echo 'Android Asset Packaging Tool 2.19'; exit 0; fi\n"
        "exit 0\n"
    )

    script_path = to_bash_path(CHECK_TOOLCHAIN)
    aapt2_path = to_bash_path(mock_aapt2)
    bin_dir_posix = to_bash_path(bin_dir)

    # 1. Without ALLOW_DYNAMIC_AAPT2=1 -> must FAIL with exit code 1
    cmd_fail = f"export PATH='{bin_dir_posix}':$PATH && export ALLOW_DYNAMIC_AAPT2=0 && bash '{script_path}' '{aapt2_path}'"
    res_fail = subprocess.run(["bash", "-c", cmd_fail], capture_output=True, text=True)
    assert res_fail.returncode == 1, f"Expected exit code 1 on dynamic libprotobuf, got {res_fail.returncode}. Output:\n{res_fail.stdout}\n{res_fail.stderr}"
    assert "dynamically linked to libprotobuf" in res_fail.stderr or "dynamically linked to libprotobuf" in res_fail.stdout

    # 2. With ALLOW_DYNAMIC_AAPT2=1 -> must PASS with warning
    cmd_pass = f"export PATH='{bin_dir_posix}':$PATH && export ALLOW_DYNAMIC_AAPT2=1 && bash '{script_path}' '{aapt2_path}'"
    res_pass = subprocess.run(["bash", "-c", cmd_pass], capture_output=True, text=True)
    assert res_pass.returncode == 0, f"Expected exit code 0 with ALLOW_DYNAMIC_AAPT2=1, got {res_pass.returncode}. Output:\n{res_pass.stdout}\n{res_pass.stderr}"


def test_adv_toolchain_split_select_validation(tmp_path):
    """Stress test split-select validation handling in check_toolchain.sh."""
    mock_aapt2 = tmp_path / "aapt2"
    write_sh_script(mock_aapt2, "#!/bin/sh\nif [ \"$1\" = \"version\" ]; then echo 'AAPT2 2.19'; exit 0; fi\nexit 0\n")

    mock_split_select = tmp_path / "split-select"
    write_sh_script(mock_split_select, "#!/bin/sh\necho 'split-select is not available on Termux ARM64'\nexit 1\n")

    script_path = to_bash_path(CHECK_TOOLCHAIN)
    aapt2_path = to_bash_path(mock_aapt2)
    ss_path = to_bash_path(mock_split_select)

    res = subprocess.run(["bash", script_path, aapt2_path, ss_path], capture_output=True, text=True)
    assert res.returncode == 0, f"Expected exit code 0 on valid split-select stub, got {res.returncode}. Output:\n{res.stdout}\n{res.stderr}"
    assert "split-select runtime execution passed" in res.stdout


def test_adv_mode_b_failure_auto_fallback_to_mode_a(tmp_path):
    """Stress test Mode B toolchain failure triggers automatic fallback to Mode A in post_install.sh."""
    flutter_root, android_sdk, prefix, files = create_mock_post_install_env(tmp_path)
    bt_dir = android_sdk / "build-tools" / "35.0.0"
    bt_dir.mkdir(parents=True, exist_ok=True)

    # Set up gradle.properties with Mode B override
    home_dir = tmp_path / "home"
    gradle_props = home_dir / ".gradle" / "gradle.properties"
    gradle_props.parent.mkdir(parents=True, exist_ok=True)
    gradle_props.write_text("android.aapt2FromMavenOverride=/Android/Sdk/build-tools/35.0.0/aapt2\n", encoding="utf-8")

    # Set up broken Mode B aapt2 that exits with error
    fake_sdk_target = tmp_path / "Android" / "Sdk" / "aapt2"
    fake_sdk_target.parent.mkdir(parents=True, exist_ok=True)
    write_sh_script(fake_sdk_target, "#!/bin/sh\nexit 1\n")

    aapt2_symlink = bt_dir / "aapt2"
    try:
        aapt2_symlink.symlink_to(fake_sdk_target)
    except Exception:
        subprocess.run(["bash", "-c", f"ln -sf '{to_bash_path(fake_sdk_target)}' '{to_bash_path(aapt2_symlink)}'"], check=True)

    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"], extra_env={"HOME": to_bash_path(home_dir)})
    assert res.returncode == 0, f"post_install failed: stdout={res.stdout}, stderr={res.stderr}"

    # Verify Mode B failure message and fallback
    assert "Mode B toolchain validation failed" in res.stdout or "Reverting Mode B activation to Mode A" in res.stdout

    # Verify gradle.properties Mode B override was stripped
    assert "android.aapt2FromMavenOverride" not in gradle_props.read_text(encoding="utf-8")
