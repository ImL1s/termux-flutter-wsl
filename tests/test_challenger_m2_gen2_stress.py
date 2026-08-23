import hashlib
import json
import os
import re
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
            return f"/{drive}{p[2:]}"
        return p


# ==============================================================================
# Adversarial Challenge 1: Complex Multi-Flavor & Multi-BuildType Isolation
# ==============================================================================

def test_adversarial_complex_multi_flavor_groovy_isolation(tmp_path):
    """
    Stress-test a deeply nested Groovy build.gradle containing:
    - 3 flavor dimensions ('brand', 'env', 'arch')
    - 6 product flavors with individual ndk blocks and comments
    - 4 buildTypes (debug, release, staging, benchmark) with ndk blocks
    - String literals containing fake defaultConfig and abiFilters syntax
    - Multiline comments containing valid-looking Gradle DSL blocks
    - Verify defaultConfig receives arm64-v8a while all flavors/buildTypes are 100% UNTOUCHED.
    """
    proj = tmp_path / "adv_complex_groovy_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    gradle_props.write_text("org.gradle.jvmargs=-Xmx4096m\n")

    build_gradle = android_dir / "build.gradle"
    original_code = """// Multi-flavor adversarial test build.gradle
// Fake commented block:
// defaultConfig {
//     ndk {
//         abiFilters 'arm64-v8a'
//     }
//     targetSdkVersion 33
// }

/*
android {
    compileSdkVersion 33
    defaultConfig {
        ndk { abiFilters 'mips', 'arm64-v8a' }
    }
}
*/

android {
    compileSdkVersion 35

    defaultConfig {
        applicationId "com.example.adversarial.groovy"
        minSdkVersion 23
        targetSdkVersion 35
        versionCode 42
        versionName "2.1.0"
        testInstrumentationRunner "androidx.test.runner.AndroidJUnitRunner"
        // String literal with decoy keywords:
        buildConfigField "String", "DECOY_CONFIG", '"defaultConfig { ndk { abiFilters \\'arm64-v8a\\' } }"'
    }

    flavorDimensions "brand", "env", "arch"

    productFlavors {
        brandAlpha {
            dimension "brand"
            applicationIdSuffix ".alpha"
            manifestPlaceholders = [appName: "AlphaApp"]
            ndk {
                abiFilters 'armeabi-v7a'
                // inline comment inside flavor ndk
            }
        }
        brandBeta {
            dimension "brand"
            applicationIdSuffix ".beta"
            ndk {
                abiFilters 'x86'
            }
        }
        dev {
            dimension "env"
            applicationIdSuffix ".dev"
        }
        staging {
            dimension "env"
            applicationIdSuffix ".staging"
            ndk {
                abiFilters 'x86_64', 'armeabi-v7a'
            }
        }
        prod {
            dimension "env"
        }
        internalOnly {
            dimension "arch"
            ndk {
                abiFilters 'x86'
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix ".debug"
            debuggable true
            ndk {
                abiFilters 'x86', 'x86_64'
            }
        }
        release {
            minifyEnabled true
            shrinkResources true
            proguardFiles getDefaultProguardFile('proguard-android.txt'), 'proguard-rules.pro'
            ndk {
                abiFilters 'armeabi-v7a'
            }
        }
        staging {
            initWith release
            matchingFallbacks = ['release']
            ndk {
                abiFilters 'x86_64'
            }
        }
        benchmark {
            initWith release
            signingConfig signingConfigs.debug
            matchingFallbacks = ['release']
        }
    }
}
"""
    build_gradle.write_text(original_code, newline="\n")
    orig_bytes = build_gradle.read_bytes()

    # Extract all flavor and buildType blocks before applying configuration
    flavors_start = original_code.find("productFlavors {")
    buildtypes_start = original_code.find("buildTypes {")
    orig_flavors_block = original_code[flavors_start:buildtypes_start]
    orig_buildtypes_block = original_code[buildtypes_start:original_code.rfind("}")]

    # Run configurator
    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Configurator failed: {res.stderr}\nSTDOUT:\n{res.stdout}"

    transformed_code = build_gradle.read_text(encoding="utf-8")

    # 1. compileSdkVersion and targetSdkVersion updated to 34
    assert "compileSdkVersion = 34" in transformed_code or "compileSdkVersion 34" in transformed_code
    assert "targetSdkVersion = 34" in transformed_code or "targetSdkVersion 34" in transformed_code

    # 2. defaultConfig contains arm64-v8a
    dc_start = transformed_code.find("defaultConfig {")
    flavors_new_start = transformed_code.find("flavorDimensions")
    default_config_text = transformed_code[dc_start:flavors_new_start]
    assert "abiFilters 'arm64-v8a'" in default_config_text, "arm64-v8a missing from defaultConfig"

    # 3. Product flavors are 100% UNTOUCHED
    transformed_flavors_start = transformed_code.find("productFlavors {")
    transformed_buildtypes_start = transformed_code.find("buildTypes {")
    transformed_flavors_block = transformed_code[transformed_flavors_start:transformed_buildtypes_start]
    assert transformed_flavors_block == orig_flavors_block, "productFlavors block was mutated/polluted!"

    # 4. BuildTypes are 100% UNTOUCHED
    transformed_buildtypes_block = transformed_code[transformed_buildtypes_start:transformed_code.rfind("}")]
    assert transformed_buildtypes_block == orig_buildtypes_block, "buildTypes block was mutated/polluted!"

    # 5. Commented blocks and string literals remain untouched
    assert '// defaultConfig {\n//     ndk {\n//         abiFilters \'arm64-v8a\'\n//     }\n//     targetSdkVersion 33\n// }' in transformed_code
    assert 'buildConfigField "String", "DECOY_CONFIG", \'"defaultConfig { ndk { abiFilters \\\'arm64-v8a\\\' } }"\'' in transformed_code

    # 6. Rollback restores exact byte-identical preimage
    res_rb = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rb.returncode == 0, f"Rollback failed: {res_rb.stderr}"
    assert build_gradle.read_bytes() == orig_bytes


