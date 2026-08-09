import json
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
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


def create_mock_project(tmp_path, use_kts=False):
    proj = tmp_path / "my_flutter_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    gradle_props.write_text("org.gradle.jvmargs=-Xmx2048m\n")

    if use_kts:
        build_gradle = android_dir / "build.gradle.kts"
        build_gradle.write_text(
            "android {\n"
            "    compileSdk = 35\n"
            "    defaultConfig {\n"
            "        targetSdk = 35\n"
            "    }\n"
            "}\n"
        )
    else:
        build_gradle = android_dir / "build.gradle"
        build_gradle.write_text(
            "android {\n"
            "    compileSdkVersion 35\n"
            "    defaultConfig {\n"
            "        targetSdkVersion 35\n"
            "    }\n"
            "}\n"
        )

    return proj


def test_configurator_apply_and_backup(tmp_path):
    proj = create_mock_project(tmp_path, use_kts=False)

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Script failed: stdout={res.stdout}, stderr={res.stderr}"

    # Check backups created
    assert (proj / "android" / "gradle.properties.bak").exists()
    assert (proj / "android" / "app" / "build.gradle.bak").exists()

    # Check content updated
    gradle_props_content = (proj / "android" / "gradle.properties").read_text()
    assert "android.aapt2FromMavenOverride" in gradle_props_content

    build_gradle_content = (proj / "android" / "app" / "build.gradle").read_text()
    assert (
        "compileSdk = 34" in build_gradle_content
        or "compileSdkVersion = 34" in build_gradle_content
        or "compileSdkVersion 34" in build_gradle_content
    )
    assert "abiFilters 'arm64-v8a'" in build_gradle_content

    # Check state file
    state_file = proj / ".termux_project_config.json"
    assert state_file.exists()
    state_data = json.loads(state_file.read_text())
    assert state_data["status"] == "configured"
    assert "timestamp" in state_data
    assert "android/gradle.properties" in state_data["modified_files"]


def test_configurator_rollback(tmp_path):
    proj = create_mock_project(tmp_path, use_kts=True)
    orig_gradle_props = (proj / "android" / "gradle.properties").read_text()
    orig_build_gradle = (proj / "android" / "app" / "build.gradle.kts").read_text()

    # Apply
    res_apply = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_apply.returncode == 0, f"Apply failed: {res_apply.stderr}"

    # Rollback
    res_rollback = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rollback.returncode == 0, f"Rollback failed: {res_rollback.stderr}"

    # Backups and state file should be gone
    assert not (proj / "android" / "gradle.properties.bak").exists()
    assert not (proj / "android" / "app" / "build.gradle.kts.bak").exists()
    assert not (proj / ".termux_project_config.json").exists()

    # Original contents restored byte-identically
    assert (proj / "android" / "gradle.properties").read_text() == orig_gradle_props
    assert (proj / "android" / "app" / "build.gradle.kts").read_text() == orig_build_gradle


def test_configurator_preimage_verification_failure(tmp_path):
    proj = tmp_path / "invalid_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    # Empty build.gradle (no compileSdk, no defaultConfig)
    build_gradle = android_dir / "build.gradle"
    build_gradle.write_text("// Empty file\n")

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "Preimage verification failed" in res.stdout


def test_configurator_syntax():
    res = subprocess.run(
        ["bash", "-n", to_bash_path(CONFIG_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"bash -n failed: {res.stderr}"


@pytest.mark.parametrize("use_kts, initial_ndk_block", [
    # Groovy fixtures
    (False, "    defaultConfig {\n        ndk {\n            abiFilters 'x86'\n        }\n    }\n"),
    (False, "    defaultConfig {\n        ndk {\n            abiFilters 'armeabi-v7a'\n        }\n    }\n"),
    (False, "    defaultConfig {\n        ndk {\n            abiFilters 'x86', 'armeabi-v7a'\n        }\n    }\n"),
    (False, "    defaultConfig {\n        ndk {\n            abiFilters 'arm64-v8a'\n        }\n    }\n"),
    # Kotlin DSL fixtures
    (True, "    defaultConfig {\n        ndk {\n            abiFilters += listOf(\"x86\")\n        }\n    }\n"),
    (True, "    defaultConfig {\n        ndk {\n            abiFilters += listOf(\"armeabi-v7a\")\n        }\n    }\n"),
    (True, "    defaultConfig {\n        ndk {\n            abiFilters += listOf(\"arm64-v8a\")\n        }\n    }\n"),
])
def test_abi_filters_fixtures(tmp_path, use_kts, initial_ndk_block):
    proj = tmp_path / "app_fixture"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    gradle_props.write_text("org.gradle.jvmargs=-Xmx2048m\n")

    filename = "build.gradle.kts" if use_kts else "build.gradle"
    target_file = android_dir / filename
    sdk_line = "    compileSdk = 35\n" if use_kts else "    compileSdkVersion 35\n"
    target_file.write_text(f"android {{\n{sdk_line}{initial_ndk_block}}}\n")

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Script failed for {filename}: {res.stderr}"

    content = target_file.read_text()
    assert "arm64-v8a" in content, f"arm64-v8a missing in {filename} after configuration"
