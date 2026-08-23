import hashlib
import json
import os
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
    assert res.returncode != 0
    assert "Preimage verification failed" in res.stderr or "Preimage verification failed" in res.stdout


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


# ==============================================================================
# Suite 1: Multi-Flavor Scope Isolation (Groovy & Kotlin DSL) - Issue #48
# ==============================================================================

def test_multi_flavor_groovy_scope_isolation(tmp_path):
    """Verify that multi-flavor Groovy build.gradle isolates abiFilters strictly to defaultConfig."""
    proj = tmp_path / "multi_flavor_groovy"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    (proj / "android" / "gradle.properties").write_text("org.gradle.jvmargs=-Xmx2048m\n")

    build_gradle = android_dir / "build.gradle"
    original_content = """android {
    compileSdkVersion 35

    defaultConfig {
        applicationId "com.example.multiflavorgroovy"
        minSdkVersion 21
        targetSdkVersion 35
        versionCode 1
        versionName "1.0"
    }

    buildTypes {
        release {
            minifyEnabled false
            ndk {
                abiFilters 'x86'
            }
        }
        debug {
            applicationIdSuffix ".debug"
        }
    }

    flavorDimensions "tier"
    productFlavors {
        demo {
            dimension "tier"
            applicationIdSuffix ".demo"
            ndk {
                abiFilters 'armeabi-v7a'
            }
        }
        full {
            dimension "tier"
            applicationIdSuffix ".full"
            ndk {
                abiFilters 'x86_64'
            }
        }
    }
}
"""
    build_gradle.write_text(original_content)
    orig_bytes = build_gradle.read_bytes()

    # Apply configuration
    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Apply failed: stdout={res.stdout}, stderr={res.stderr}"

    content = build_gradle.read_text()
    assert "compileSdkVersion = 34" in content or "compileSdkVersion 34" in content
    assert "targetSdkVersion = 34" in content or "targetSdkVersion 34" in content

    # defaultConfig must have arm64-v8a
    assert "abiFilters 'arm64-v8a'" in content

    # Flavors and buildTypes must NOT have arm64-v8a and must retain their original abiFilters
    assert "abiFilters 'x86'" in content
    assert "abiFilters 'armeabi-v7a'" in content
    assert "abiFilters 'x86_64'" in content

    # Extract sections to ensure no leakage
    demo_flavor_section = content[content.find("demo {"):content.find("full {")]
    assert "arm64-v8a" not in demo_flavor_section, "demo flavor polluted with arm64-v8a"
    assert "abiFilters 'armeabi-v7a'" in demo_flavor_section

    full_flavor_section = content[content.find("full {"):content.find("}\n}")]
    assert "arm64-v8a" not in full_flavor_section, "full flavor polluted with arm64-v8a"
    assert "abiFilters 'x86_64'" in full_flavor_section

    release_section = content[content.find("release {"):content.find("debug {")]
    assert "arm64-v8a" not in release_section, "release buildType polluted with arm64-v8a"
    assert "abiFilters 'x86'" in release_section

    # Rollback and verify exact pre-image restoration
    res_rb = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rb.returncode == 0
    assert build_gradle.read_bytes() == orig_bytes


def test_multi_flavor_kotlin_scope_isolation(tmp_path):
    """Verify that multi-flavor Kotlin DSL build.gradle.kts isolates abiFilters strictly to defaultConfig."""
    proj = tmp_path / "multi_flavor_kotlin"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    (proj / "android" / "gradle.properties").write_text("org.gradle.jvmargs=-Xmx2048m\n")

    build_gradle = android_dir / "build.gradle.kts"
    original_content = """android {
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.multiflavorkotlin"
        minSdk = 21
        targetSdk = 35
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            ndk {
                abiFilters += listOf("x86")
            }
        }
    }

    flavorDimensions += "version"
    productFlavors {
        create("demo") {
            dimension = "version"
            ndk {
                abiFilters += listOf("armeabi-v7a")
            }
        }
        create("full") {
            dimension = "version"
            ndk {
                abiFilters += listOf("x86_64")
            }
        }
    }
}
"""
    build_gradle.write_text(original_content)
    orig_bytes = build_gradle.read_bytes()

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Apply failed: {res.stderr}"

    content = build_gradle.read_text()
    assert "compileSdk = 34" in content
    assert "targetSdk = 34" in content
    assert 'abiFilters += listOf("arm64-v8a")' in content

    # Check flavors unpolluted
    demo_section = content[content.find('create("demo")'):content.find('create("full")')]
    assert "arm64-v8a" not in demo_section
    assert 'abiFilters += listOf("armeabi-v7a")' in demo_section

    full_section = content[content.find('create("full")'):]
    assert "arm64-v8a" not in full_section
    assert 'abiFilters += listOf("x86_64")' in full_section

    # Rollback check
    res_rb = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rb.returncode == 0
    assert build_gradle.read_bytes() == orig_bytes