def test_adversarial_complex_multi_flavor_kotlin_isolation(tmp_path):
    """
    Stress-test a deeply nested Kotlin DSL build.gradle.kts containing:
    - Multiple flavor dimensions with create(...) syntax
    - Multiple buildTypes with getByName(...) syntax
    - Existing ndk blocks with += listOf(...) in flavors and buildTypes
    - Verify defaultConfig receives arm64-v8a while all flavors/buildTypes are 100% UNTOUCHED.
    """
    proj = tmp_path / "adv_complex_kotlin_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    (proj / "android" / "gradle.properties").write_text("org.gradle.jvmargs=-Xmx4096m\n")

    build_gradle_kts = android_dir / "build.gradle.kts"
    original_code = """// Kotlin DSL multi-flavor test
android {
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.adversarial.kotlin"
        minSdk = 24
        targetSdk = 35
        versionCode = 100
        versionName = "3.0.0"
    }

    flavorDimensions += listOf("tier", "channel")

    productFlavors {
        create("free") {
            dimension = "tier"
            applicationIdSuffix = ".free"
            ndk {
                abiFilters += listOf("armeabi-v7a")
            }
        }
        create("premium") {
            dimension = "tier"
            applicationIdSuffix = ".premium"
            ndk {
                abiFilters += listOf("x86_64")
            }
        }
        create("googlePlay") {
            dimension = "channel"
        }
        create("sideload") {
            dimension = "channel"
            ndk {
                abiFilters += listOf("x86", "armeabi-v7a")
            }
        }
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = true
            ndk {
                abiFilters += listOf("armeabi-v7a")
            }
        }
        getByName("debug") {
            applicationIdSuffix = ".debug"
            ndk {
                abiFilters += listOf("x86")
            }
        }
        create("qa") {
            initWith(getByName("debug"))
            ndk {
                abiFilters += listOf("x86_64")
            }
        }
    }
}
"""
    build_gradle_kts.write_text(original_code, newline="\n")
    orig_bytes = build_gradle_kts.read_bytes()

    flavors_start = original_code.find("productFlavors {")
    buildtypes_start = original_code.find("buildTypes {")
    orig_flavors_block = original_code[flavors_start:buildtypes_start]
    orig_buildtypes_block = original_code[buildtypes_start:original_code.rfind("}")]

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Configurator failed: {res.stderr}\nSTDOUT:\n{res.stdout}"

    transformed_code = build_gradle_kts.read_text(encoding="utf-8")

    assert "compileSdk = 34" in transformed_code
    assert "targetSdk = 34" in transformed_code

    dc_start = transformed_code.find("defaultConfig {")
    flavors_new_start = transformed_code.find("flavorDimensions")
    default_config_text = transformed_code[dc_start:flavors_new_start]
    assert 'abiFilters += listOf("arm64-v8a")' in default_config_text

    # Flavors must be byte-exact
    transformed_flavors_start = transformed_code.find("productFlavors {")
    transformed_buildtypes_start = transformed_code.find("buildTypes {")
    transformed_flavors_block = transformed_code[transformed_flavors_start:transformed_buildtypes_start]
    assert transformed_flavors_block == orig_flavors_block, "Kotlin productFlavors block was mutated!"

    # BuildTypes must be byte-exact
    transformed_buildtypes_block = transformed_code[transformed_buildtypes_start:transformed_code.rfind("}")]
    assert transformed_buildtypes_block == orig_buildtypes_block, "Kotlin buildTypes block was mutated!"

    # Rollback
    res_rb = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res_rb.returncode == 0
    assert build_gradle_kts.read_bytes() == orig_bytes


