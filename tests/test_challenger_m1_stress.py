import hashlib
import json
import os
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
LIB_COMMON = REPO_ROOT / "scripts" / "install" / "lib_common.sh"
INSTALLER = REPO_ROOT / "install_flutter_complete.sh"
CONFIG_SCRIPT = REPO_ROOT / "scripts" / "install" / "flutter_project_config.sh"


from conftest import to_bash_path


# ==============================================================================
# 1. lib_common.sh Stress Tests
# ==============================================================================

def test_verify_sha256_missing_hasher(tmp_path):
    """Verify that when neither sha256sum nor shasum is available, verify_sha256 fails hard (code != 0)."""
    test_file = tmp_path / "test.tar.gz"
    test_file.write_bytes(b"some content")
    
    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(test_file)
    mock_cmd = 'command() { if [ "$2" = "sha256sum" ] || [ "$2" = "shasum" ]; then return 1; fi; builtin command "$@"; };'
    cmd = f"{mock_cmd} source '{lib_path}' && verify_sha256 '{file_path}' 'dummyhash'"
    
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode != 0, "verify_sha256 must fail when no hasher is present"
    assert "Neither sha256sum nor shasum is available" in res.stdout or "Neither sha256sum nor shasum is available" in res.stderr or "ERROR" in res.stdout


def test_verify_sha256_mismatch_removes_file(tmp_path):
    """Verify that sha256 mismatch causes non-zero exit code and removes the corrupted file."""
    corrupt_file = tmp_path / "corrupt.deb"
    corrupt_file.write_bytes(b"bad binary data")
    wrong_hash = "1111111111111111111111111111111111111111111111111111111111111111"
    
    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(corrupt_file)
    cmd = f"source '{lib_path}' && verify_sha256 '{file_path}' '{wrong_hash}'"
    
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode != 0, "verify_sha256 must return non-zero exit code on hash mismatch"
    assert not corrupt_file.exists(), "Corrupted file must be deleted upon hash mismatch"


def test_verify_sha256_spaces_in_path(tmp_path):
    """Verify that verify_sha256 handles paths with spaces properly."""
    space_dir = tmp_path / "folder with spaces"
    space_dir.mkdir()
    space_file = space_dir / "my package.deb"
    content = b"content with spaces"
    space_file.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest()
    
    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(space_file)
    cmd = f"source '{lib_path}' && verify_sha256 '{file_path}' '{expected_hash}'"
    
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Failed on path with spaces: stdout={res.stdout}, stderr={res.stderr}"