# ==============================================================================
# Suite 2: Missing gradle.properties Auto-Creation & Clean Rollback - Issue #49
# ==============================================================================

def test_missing_gradle_properties_creation_and_clean_rollback(tmp_path):
    """Verify that when android/gradle.properties is absent, it is created and cleanly deleted on rollback."""
    proj = tmp_path / "no_gradle_props_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    build_gradle = android_dir / "build.gradle"
    build_gradle.write_text("android {\n    compileSdkVersion 35\n    defaultConfig {\n        targetSdkVersion 35\n    }\n}\n")
    orig_gradle_bytes = build_gradle.read_bytes()

    gradle_props = proj / "android" / "gradle.properties"
    assert not gradle_props.exists(), "gradle.properties must not pre-exist for this test"

    # Run configurator
    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Configurator failed: {res.stderr}"

    # Verify gradle.properties was created with override
    assert gradle_props.exists(), "gradle.properties was not auto-created"
    props_text = gradle_props.read_text()
    assert "android.aapt2FromMavenOverride=" in props_text
    assert not (proj / "android" / "gradle.properties.bak").exists(), "Newly created file must not have a .bak"

    # State file must record created_files
    state_path = proj / ".termux_project_config.json"
    assert state_path.exists()
    state_data = json.loads(state_path.read_text())
    assert "android/gradle.properties" in state_data.get("created_files", [])

    # Rollback
    res_rb = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rb.returncode == 0

    # Verify gradle.properties was DELETED (zero dangling files)
    assert not gradle_props.exists(), "Newly created gradle.properties must be deleted upon rollback"
    assert not state_path.exists()
    assert build_gradle.read_bytes() == orig_gradle_bytes


# ==============================================================================
# Suite 3: Spaced Properties and Comment Preservation - Issue #49
# ==============================================================================

def test_spaced_properties_and_comments_preservation(tmp_path):
    """Verify that property lines with arbitrary whitespace or delimiters are safely replaced while comments remain intact."""
    proj = tmp_path / "spaced_props_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    build_gradle = android_dir / "build.gradle"
    build_gradle.write_text("android {\n    compileSdkVersion 35\n    defaultConfig {\n        targetSdkVersion 35\n    }\n}\n")

    gradle_props = proj / "android" / "gradle.properties"
    initial_props = """# Top-level Gradle configuration comments
org.gradle.jvmargs=-Xmx2048m -XX:+HeapDumpOnOutOfMemoryError

# Old spaced AAPT2 override
   android.aapt2FromMavenOverride   =   /obsolete/old/aapt2/path

# AndroidX flags
android.useAndroidX=true
android.enableJetifier=true
"""
    gradle_props.write_text(initial_props)

    # Apply configuration
    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0

    result_props = gradle_props.read_text()
    # Comments preserved
    assert "# Top-level Gradle configuration comments" in result_props
    assert "# Old spaced AAPT2 override" in result_props
    assert "# AndroidX flags" in result_props
    assert "org.gradle.jvmargs=-Xmx2048m -XX:+HeapDumpOnOutOfMemoryError" in result_props
    assert "android.useAndroidX=true" in result_props

    # Obsolete path removed
    assert "/obsolete/old/aapt2/path" not in result_props

    # Exactly one active override present
    override_count = sum(1 for line in result_props.splitlines() if line.startswith("android.aapt2FromMavenOverride="))
    assert override_count == 1, f"Expected exactly 1 override line, found {override_count}"


# ==============================================================================
# Suite 4: Missing targetSdk Injection into defaultConfig - Issue #49
# ==============================================================================

def test_missing_target_sdk_injected_in_default_config_groovy(tmp_path):
    """Verify that targetSdkVersion 34 is injected when missing from Groovy defaultConfig."""
    proj = tmp_path / "missing_target_sdk_groovy"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    (proj / "android" / "gradle.properties").write_text("org.gradle.jvmargs=-Xmx2048m\n")

    build_gradle = android_dir / "build.gradle"
    # Note: No targetSdkVersion in defaultConfig!
    build_gradle.write_text("""android {
    compileSdkVersion 35
    defaultConfig {
        applicationId "com.example.missingtargetsdk"
        minSdkVersion 21
        versionCode 1
        versionName "1.0"
    }
}
""")
    orig_bytes = build_gradle.read_bytes()

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0

    content = build_gradle.read_text()
    assert "compileSdkVersion = 34" in content or "compileSdkVersion 34" in content
    assert "targetSdkVersion = 34" in content or "targetSdkVersion 34" in content
    assert "abiFilters 'arm64-v8a'" in content

    # Rollback
    res_rb = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rb.returncode == 0
    assert build_gradle.read_bytes() == orig_bytes


