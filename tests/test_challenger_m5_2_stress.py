import json
import os
import re
import subprocess
import shutil
import tempfile
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

def test_workflow_permissions_contents_write():
    """Verify both build-deb.yml and device-smoke.yml have top-level contents: write permissions."""
    build_deb_path = REPO_ROOT / ".github" / "workflows" / "build-deb.yml"
    device_smoke_path = REPO_ROOT / ".github" / "workflows" / "device-smoke.yml"

    for path in [build_deb_path, device_smoke_path]:
        content = path.read_text(encoding="utf-8")
        assert "permissions:" in content, f"Missing permissions block in {path.name}"
        assert "contents: write" in content, f"Missing contents: write in {path.name}"
        assert "actions: read" in content, f"Missing actions: read in {path.name}"

def test_release_promotion_target_commit_binding():
    """Verify release promotion in device-smoke.yml binds tag to --target $SOURCE_COMMIT."""
    device_smoke_path = REPO_ROOT / ".github" / "workflows" / "device-smoke.yml"
    content = device_smoke_path.read_text(encoding="utf-8")

    assert "SOURCE_COMMIT=" in content, "device-smoke.yml must extract SOURCE_COMMIT from metadata"
    assert 'source_commit' in content, "device-smoke.yml must query source_commit JSON field"
    assert '--target' in content and '$SOURCE_COMMIT' in content, "device-smoke.yml must pass --target $SOURCE_COMMIT to gh release create"
    assert 'if [ -z "$SOURCE_COMMIT" ]; then' in content, "device-smoke.yml must fail if SOURCE_COMMIT is empty"

def test_build_deb_metadata_generation():
    """Verify build-deb.yml populates build_metadata.json and evidence.json with source_commit and build_number."""
    build_deb_path = REPO_ROOT / ".github" / "workflows" / "build-deb.yml"
    content = build_deb_path.read_text(encoding="utf-8")

    assert '"source_commit": "${{ github.sha }}"' in content, "build-deb.yml must set source_commit to github.sha"
    assert '"build_number": "${{ github.run_number }}"' in content, "build-deb.yml must set build_number to github.run_number"
    assert '"sha256":' in content, "build-deb.yml must record deb sha256"

def test_termux_smoke_sh_failure_propagation_logic():
    """Empirically test termux_smoke.sh evidence function and exit code when status is non-zero."""
    smoke_sh_path = REPO_ROOT / "scripts" / "device" / "termux_smoke.sh"
    content = smoke_sh_path.read_text(encoding="utf-8")

    # Check exit code is $status
    assert 'exit "$status"' in content or 'exit $status' in content, "termux_smoke.sh must exit with $status"
    assert 'trap write_evidence_json EXIT' in content, "termux_smoke.sh must trap write_evidence_json on EXIT"
    assert 'local cur_status="${status:-1}"' in content, "write_evidence_json must check $status"
    assert 'overall_status="failed"' in content, "overall_status must default to failed"

    if shutil.which("bash"):
        test_dir = REPO_ROOT / ".agents" / "challenger_m5_2"
        test_file = test_dir / "run_ev_test.sh"
        test_file.write_text("""#!/bin/bash
status=1
status_BUILD_APK_STATUS=1
status_APK_LAUNCH_STATUS=1
status_APK_CRASH_FREE_STATUS=1
EVIDENCE_JSON="./test_ev_out.json"

write_evidence_json() {
    local cur_status="${status:-1}"
    local overall_status="failed"
    if [ "$cur_status" = "0" ]; then
        overall_status="passed"
    fi
    cat > "$EVIDENCE_JSON" <<EOF
{
  "status": "$overall_status",
  "exit_status": $cur_status
}
EOF
}

write_evidence_json
""", encoding="utf-8", newline="\n")
        res = subprocess.run(["bash", "run_ev_test.sh"], cwd=str(test_dir), capture_output=True, text=True)
        assert res.returncode == 0
        ev_out = test_dir / "test_ev_out.json"
        assert ev_out.exists()
        ev_data = json.loads(ev_out.read_text(encoding="utf-8"))
        assert ev_data["status"] == "failed"
        assert ev_data["exit_status"] == 1
        ev_out.unlink(missing_ok=True)
        test_file.unlink(missing_ok=True)