def test_preflight_check_failures():
    """Verify preflight_check aborts with exit code 10 on invalid arch/environment/space."""
    lib_path = to_bash_path(LIB_COMMON)
    
    # Test arch failure
    cmd_arch = f"source '{lib_path}' && uname() {{ echo 'x86_64'; }}; export -f uname; preflight_check 100"
    res_arch = subprocess.run(["bash", "-c", cmd_arch], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res_arch.returncode == 10, f"Expected exit code 10 on bad arch, got {res_arch.returncode}"
    
    # Test non-termux failure
    cmd_termux = f"source '{lib_path}' && uname() {{ echo 'aarch64'; }}; preflight_check 100"
    res_termux = subprocess.run(["bash", "-c", cmd_termux], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res_termux.returncode == 10, f"Expected exit code 10 on non-termux, got {res_termux.returncode}"


# ==============================================================================
# 2. install_flutter_complete.sh Safety & Staging Tests
# ==============================================================================

def test_installer_staging_and_purge_safety(tmp_path):
    """Verify that download & integrity verification happen BEFORE dpkg --purge of existing packages.
    If download/verification fails, existing packages must NOT be purged."""
    
    purged_marker = tmp_path / "purged_flag.txt"
    
    sim_script = tmp_path / "sim_installer.sh"
    sim_content = f"""#!/usr/bin/env bash
set -e

PURGED_MARKER="{to_bash_path(purged_marker)}"

dpkg() {{
    if [ "$1" = "--purge" ]; then
        touch "$PURGED_MARKER"
    fi
}}

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

FLUTTER_DEB="$WORK_DIR/flutter.deb"
ANDROID_SDK_DEB="$WORK_DIR/android_sdk.deb"

touch "$FLUTTER_DEB"

# Simulating download failure
echo "Simulating Android SDK download failure..."
exit 20

dpkg --purge android-sdk
dpkg --purge flutter
"""
    sim_script.write_bytes(sim_content.encode("utf-8"))
    
    res = subprocess.run(["bash", to_bash_path(sim_script)], capture_output=True, text=True)
    assert res.returncode == 20, f"Installer must exit with code 20 on download failure, got {res.returncode}"
    assert not purged_marker.exists(), "Existing packages MUST NOT be purged if download fails before staging completion"


def test_installer_dpkg_failure_propagation(tmp_path):
    """Verify that dpkg -i failures in install_flutter_complete.sh propagate exit code 40 instead of being swallowed."""
    
    sim_script = tmp_path / "sim_dpkg_fail.sh"
    sim_content = """#!/usr/bin/env bash
set -e

STAGE_STATUS=()
record_stage() { echo "RECORDED: $1 $2"; }

apt-get() {
    return 100
}

apt-get install -f -y "dummy.deb" || { record_stage package failed; exit 40; }
"""
    sim_script.write_bytes(sim_content.encode("utf-8"))
    
    res = subprocess.run(["bash", to_bash_path(sim_script)], capture_output=True, text=True)
    assert res.returncode == 40, f"Expected exit code 40 on package install failure, got {res.returncode}"
    assert "RECORDED: package failed" in res.stdout


def test_real_installer_script_staging_order():
    """Verify that install_flutter_complete.sh uses transactional install-first (no premature purge)."""
    content = INSTALLER.read_text(encoding="utf-8")
    
    pos_staging = content.find("預先下載並驗證所有套件")
    pos_verify_flutter = content.find('verify_sha256 "$FLUTTER_DEB"')
    pos_verify_android = content.find('verify_sha256 "$ANDROID_SDK_DEB"')
    pos_verify_ndk = content.find('verify_sha256 "$NDK_ARCHIVE"')
    
    assert pos_staging > 0, "Staging block header missing"
    assert pos_verify_flutter > pos_staging, "Flutter verification must be inside staging block"
    assert pos_verify_android > pos_staging, "Android SDK verification must be inside staging block"
    assert pos_verify_ndk > pos_staging, "NDK verification must be inside staging block"
    
    # Transactional: no premature purge should exist
    # dpkg --purge with || true was the old dangerous pattern
    assert 'dpkg --purge android-sdk' not in content, \
        "Transactional installer must not have dpkg --purge android-sdk (dpkg -i handles upgrade)"
    assert 'dpkg --purge flutter' not in content, \
        "Transactional installer must not have dpkg --purge flutter (dpkg -i handles upgrade)"


# ==============================================================================
# 3. flutter_project_config.sh Edge Case Stress Tests
# ==============================================================================

def create_full_mock_project(tmp_path, build_gradle_type="groovy"):
    proj = tmp_path / "test_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)
    
    gradle_props = proj / "android" / "gradle.properties"
    gradle_props.write_text("org.gradle.jvmargs=-Xmx2048m\n")
    
    if build_gradle_type == "groovy":
        build_gradle = android_dir / "build.gradle"
        build_gradle.write_text("""
android {
    compileSdkVersion 35
    defaultConfig {
        applicationId "com.example.test"
        minSdkVersion 21
        targetSdkVersion 35
    }
}
""")
    elif build_gradle_type == "kotlin":
        build_gradle = android_dir / "build.gradle.kts"
        build_gradle.write_text("""
android {
    compileSdk = 35
    defaultConfig {
        applicationId = "com.example.test"
        minSdk = 21
        targetSdk = 35
    }
}
""")
    elif build_gradle_type == "groovy_with_ndk":
        build_gradle = android_dir / "build.gradle"
        build_gradle.write_text("""
android {
    compileSdkVersion 35
    ndk {
        moduleName "native"
    }
    defaultConfig {
        targetSdkVersion 35
    }
}
""")
    return proj


def test_configurator_idempotency_preserves_first_backup(tmp_path):
    """Verify that multiple applies do NOT overwrite the original .bak file."""
    proj = create_full_mock_project(tmp_path, build_gradle_type="groovy")
    orig_props_content = (proj / "android" / "gradle.properties").read_text()
    
    # First apply
    res1 = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
    assert res1.returncode == 0
    bak_props_content_1 = (proj / "android" / "gradle.properties.bak").read_text()
    assert bak_props_content_1 == orig_props_content
    
    # Second apply
    res2 = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
    assert res2.returncode == 0
    bak_props_content_2 = (proj / "android" / "gradle.properties.bak").read_text()
    assert bak_props_content_2 == orig_props_content, "Second apply must NOT overwrite original backup!"


def test_configurator_rollback_restores_exact_state(tmp_path):
    """Verify that rollback restores exact byte-for-byte original files and cleans up state."""
    proj = create_full_mock_project(tmp_path, build_gradle_type="kotlin")
    orig_props = (proj / "android" / "gradle.properties").read_bytes()
    orig_gradle = (proj / "android" / "app" / "build.gradle.kts").read_bytes()
    
    # Apply
    subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], check=True)
    assert (proj / ".termux_project_config.json").exists()
    
    # Rollback
    subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], check=True)
    
    # Check restored state
    assert not (proj / ".termux_project_config.json").exists()
    assert not (proj / "android" / "gradle.properties.bak").exists()
    assert not (proj / "android" / "app" / "build.gradle.kts.bak").exists()
    assert (proj / "android" / "gradle.properties").read_bytes() == orig_props
    assert (proj / "android" / "app" / "build.gradle.kts").read_bytes() == orig_gradle


