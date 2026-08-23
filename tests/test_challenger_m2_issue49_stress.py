import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
CONFIG_SCRIPT = REPO_ROOT / "scripts" / "install" / "flutter_project_config.sh"


from conftest import to_bash_path


def test_adversarial_gradle_properties_delimiters_and_spacing(tmp_path):
    """Stress-test gradle.properties delimiter variations, whitespace, tabs, and comment preservation."""
    proj = tmp_path / "spaced_props_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)
    (android_dir / "build.gradle").write_text(
        "android {\n    compileSdkVersion 35\n    defaultConfig {\n        targetSdkVersion 35\n    }\n}\n"
    )

    gradle_props = proj / "android" / "gradle.properties"
    initial_props = (
        "# Header Comment 1\n"
        "# android.aapt2FromMavenOverride=/commented/path/1\n"
        "   android.aapt2FromMavenOverride   =   /spaced/equals/path   \n"
        "android.aapt2FromMavenOverride:/spaced/colon/path\n"
        "\tandroid.aapt2FromMavenOverride\t=\t/tabbed/path\n"
        "# Another Comment 2\n"
        "org.gradle.jvmargs=-Xmx2048m\n"
        "android.useAndroidX=true\n"
    )
    gradle_props.write_text(initial_props)

    # Apply configuration
    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Configurator failed: {res.stderr}"

    result_props = gradle_props.read_text()

    # Verify comments and other properties were preserved
    assert "# Header Comment 1" in result_props
    assert "# android.aapt2FromMavenOverride=/commented/path/1" in result_props
    assert "# Another Comment 2" in result_props
    assert "org.gradle.jvmargs=-Xmx2048m" in result_props
    assert "android.useAndroidX=true" in result_props

    # Verify old paths were removed
    assert "/spaced/equals/path" not in result_props
    assert "/spaced/colon/path" not in result_props
    assert "/tabbed/path" not in result_props

    # Verify exactly one active override line is present
    active_overrides = [
        line for line in result_props.splitlines() if line.startswith("android.aapt2FromMavenOverride=")
    ]
    assert len(active_overrides) == 1, f"Expected 1 active override line, got: {active_overrides}"

    # Rollback and verify exact pre-image restoration
    res_rb = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rb.returncode == 0, f"Rollback failed: {res_rb.stderr}"
    assert gradle_props.read_text() == initial_props


def test_adversarial_missing_gradle_properties_lifecycle(tmp_path):
    """Stress-test missing gradle.properties: auto-creation, state tracking, and clean deletion on rollback."""
    proj = tmp_path / "missing_props_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)
    build_gradle = android_dir / "build.gradle.kts"
    initial_gradle = "android {\n    compileSdk = 35\n    defaultConfig {\n        targetSdk = 35\n    }\n}\n"
    build_gradle.write_text(initial_gradle)

    gradle_props = proj / "android" / "gradle.properties"
    assert not gradle_props.exists()

    # Apply configuration
    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Apply failed: {res.stderr}"

    assert gradle_props.exists(), "gradle.properties should be auto-created"
    assert "android.aapt2FromMavenOverride=" in gradle_props.read_text()
    assert not (proj / "android" / "gradle.properties.bak").exists(), "No .bak for newly created file"

    state_file = proj / ".termux_project_config.json"
    assert state_file.exists(), "State file must exist"
    state = json.loads(state_file.read_text())
    assert "android/gradle.properties" in state.get("created_files", [])

    # Rollback must completely remove the created gradle.properties and state file
    res_rb = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rb.returncode == 0, f"Rollback failed: {res_rb.stderr}"
    assert not gradle_props.exists(), "Auto-created gradle.properties must be deleted on rollback"
    assert not state_file.exists(), "State file must be deleted on rollback"
    assert build_gradle.read_text() == initial_gradle