# ==============================================================================
# Adversarial Challenge 2: 100 Consecutive Invocations & SHA256 Stability
# ==============================================================================

def test_adversarial_100_consecutive_runs_sha256_stability(tmp_path):
    """
    Execute 100 consecutive runs of flutter_project_config.sh on:
    - Multi-flavor Groovy project starting WITHOUT gradle.properties
    - Verify SHA256 of gradle.properties and build.gradle are 100% stable from run 1 to run 100.
    - Verify zero duplication of ndk or arm64-v8a lines.
    - Verify rollback restores preimage (run 0) byte-for-byte.
    """
    proj = tmp_path / "adv_100_runs_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    build_gradle = android_dir / "build.gradle"
    build_gradle.write_text("""android {
    compileSdkVersion 35
    defaultConfig {
        applicationId "com.example.stress100"
        minSdkVersion 21
    }
    productFlavors {
        demo {
            ndk { abiFilters 'x86' }
        }
    }
}
""", newline="\n")
    orig_gradle_bytes = build_gradle.read_bytes()

    gradle_props = proj / "android" / "gradle.properties"
    assert not gradle_props.exists()

    # First invocation
    res1 = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
    assert res1.returncode == 0, f"Run 1 failed: {res1.stderr}"

    assert gradle_props.exists()
    props_hash_1 = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
    gradle_hash_1 = hashlib.sha256(build_gradle.read_bytes()).hexdigest()

    # Runs 2 through 100
    for run_idx in range(2, 101):
        res_i = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
        assert res_i.returncode == 0, f"Run {run_idx} failed: {res_i.stderr}"

        curr_props_hash = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
        curr_gradle_hash = hashlib.sha256(build_gradle.read_bytes()).hexdigest()

        assert curr_props_hash == props_hash_1, f"gradle.properties SHA256 drifted on run {run_idx}"
        assert curr_gradle_hash == gradle_hash_1, f"build.gradle SHA256 drifted on run {run_idx}"

    # Verify no duplication in contents
    props_content = gradle_props.read_text()
    assert props_content.count("android.aapt2FromMavenOverride=") == 1

    gradle_content = build_gradle.read_text()
    assert gradle_content.count("arm64-v8a") == 1
    assert gradle_content.count("compileSdkVersion") == 1
    assert gradle_content.count("targetSdkVersion") == 1

    # Rollback must restore run 0 state
    res_rb = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], capture_output=True, text=True)
    assert res_rb.returncode == 0
    assert not gradle_props.exists(), "Auto-created gradle.properties was not cleaned on rollback!"
    assert build_gradle.read_bytes() == orig_gradle_bytes