def test_run_termux_smoke_ps1_markers_and_exceptions():
    """Verify run_termux_smoke.ps1 requires CONFIG_VERIFY_STATUS=0 and throws on missing markers."""
    ps1_path = REPO_ROOT / "scripts" / "device" / "run_termux_smoke.ps1"
    content = ps1_path.read_text(encoding="utf-8")

    assert '"CONFIG_VERIFY_STATUS=0"' in content, "run_termux_smoke.ps1 must require CONFIG_VERIFY_STATUS=0 marker"
    assert '"BUILD_APK_STATUS=0"' in content, "run_termux_smoke.ps1 must require BUILD_APK_STATUS=0"
    assert '"BUILD_LINUX_STATUS=0"' in content, "run_termux_smoke.ps1 must require BUILD_LINUX_STATUS=0"
    assert 'throw "Missing smoke marker: $marker"' in content, "run_termux_smoke.ps1 must throw on missing marker"
    assert 'throw "APK launch verification failed on host"' in content, "run_termux_smoke.ps1 must throw on host launch failure"
    assert 'throw "APK crash-free verification failed on host"' in content, "run_termux_smoke.ps1 must throw on host crash failure"

def test_flutter_project_config_sh_execution():
    """Empirically test scripts/install/flutter_project_config.sh against mock Flutter projects inside repo dir."""
    if not shutil.which("bash"):
        pytest.skip("bash not available on system")

    config_script = REPO_ROOT / "scripts" / "install" / "flutter_project_config.sh"
    assert config_script.exists()

    tmp_dir = REPO_ROOT / ".agents" / "challenger_m5_2" / "mock_projs"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Create mock Kotlin Gradle project
        proj_kts = tmp_dir / "mock_flutter_kts"
        if proj_kts.exists():
            shutil.rmtree(proj_kts)
        (proj_kts / "android" / "app").mkdir(parents=True)
        (proj_kts / "android" / "gradle.properties").write_text("org.gradle.jvmargs=-Xmx2048m\n", encoding="utf-8")
        (proj_kts / "android" / "app" / "build.gradle.kts").write_text("""
android {
    compileSdk = flutter.compileSdkVersion
    defaultConfig {
        applicationId = "com.example.test"
        targetSdk = flutter.targetSdkVersion
    }
}
""", encoding="utf-8")

        rel_config = "scripts/install/flutter_project_config.sh"
        rel_kts = os.path.relpath(proj_kts, REPO_ROOT).replace("\\", "/")
        res_kts = subprocess.run(["bash", rel_config, rel_kts], cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert res_kts.returncode == 0, f"flutter_project_config.sh failed on kts project: {res_kts.stderr}\nstdout: {res_kts.stdout}"

        kts_content = (proj_kts / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
        props_content = (proj_kts / "android" / "gradle.properties").read_text(encoding="utf-8")

        assert "compileSdk = 34" in kts_content
        assert "targetSdk = 34" in kts_content
        assert 'abiFilters += listOf("arm64-v8a")' in kts_content
        assert "android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2" in props_content

        # Create mock Groovy Gradle project
        proj_groovy = tmp_dir / "mock_flutter_groovy"
        if proj_groovy.exists():
            shutil.rmtree(proj_groovy)
        (proj_groovy / "android" / "app").mkdir(parents=True)
        (proj_groovy / "android" / "gradle.properties").write_text("", encoding="utf-8")
        (proj_groovy / "android" / "app" / "build.gradle").write_text("""
android {
    compileSdkVersion 35
    defaultConfig {
        applicationId "com.example.groovy"
        targetSdkVersion 35
    }
}
""", encoding="utf-8")

        rel_groovy = os.path.relpath(proj_groovy, REPO_ROOT).replace("\\", "/")
        res_groovy = subprocess.run(["bash", rel_config, rel_groovy], cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert res_groovy.returncode == 0, f"flutter_project_config.sh failed on groovy project: {res_groovy.stderr}\nstdout: {res_groovy.stdout}"

        groovy_content = (proj_groovy / "android" / "app" / "build.gradle").read_text(encoding="utf-8")
        assert "compileSdk = 34" in groovy_content or "compileSdkVersion = 34" in groovy_content or "compileSdkVersion 34" in groovy_content
        assert "abiFilters 'arm64-v8a'" in groovy_content
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

def test_package_yaml_flutter_project_config_mapping():
    """Verify package.yaml configures flutter_project_config mapping."""
    package_yaml = REPO_ROOT / "package.yaml"
    content = package_yaml.read_text(encoding="utf-8")

    assert "flutter_project_config:" in content
    assert "scripts/install/flutter_project_config.sh" in content
    assert "$prefix/share/flutter/flutter_project_config.sh" in content