def test_adversarial_target_sdk_template_and_missing_variations(tmp_path):
    """Stress-test targetSdk/compileSdk injection and template variable substitution in Groovy and Kotlin."""
    # 1. Groovy with template variable and missing targetSdkVersion
    proj_groovy = tmp_path / "proj_groovy"
    (proj_groovy / "android" / "app").mkdir(parents=True)
    (proj_groovy / "android" / "gradle.properties").write_text("")
    groovy_file = proj_groovy / "android" / "app" / "build.gradle"
    groovy_initial = (
        "android {\n"
        "    compileSdkVersion flutter.compileSdkVersion\n"
        "    defaultConfig {\n"
        "        applicationId \"com.example.groovyapp\"\n"
        "        minSdkVersion 21\n"
        "        versionCode 1\n"
        "    }\n"
        "}\n"
    )
    groovy_file.write_text(groovy_initial)

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj_groovy)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Groovy config failed: {res.stderr}"
    g_res = groovy_file.read_text()
    assert "compileSdkVersion = 34" in g_res or "compileSdkVersion 34" in g_res
    assert "flutter.compileSdkVersion" not in g_res
    assert "targetSdkVersion 34" in g_res or "targetSdkVersion = 34" in g_res
    assert "abiFilters 'arm64-v8a'" in g_res

    # 2. Kotlin with targetSdk = flutter.targetSdkVersion and compileSdk = 36
    proj_kotlin = tmp_path / "proj_kotlin"
    (proj_kotlin / "android" / "app").mkdir(parents=True)
    (proj_kotlin / "android" / "gradle.properties").write_text("")
    kotlin_file = proj_kotlin / "android" / "app" / "build.gradle.kts"
    kotlin_initial = (
        "android {\n"
        "    compileSdk = 36\n"
        "    defaultConfig {\n"
        "        applicationId = \"com.example.kotlinapp\"\n"
        "        minSdk = 24\n"
        "        targetSdk = flutter.targetSdkVersion\n"
        "    }\n"
        "}\n"
    )
    kotlin_file.write_text(kotlin_initial)

    res_k = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj_kotlin)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_k.returncode == 0, f"Kotlin config failed: {res_k.stderr}"
    k_res = kotlin_file.read_text()
    assert "compileSdk = 34" in k_res
    assert "targetSdk = 34" in k_res
    assert "flutter.targetSdkVersion" not in k_res
    assert 'abiFilters += listOf("arm64-v8a")' in k_res