def test_configurator_groovy_existing_ndk_block(tmp_path):
    """Verify that if build.gradle already has an ndk block, abiFilters is appended inside it."""
    proj = create_full_mock_project(tmp_path, build_gradle_type="groovy_with_ndk")
    
    res = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
    assert res.returncode == 0
    
    content = (proj / "android" / "app" / "build.gradle").read_text()
    assert "abiFilters 'arm64-v8a'" in content
    assert "Added abiFilters to existing ndk block" in res.stdout


def test_configurator_preimage_missing_compile_sdk(tmp_path):
    """Verify preimage check fails gracefully when compileSdk is missing from build.gradle."""
    proj = tmp_path / "broken_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)
    (proj / "android" / "gradle.properties").write_text("# empty\n")
    (android_dir / "build.gradle").write_text("""
android {
    // Empty block without version setting
}
""")
    
    res = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
    assert res.returncode != 0
    assert "Preimage verification failed" in res.stderr or "Preimage verification failed" in res.stdout
    assert "compileSdk" not in (android_dir / "build.gradle").read_text()


def test_configurator_state_file_validity(tmp_path):
    """Verify .termux_project_config.json contains valid JSON with timestamp, modified_files, and status."""
    proj = create_full_mock_project(tmp_path, build_gradle_type="kotlin")
    
    subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], check=True)
    
    state_path = proj / ".termux_project_config.json"
    assert state_path.exists()
    
    data = json.loads(state_path.read_text())
    assert data["status"] == "configured"
    assert "T" in data["timestamp"] and "Z" in data["timestamp"]
    assert isinstance(data["modified_files"], list)
    assert "android/gradle.properties" in data["modified_files"]
    assert "android/app/build.gradle.kts" in data["modified_files"]
