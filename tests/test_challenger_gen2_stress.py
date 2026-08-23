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
# 1. Advanced Stress Tests for lib_common.sh
# ============================================================================

def test_verify_sha256_space_in_filename(tmp_path):
    test_file = tmp_path / "my test package.deb"
    content = b"hello world test package content"
    test_file.write_bytes(content)
    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(test_file)
    
    # Calculate real sha256
    import hashlib
    expected_hash = hashlib.sha256(content).hexdigest()
    
    cmd = f"source '{lib_path}' && verify_sha256 '{file_path}' '{expected_hash}'"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Failed for file with spaces: {res.stderr}\n{res.stdout}"
    assert test_file.exists()


def test_verify_sha256_mismatch_removes_file_with_spaces(tmp_path):
    test_file = tmp_path / "corrupted file name with spaces.deb"
    test_file.write_bytes(b"corrupted data")
    lib_path = to_bash_path(LIB_COMMON)
    file_path = to_bash_path(test_file)
    wrong_hash = "f" * 64
    
    cmd = f"source '{lib_path}' && verify_sha256 '{file_path}' '{wrong_hash}'"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode != 0
    assert not test_file.exists(), "Corrupted file with spaces in name must be removed"


def test_stage_status_json_validation():
    lib_path = to_bash_path(LIB_COMMON)
    cmd = f"source '{lib_path}' && record_stage preflight success && record_stage download success && record_stage integrity success && print_summary"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0
    # Parse json output
    output_str = res.stdout.strip()
    data = json.loads(output_str)
    assert data.get("preflight") == "success"
    assert data.get("download") == "success"
    assert data.get("integrity") == "success"


def test_preflight_check_failure_on_non_arm64():
    lib_path = to_bash_path(LIB_COMMON)
    # Mock uname -m to return x86_64
    mock_cmd = 'uname() { if [ "$1" = "-m" ]; then echo "x86_64"; else builtin uname "$@"; fi; };'
    cmd = f"{mock_cmd} source '{lib_path}' && trap print_summary EXIT && preflight_check 1000"
    res = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 10
    assert "Error: This script only supports ARM64" in res.stdout or "Error: This script only supports ARM64" in res.stderr
    assert '"preflight": "failed"' in res.stdout


# ============================================================================
# 2. Advanced Stress Tests for flutter_project_config.sh
# ============================================================================

def test_configurator_spaces_in_path(tmp_path):
    proj = tmp_path / "my app with spaces"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)
    
    gradle_props = proj / "android" / "gradle.properties"
    gradle_props.write_text("org.gradle.jvmargs=-Xmx2048m\n")
    
    build_gradle = android_dir / "build.gradle.kts"
    build_gradle.write_text("android {\n    compileSdk = 36\n    defaultConfig {\n        targetSdk = 36\n    }\n}\n")
    
    orig_props = gradle_props.read_bytes()
    orig_gradle = build_gradle.read_bytes()
    
    # Apply
    res1 = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert res1.returncode == 0
    assert (proj / ".termux_project_config.json").exists()
    
    # Rollback
    res2 = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert res2.returncode == 0
    assert not (proj / ".termux_project_config.json").exists()
    assert gradle_props.read_bytes() == orig_props
    assert build_gradle.read_bytes() == orig_gradle


@pytest.mark.parametrize("compile_format,target_format", [
    ("compileSdkVersion 35", "targetSdkVersion 35"),
    ("compileSdkVersion=35", "targetSdkVersion=35"),
    ("compileSdkVersion = 35", "targetSdkVersion = 35"),
    ("compileSdk 35", "targetSdk 35"),
    ("compileSdk = 35", "targetSdk = 35"),
])
def test_configurator_groovy_various_formats(tmp_path, compile_format, target_format):
    proj = tmp_path / f"app_{hash(compile_format)}"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)
    
    (proj / "android" / "gradle.properties").write_text("org.gradle.jvmargs=-Xmx2048m\n")
    
    build_gradle_content = (
        "android {\n"
        f"    {compile_format}\n"
        "    defaultConfig {\n"
        '        applicationId "com.example.app"\n'
        f"        {target_format}\n"
        "    }\n"
        "}\n"
    )
    build_gradle = android_dir / "build.gradle"
    build_gradle.write_text(build_gradle_content)
    orig_bytes = build_gradle.read_bytes()
    
    # Apply
    res1 = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert res1.returncode == 0
    
    modified_text = build_gradle.read_text()
    assert "= 34" in modified_text
    assert "arm64-v8a" in modified_text
    
    # Rollback
    res2 = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert res2.returncode == 0
    assert build_gradle.read_bytes() == orig_bytes


def test_configurator_invalid_arguments():
    res1 = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT)],
        cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert res1.returncode == 1
    assert "Usage:" in res1.stdout or "Usage:" in res1.stderr

    res2 = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "arg1", "arg2", "arg3"],
        cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert res2.returncode == 1
    assert "Usage:" in res2.stdout or "Usage:" in res2.stderr