def test_adversarial_mode_a_b_and_env_precedence(tmp_path):
    """Stress-test CLI flags (--mode=A, --mode=B, --aapt2) and environment variable resolution precedence."""
    proj = tmp_path / "mode_prec_app"
    (proj / "android" / "app").mkdir(parents=True)
    (proj / "android" / "app" / "build.gradle").write_text(
        "android {\n    compileSdkVersion 35\n    defaultConfig {\n        targetSdkVersion 35\n    }\n}\n"
    )
    gradle_props = proj / "android" / "gradle.properties"
    cfg_sh = to_bash_path(CONFIG_SCRIPT)
    proj_sh = to_bash_path(proj)

    # 1. Flag --aapt2 overrides everything even if env vars and --mode=A are present
    cmd1 = f"export AAPT2_OVERRIDE='/env/aapt2' && export TERMUX_AAPT2_PATH='/termux/aapt2' && bash '{cfg_sh}' --aapt2=/flag/aapt2 '{proj_sh}'"
    res1 = subprocess.run(["bash", "-c", cmd1], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res1.returncode == 0, f"cmd1 failed: {res1.stderr}"
    assert "android.aapt2FromMavenOverride=/flag/aapt2" in gradle_props.read_text()

    # 2. AAPT2_OVERRIDE takes precedence over --mode=A and TERMUX_AAPT2_PATH
    cmd2 = f"export AAPT2_OVERRIDE='/env/aapt2' && export TERMUX_AAPT2_PATH='/termux/aapt2' && bash '{cfg_sh}' --mode=A '{proj_sh}'"
    res2 = subprocess.run(["bash", "-c", cmd2], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res2.returncode == 0, f"cmd2 failed: {res2.stderr}"
    assert "android.aapt2FromMavenOverride=/env/aapt2" in gradle_props.read_text()

    # 3. TERMUX_AAPT2_PATH takes precedence when AAPT2_OVERRIDE is unset
    cmd3 = f"unset AAPT2_OVERRIDE && export TERMUX_AAPT2_PATH='/termux/aapt2' && bash '{cfg_sh}' '{proj_sh}'"
    res3 = subprocess.run(["bash", "-c", cmd3], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res3.returncode == 0, f"cmd3 failed: {res3.stderr}"
    assert "android.aapt2FromMavenOverride=/termux/aapt2" in gradle_props.read_text()

    # 4. --mode=A sets standard Termux bin/aapt2
    cmd4 = f"unset AAPT2_OVERRIDE && unset TERMUX_AAPT2_PATH && bash '{cfg_sh}' --mode=A '{proj_sh}'"
    res4 = subprocess.run(["bash", "-c", cmd4], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res4.returncode == 0, f"cmd4 failed: {res4.stderr}"
    assert "android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2" in gradle_props.read_text()

    # 5. --mode=B sets static build-tools aapt2
    cmd5 = f"unset AAPT2_OVERRIDE && unset TERMUX_AAPT2_PATH && bash '{cfg_sh}' --mode=B '{proj_sh}'"
    res5 = subprocess.run(["bash", "-c", cmd5], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res5.returncode == 0, f"cmd5 failed: {res5.stderr}"
    assert "Android/Sdk/build-tools/35.0.0/aapt2" in gradle_props.read_text() or "android-sdk/build-tools/35.0.0/aapt2" in gradle_props.read_text()


def test_adversarial_transactional_error_trap(tmp_path):
    """Stress-test that corrupted inputs mid-flight trigger trap cleanup, restoring original files and removing created ones."""
    proj = tmp_path / "corrupt_syntax_app"
    (proj / "android" / "app").mkdir(parents=True)
    orig_props = "org.gradle.jvmargs=-Xmx1024m\n# Pre-existing property\n"
    (proj / "android" / "gradle.properties").write_text(orig_props)

    # Corrupted build.gradle (unbalanced brace)
    corrupted_gradle = "android {\n    compileSdkVersion 35\n    defaultConfig {\n        targetSdkVersion 35\n"
    (proj / "android" / "app" / "build.gradle").write_text(corrupted_gradle)

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0, "Should fail on unbalanced braces"

    # Pre-existing file must be restored
    assert (proj / "android" / "gradle.properties").read_text() == orig_props
    assert not (proj / "android" / "gradle.properties.bak").exists()
    assert not (proj / "android" / "app" / "build.gradle.bak").exists()
    assert not (proj / ".termux_project_config.json").exists()


def test_adversarial_missing_default_config_block_injection(tmp_path):
    """Stress-test that a build.gradle without defaultConfig block receives a synthesized defaultConfig block."""
    proj = tmp_path / "no_dc_app"
    (proj / "android" / "app").mkdir(parents=True)
    (proj / "android" / "gradle.properties").write_text("")

    build_gradle = proj / "android" / "app" / "build.gradle"
    # No defaultConfig block at all
    initial_content = """android {
    compileSdkVersion 35

    buildTypes {
        release {
            minifyEnabled false
        }
    }
}
"""
    build_gradle.write_text(initial_content)

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Config failed: {res.stderr}"

    content = build_gradle.read_text()
    assert "defaultConfig {" in content
    assert "targetSdkVersion 34" in content or "targetSdkVersion = 34" in content
    assert "abiFilters 'arm64-v8a'" in content
    assert "compileSdkVersion = 34" in content or "compileSdkVersion 34" in content

    # Rollback
    res_rb = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rb.returncode == 0
    assert build_gradle.read_text() == initial_content


def test_adversarial_strings_and_comments_with_braces(tmp_path):
    """Stress-test that string literals and comments with braces do not confuse the scope parser."""
    proj = tmp_path / "braces_in_strings_app"
    (proj / "android" / "app").mkdir(parents=True)
    (proj / "android" / "gradle.properties").write_text("")

    build_gradle = proj / "android" / "app" / "build.gradle.kts"
    initial_content = '''android {
    compileSdk = 35

    // Comment with unbalanced brace: { { {
    /* Multi-line comment with braces:
       defaultConfig { targetSdk = 30 }
    */

    defaultConfig {
        applicationId = "com.example.{app}"
        minSdk = 21
        targetSdk = 35
        val dummyStr = """ { nested brace string } """
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
        }
    }
}
'''
    build_gradle.write_text(initial_content)

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Config failed on braces in strings: {res.stderr}"

    content = build_gradle.read_text()
    assert "compileSdk = 34" in content
    assert "targetSdk = 34" in content
    assert 'abiFilters += listOf("arm64-v8a")' in content
    assert 'applicationId = "com.example.{app}"' in content
    assert 'val dummyStr = """ { nested brace string } """' in content

    # Rollback
    res_rb = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rb.returncode == 0
    assert build_gradle.read_text() == initial_content

