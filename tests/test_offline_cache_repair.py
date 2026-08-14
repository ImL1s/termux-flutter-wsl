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

    # Create directory hierarchy
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

    # Dummy dds snapshot so downloads are skipped
    (flutter_root / "bin" / "cache" / "dart-sdk" / "bin" / "snapshots" / "dds_aot.dart.snapshot").write_text("snapshot", newline="\n")

    # Mock dart compiler binary that creates valid snapshots
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

    # Entry point for flutter_tools
    entry_point = flutter_root / "packages" / "flutter_tools" / "bin" / "flutter_tools.dart"
    entry_point.write_text("void main() {}", newline="\n")

    # Package config
    pkg_cfg = flutter_root / "packages" / "flutter_tools" / ".dart_tool" / "package_config.json"
    pkg_cfg.parent.mkdir(parents=True, exist_ok=True)
    pkg_cfg.write_text("{}", newline="\n")

    # Pubspec yaml and lock
    pubspec_yaml = flutter_root / "packages" / "flutter_tools" / "pubspec.yaml"
    pubspec_yaml.write_text("name: flutter_tools\n", newline="\n")
    pubspec_lock = flutter_root / "packages" / "flutter_tools" / "pubspec.lock"
    pubspec_lock.write_text("# lockfile\n", newline="\n")

    (flutter_root / "bin" / "internal" / "engine.version").write_text("77e2e94772b6eb43759e34ed1ad7da4674e19cab", newline="\n")
    (flutter_root / "version").write_text("3.44.0", newline="\n")

    # Preimage files for post_install.sh patches
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


def test_correct_revision_stamp_format(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode == 0, f"post_install failed: stdout={res.stdout}, stderr={res.stderr}"

    stamp = flutter_root / "bin" / "cache" / "flutter_tools.stamp"
    snapshot = flutter_root / "bin" / "cache" / "flutter_tools.snapshot"

    assert stamp.exists(), "flutter_tools.stamp must exist"
    assert snapshot.exists(), "flutter_tools.snapshot must exist"
    assert snapshot.stat().st_size > 0, "flutter_tools.snapshot must not be empty"

    engine_ver = (flutter_root / "bin" / "internal" / "engine.version").read_text().strip()
    expected_stamp = f"{engine_ver}:"
    assert stamp.read_text() == expected_stamp, f"Stamp must equal '{expected_stamp}', got '{stamp.read_text()}'"


def test_missing_compiler_fails_closed(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    # Remove mock dart compiler
    mock_dart = flutter_root / "bin" / "cache" / "dart-sdk" / "bin" / "dart"
    mock_dart.unlink()

    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode != 0, "post_install must fail closed when compiler is missing"
    assert "Dart compiler missing" in res.stderr or "Dart compiler missing" in res.stdout

    stamp = flutter_root / "bin" / "cache" / "flutter_tools.stamp"
    snapshot = flutter_root / "bin" / "cache" / "flutter_tools.snapshot"
    assert not stamp.exists(), "Stamp must NOT exist when compiler fails"
    assert not snapshot.exists(), "Snapshot must NOT exist when compiler fails"


def test_compile_failure_fails_closed(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    # Mock dart compiler that exits 1
    mock_dart = flutter_root / "bin" / "cache" / "dart-sdk" / "bin" / "dart"
    mock_dart.write_text("#!/bin/sh\nexit 1\n", newline="\n")

    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode != 0, "post_install must fail closed when dart compilation fails"
    assert "Failed to compile flutter_tools.snapshot" in res.stderr or "Failed to compile" in res.stdout

    stamp = flutter_root / "bin" / "cache" / "flutter_tools.stamp"
    snapshot = flutter_root / "bin" / "cache" / "flutter_tools.snapshot"
    assert not stamp.exists(), "Stamp must NOT exist when compilation fails"
    assert not snapshot.exists(), "Snapshot must NOT exist when compilation fails"


def test_stale_or_malformed_stamp_overwritten_correctly(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    stamp = flutter_root / "bin" / "cache" / "flutter_tools.stamp"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text("INVALID_STALE_STAMP_KEY", newline="\n")

    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode == 0

    engine_ver = (flutter_root / "bin" / "internal" / "engine.version").read_text().strip()
    expected_stamp = f"{engine_ver}:"
    assert stamp.read_text() == expected_stamp, f"Stale stamp must be overwritten with '{expected_stamp}'"


def test_rerun_idempotency(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    res1 = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res1.returncode == 0

    stamp = flutter_root / "bin" / "cache" / "flutter_tools.stamp"
    snapshot = flutter_root / "bin" / "cache" / "flutter_tools.snapshot"
    stamp_content_1 = stamp.read_text()
    snapshot_bytes_1 = snapshot.read_bytes()

    res2 = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res2.returncode == 0

    assert stamp.read_text() == stamp_content_1
    assert snapshot.read_bytes() == snapshot_bytes_1


def test_hermetic_shared_sh_cache_decision(tmp_path):
    flutter_root, android_sdk, prefix, files = create_mock_env(tmp_path)
    res = run_post_install(flutter_root, android_sdk, prefix, ["--apply"])
    assert res.returncode == 0

    snapshot = flutter_root / "bin" / "cache" / "flutter_tools.snapshot"
    stamp = flutter_root / "bin" / "cache" / "flutter_tools.stamp"
    pubspec_yaml = flutter_root / "packages" / "flutter_tools" / "pubspec.yaml"
    pubspec_lock = flutter_root / "packages" / "flutter_tools" / "pubspec.lock"

    # Evaluate shared.sh's exact cache validity condition in bash:
    # if [[ ! -f "$SNAPSHOT_PATH" || ! -s "$STAMP_PATH" || "$(< "$STAMP_PATH")" != "$compilekey" || "$FLUTTER_TOOLS_DIR/pubspec.yaml" -nt "$FLUTTER_TOOLS_DIR/pubspec.lock" ]]; then
    #   echo "STALE"
    # else
    #   echo "VALID"
    # fi
    engine_ver = (flutter_root / "bin" / "internal" / "engine.version").read_text().strip()
    compile_key = f"{engine_ver}:"

    # Hermetically verify all 4 shared.sh cache validity conditions (shared.sh lines 133-136):
    # 1. snapshot exists
    # 2. stamp exists and is non-empty
    # 3. stamp content matches compilation key (${REVISION}:)
    # 4. pubspec.yaml is NOT newer than pubspec.lock
    snapshot_invalid = not snapshot.is_file()
    stamp_invalid = not stamp.is_file() or stamp.stat().st_size == 0
    stamp_val = stamp.read_text()
    stamp_mismatch = stamp_val != compile_key
    yaml_newer_than_lock = pubspec_yaml.stat().st_mtime > pubspec_lock.stat().st_mtime

    assert not snapshot_invalid, "shared.sh condition 1 failed: flutter_tools.snapshot is missing"
    assert not stamp_invalid, "shared.sh condition 2 failed: flutter_tools.stamp is missing or 0 bytes"
    assert not stamp_mismatch, f"shared.sh condition 3 failed: stamp content '{stamp_val}' != expected key '{compile_key}'"
    assert not yaml_newer_than_lock, f"shared.sh condition 4 failed: pubspec.yaml ({pubspec_yaml.stat().st_mtime}) is newer than pubspec.lock ({pubspec_lock.stat().st_mtime})"