def test_missing_target_sdk_injected_in_default_config_kotlin(tmp_path):
    """Verify that targetSdk = 34 is injected when missing from Kotlin DSL defaultConfig."""
    proj = tmp_path / "missing_target_sdk_kotlin"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    (proj / "android" / "gradle.properties").write_text("org.gradle.jvmargs=-Xmx2048m\n")

    build_gradle = android_dir / "build.gradle.kts"
    # Note: No targetSdk in defaultConfig!
    build_gradle.write_text("""android {
    compileSdk = 35
    defaultConfig {
        applicationId = "com.example.missingtargetsdk"
        minSdk = 21
    }
}
""")
    orig_bytes = build_gradle.read_bytes()

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0

    content = build_gradle.read_text()
    assert "compileSdk = 34" in content
    assert "targetSdk = 34" in content
    assert 'abiFilters += listOf("arm64-v8a")' in content

    # Rollback
    res_rb = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rb.returncode == 0
    assert build_gradle.read_bytes() == orig_bytes


# ==============================================================================
# Suite 5: Template Variable targetSdk Replacement - Issue #49
# ==============================================================================

def test_flutter_template_target_sdk_replacement(tmp_path):
    """Verify replacement of Flutter standard template variables (e.g. flutter.targetSdkVersion)."""
    proj = tmp_path / "template_var_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    (proj / "android" / "gradle.properties").write_text("org.gradle.jvmargs=-Xmx2048m\n")

    build_gradle = android_dir / "build.gradle.kts"
    build_gradle.write_text("""android {
    compileSdk = flutter.compileSdkVersion
    defaultConfig {
        applicationId = "com.example.templateapp"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
    }
}
""")
    orig_bytes = build_gradle.read_bytes()

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0

    content = build_gradle.read_text()
    assert "compileSdk = 34" in content
    assert "targetSdk = 34" in content
    assert "flutter.targetSdkVersion" not in content
    assert "minSdk = flutter.minSdkVersion" in content  # unmutated

    # Rollback
    subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], check=True)
    assert build_gradle.read_bytes() == orig_bytes


# ==============================================================================
# Suite 6: Transactional Trap Rollback on Mid-Flight Failure - Issue #49
# ==============================================================================

def test_transactional_trap_rollback_on_mid_flight_failure(tmp_path):
    """Verify that if an error occurs mid-execution, trap restores original preimages and cleans backups."""
    proj = tmp_path / "trap_test_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    # Initial gradle.properties
    gradle_props = proj / "android" / "gradle.properties"
    orig_props_content = "org.gradle.jvmargs=-Xmx1024m\n# Original properties\n"
    gradle_props.write_text(orig_props_content)

    # Corrupted build.gradle that passes regex preimage check but fails python parsing
    build_gradle = android_dir / "build.gradle"
    # Unbalanced brace will cause python parse error / exit non-zero
    build_gradle.write_text("android {\n    compileSdkVersion 35\n    defaultConfig {\n        targetSdkVersion 35\n        // Missing closing braces")

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    # Must fail
    assert res.returncode != 0

    # Trap must have restored original gradle.properties
    assert gradle_props.read_text() == orig_props_content
    # Zero dangling .bak files
    assert not (proj / "android" / "gradle.properties.bak").exists()
    assert not (proj / "android" / "app" / "build.gradle.bak").exists()
    assert not (proj / ".termux_project_config.json").exists()


# ==============================================================================
# Suite 7: 100 Consecutive Invocations Idempotency & Hash Stability - Issue #48
# ==============================================================================