# ==============================================================================
# Adversarial Challenge 3: Transactional Error Trap Rollback & Mid-Flight Abortion
# ==============================================================================

def test_adversarial_error_trap_unclosed_brace_abort(tmp_path):
    """
    Test transactional abortion when build.gradle contains an unclosed brace.
    Ensures that modifications made to gradle.properties prior to failure are rolled back,
    and all .bak files are deleted.
    """
    proj = tmp_path / "adv_trap_unclosed_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    orig_props_content = "# Pre-existing gradle.properties\norg.gradle.jvmargs=-Xmx2048m\n"
    gradle_props.write_text(orig_props_content, newline="\n")

    build_gradle = android_dir / "build.gradle"
    # Valid compileSdkVersion so preimage check passes, but unclosed brace triggers parser exception
    build_gradle.write_text("android {\n    compileSdkVersion 35\n    defaultConfig {\n", newline="\n")
    orig_gradle_bytes = build_gradle.read_bytes()

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0, "Expected non-zero return code on syntax failure"
    assert "Unclosed braces" in res.stderr or "Syntax error" in res.stderr
    assert "Rolling back transactional changes" in res.stderr

    # Verify preimage restored
    assert gradle_props.read_text(encoding="utf-8") == orig_props_content
    assert build_gradle.read_bytes() == orig_gradle_bytes

    # Verify NO leftover .bak or state files
    assert not (proj / "android" / "gradle.properties.bak").exists()
    assert not (proj / "android" / "app" / "build.gradle.bak").exists()
    assert not (proj / ".termux_project_config.json").exists()


def test_adversarial_error_trap_created_file_abort(tmp_path):
    """
    Test that when gradle.properties is NEWLY created and subsequent step fails,
    the newly created gradle.properties is completely deleted (zero orphan files).
    """
    proj = tmp_path / "adv_trap_created_file_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    assert not gradle_props.exists()

    build_gradle = android_dir / "build.gradle"
    # Unmatched closing brace triggers ValueError in parse_scopes
    build_gradle.write_text("android {\n    compileSdkVersion 35\n}}\n", newline="\n")

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0

    # Created gradle.properties MUST BE DELETED
    assert not gradle_props.exists(), "Newly created gradle.properties was orphaned after failure!"
    assert not (proj / "android" / "app" / "build.gradle.bak").exists()
    assert not (proj / ".termux_project_config.json").exists()


def test_adversarial_non_flutter_dir_error_handling(tmp_path):
    """Test invocation against non-Flutter folder with no android/ directory."""
    non_flutter = tmp_path / "empty_dir"
    non_flutter.mkdir()

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(non_flutter)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "is not a valid Flutter Android project" in res.stderr
    assert len(list(non_flutter.iterdir())) == 0


def test_adversarial_preimage_failure_leaves_no_artifacts(tmp_path):
    """Test invocation against android/ project with empty build.gradle."""
    proj = tmp_path / "preimage_fail_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    (proj / "android" / "gradle.properties").write_text("test=1\n")
    (android_dir / "build.gradle").write_text("// Empty gradle file\n")

    res = subprocess.run(
        ["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "Preimage verification failed" in res.stderr

    # Zero .bak or state files
    assert not (proj / "android" / "gradle.properties.bak").exists()
    assert not (proj / "android" / "app" / "build.gradle.bak").exists()
    assert not (proj / ".termux_project_config.json").exists()
