import json
import os
import shutil
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
LIB_COMMON = REPO_ROOT / "scripts" / "install" / "lib_common.sh"
INSTALLER = REPO_ROOT / "install_flutter_complete.sh"
CONFIG_SCRIPT = REPO_ROOT / "scripts" / "install" / "flutter_project_config.sh"


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


# ============================================================================
# 1. Stress Tests for lib_common.sh / verify_sha256
# ============================================================================

def test_verify_sha256_missing_file(tmp_path):
    lib_path = to_bash_path(LIB_COMMON)
    non_existent = to_bash_path(tmp_path / "does_not_exist.bin")
    cmd = f"source '{lib_path}' && verify_sha256 '{non_existent}' '1234'"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode != 0
    assert "File not found" in res.stdout or "File not found" in res.stderr


def test_verify_sha256_empty_expected_hash_vulnerability(tmp_path):
    """Test what happens if expected hash is empty string."""
    test_file = tmp_path / "sample.txt"
    test_file.write_bytes(b"some content\n")
    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(test_file)
    
    cmd = f"source '{lib_path}' && verify_sha256 '{file_path}' ''"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode != 0
    assert "Expected SHA256 checksum is empty" in res.stdout or "Expected SHA256 checksum is empty" in res.stderr


def test_verify_sha256_both_hashers_missing(tmp_path):
    test_file = tmp_path / "dummy.deb"
    test_file.write_bytes(b"dummy package content")
    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(test_file)

    mock_cmd = 'command() { if [ "$2" = "sha256sum" ] || [ "$2" = "shasum" ]; then return 1; fi; builtin command "$@"; };'
    cmd = f"{mock_cmd} source '{lib_path}' && verify_sha256 '{file_path}' 'dummyhash'"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode != 0
    assert "Neither sha256sum nor shasum is available" in res.stdout


def test_verify_sha256_checksum_mismatch_removes_file(tmp_path):
    test_file = tmp_path / "corrupt_pkg.deb"
    test_file.write_bytes(b"bad content")
    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(test_file)
    wrong_hash = "a" * 64

    cmd = f"source '{lib_path}' && verify_sha256 '{file_path}' '{wrong_hash}'"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode != 0
    assert not test_file.exists(), "Corrupted file must be removed"


# ============================================================================
# 2. Stress Tests for install_flutter_complete.sh
# ============================================================================

def test_installer_swallowed_dpkg_errors_scan():
    """Scan install_flutter_complete.sh for dpkg commands with || true."""
    content = INSTALLER.read_text(encoding="utf-8")
    lines = content.splitlines()
    swallowed_dpkg_lines = []
    for idx, line in enumerate(lines, 1):
        if "dpkg " in line and "|| true" in line:
            swallowed_dpkg_lines.append((idx, line.strip()))
    
    print("Found dpkg || true lines:", swallowed_dpkg_lines)
    # R1 constraint: dpkg failures must not be swallowed by || true
    # Let's check if there are dpkg -i calls swallowed by || true
    swallowed_dpkg_install = [l for l in swallowed_dpkg_lines if "dpkg -i" in l[1]]
    assert len(swallowed_dpkg_install) == 0, f"Found dpkg -i with || true: {swallowed_dpkg_install}"


def test_installer_preflight_purge_order_analysis():
    """Verify installer uses transactional install-first approach (no premature purge)."""
    content = INSTALLER.read_text(encoding="utf-8")
    lines = content.splitlines()
    
    # Transactional installer: dpkg --purge should NOT exist as a standalone purge-first step
    # (dpkg -i handles upgrades directly)
    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        if "dpkg --purge" in stripped and "|| true" in stripped:
            pytest.fail(
                f"Line {idx}: Found premature purge '{stripped}'. "
                f"Transactional installer must not purge before install."
            )
    
    # Verify Android SDK install line exists
    android_sdk_install_idx = None
    for idx, line in enumerate(lines, 1):
        if "ANDROID_SDK_DEB" in line and ("dpkg -i" in line or "dpkg --force" in line):
            if android_sdk_install_idx is None:
                android_sdk_install_idx = idx
    assert android_sdk_install_idx is not None, "Android SDK install line must exist"


# ============================================================================
# 3. Stress Tests for flutter_project_config.sh
# ============================================================================

def create_test_project(tmp_path, groovy=True, kts=False):
    proj = tmp_path / "test_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True, exist_ok=True)

    (proj / "android" / "gradle.properties").write_text(
        "org.gradle.jvmargs=-Xmx2048m\n"
    )

    if groovy:
        (android_dir / "build.gradle").write_text(
            "android {\n"
            "    compileSdkVersion 35\n"
            "    defaultConfig {\n"
            "        applicationId \"com.example.testapp\"\n"
            "        minSdkVersion 21\n"
            "        targetSdkVersion 35\n"
            "    }\n"
            "}\n"
        )
    if kts:
        (android_dir / "build.gradle.kts").write_text(
            "android {\n"
            "    compileSdk = 35\n"
            "    defaultConfig {\n"
            "        applicationId = \"com.example.testapp\"\n"
            "        minSdk = 21\n"
            "        targetSdk = 35\n"
            "    }\n"
            "}\n"
        )
    return proj


def test_configurator_rollback_byte_exact(tmp_path):
    proj = create_test_project(tmp_path, groovy=True, kts=True)
    orig_props = (proj / "android" / "gradle.properties").read_bytes()
    orig_groovy = (proj / "android" / "app" / "build.gradle").read_bytes()
    orig_kts = (proj / "android" / "app" / "build.gradle.kts").read_bytes()

    # Apply config
    res1 = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert res1.returncode == 0

    # Verify state file
    state_file = proj / ".termux_project_config.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["status"] == "configured"
    assert "timestamp" in state
    assert len(state["modified_files"]) > 0

    # Rollback
    res2 = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert res2.returncode == 0

    # Check state file and backups removed
    assert not state_file.exists()
    assert not (proj / "android" / "gradle.properties.bak").exists()
    assert not (proj / "android" / "app" / "build.gradle.bak").exists()
    assert not (proj / "android" / "app" / "build.gradle.kts.bak").exists()

    # Check files restored byte-exact
    assert (proj / "android" / "gradle.properties").read_bytes() == orig_props
    assert (proj / "android" / "app" / "build.gradle.kts").read_bytes() == orig_kts


def test_configurator_idempotency(tmp_path):
    proj = create_test_project(tmp_path, groovy=True)

    # First run
    res1 = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert res1.returncode == 0
    content1 = (proj / "android" / "app" / "build.gradle").read_text()

    # Second run
    res2 = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert res2.returncode == 0
    content2 = (proj / "android" / "app" / "build.gradle").read_text()

    assert content1 == content2, "Configurator must be idempotent (second run changes nothing)"


def test_configurator_preimage_failure(tmp_path):
    proj = tmp_path / "broken_proj"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)
    (proj / "android" / "gradle.properties").write_text("key=value\n")
    # build.gradle without defaultConfig or compileSdk
    (android_dir / "build.gradle").write_text("// Empty build gradle file\n")

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert res.returncode == 0
    assert "Preimage verification failed" in res.stdout
    # build.gradle should not have been modified
    assert (android_dir / "build.gradle").read_text() == "// Empty build gradle file\n"