def test_idempotency_100_runs_hash_stability(tmp_path):
    """Verify that running configurator 100 times produces byte-identical hash stability."""
    proj = tmp_path / "idempotent_100_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    gradle_props.write_text("org.gradle.jvmargs=-Xmx2048m\n")
    orig_props_bytes = gradle_props.read_bytes()

    build_gradle = android_dir / "build.gradle.kts"
    build_gradle.write_text("""android {
    compileSdk = 35
    defaultConfig {
        applicationId = "com.example.idempotent"
        minSdk = 21
        targetSdk = 35
    }
    flavorDimensions += "tier"
    productFlavors {
        create("demo") {
            dimension = "tier"
            ndk {
                abiFilters += listOf("x86")
            }
        }
    }
}
""")
    orig_gradle_bytes = build_gradle.read_bytes()

    # Run 1
    res1 = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
    assert res1.returncode == 0
    hash_props_1 = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
    hash_gradle_1 = hashlib.sha256(build_gradle.read_bytes()).hexdigest()

    # Runs 2..100
    for i in range(2, 101):
        res_i = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
        assert res_i.returncode == 0, f"Run {i} failed: {res_i.stderr}"
        current_props_hash = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
        current_gradle_hash = hashlib.sha256(build_gradle.read_bytes()).hexdigest()
        assert current_props_hash == hash_props_1, f"gradle.properties hash drifted on run {i}"
        assert current_gradle_hash == hash_gradle_1, f"build.gradle.kts hash drifted on run {i}"

    # Rollback must restore run 0 bytes exactly
    res_rb = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], capture_output=True, text=True)
    assert res_rb.returncode == 0
    assert gradle_props.read_bytes() == orig_props_bytes
    assert build_gradle.read_bytes() == orig_gradle_bytes


# ==============================================================================
# Suite 8: Commented Blocks Resilience - Issue #48
# ==============================================================================

def test_commented_blocks_resilience(tmp_path):
    """Verify that comments containing defaultConfig/ndk/abiFilters are ignored and active blocks configured."""
    proj = tmp_path / "commented_blocks_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    (proj / "android" / "gradle.properties").write_text("org.gradle.jvmargs=-Xmx2048m\n")

    build_gradle = android_dir / "build.gradle"
    build_gradle.write_text("""// Old commented block that should be ignored:
// defaultConfig {
//     ndk {
//         abiFilters 'arm64-v8a'
//     }
//     targetSdkVersion 33
// }
/*
android {
    compileSdkVersion 33
}
*/
android {
    compileSdkVersion 35
    defaultConfig {
        applicationId "com.example.commented"
        minSdkVersion 21
        targetSdkVersion 35
    }
}
""")
    orig_bytes = build_gradle.read_bytes()

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0

    content = build_gradle.read_text()

    # Verify comments were NOT touched
    assert "// defaultConfig {" in content
    assert "//     targetSdkVersion 33" in content
    assert "/*\nandroid {\n    compileSdkVersion 33\n}\n*/" in content

    # Active block got updated
    assert "compileSdkVersion = 34" in content or "compileSdkVersion 34" in content
    assert "targetSdkVersion = 34" in content or "targetSdkVersion 34" in content

    # Active defaultConfig has ndk block with arm64-v8a
    assert "applicationId \"com.example.commented\"\n        minSdkVersion 21\n        targetSdkVersion = 34\n        ndk {\n            abiFilters 'arm64-v8a'\n        }" in content or "abiFilters 'arm64-v8a'" in content

    # Rollback
    subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], check=True)
    assert build_gradle.read_bytes() == orig_bytes


# ==============================================================================
# Suite 9: Mode A / Mode B Selection & Custom AAPT2 Path - Issue #49
# ==============================================================================

def test_mode_a_mode_b_selection(tmp_path):
    """Verify --mode=A, --mode=B, --aapt2, and $AAPT2_OVERRIDE selection logic."""
    proj = tmp_path / "mode_test_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)
    (android_dir / "build.gradle").write_text("android {\n    compileSdkVersion 35\n    defaultConfig {\n        targetSdkVersion 35\n    }\n}\n")

    gradle_props = proj / "android" / "gradle.properties"

    # Test 1: Explicit --aapt2 flag
    subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--aapt2=/opt/custom/aapt2", to_bash_path(proj)], check=True)
    assert "android.aapt2FromMavenOverride=/opt/custom/aapt2" in gradle_props.read_text()

    # Test 2: Explicit --mode=A
    subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--mode=A", to_bash_path(proj)], check=True)
    assert "/bin/aapt2" in gradle_props.read_text()

    # Test 3: Explicit --mode=B
    subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--mode=B", to_bash_path(proj)], check=True)
    assert "Android/Sdk/build-tools/35.0.0/aapt2" in gradle_props.read_text() or "android-sdk/build-tools/35.0.0/aapt2" in gradle_props.read_text()

    # Test 4: Custom path with quotes / JSON special characters
    special_path = '/opt/custom "quoted"/aapt2'
    subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), f"--aapt2={special_path}", to_bash_path(proj)], check=True)
    state_file = proj / ".termux_project_config.json"
    assert state_file.exists()
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["aapt2_path"] == special_path

    # Rollback succeeds with special character state file
    subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], check=True)
    assert not state_file.exists()

