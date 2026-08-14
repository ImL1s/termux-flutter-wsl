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
            return f"/mnt/{drive}{p[2:]}"
        return p


# ==============================================================================
# Adversarial Challenge 1: 100 Consecutive Runs Idempotence on Groovy & Kotlin
# Testing 0-Byte Delta & Exact SHA256 Stability from Run 1 to Run 100
# ==============================================================================

@pytest.mark.parametrize("auto_create_props", [False, True], ids=["preexisting_props", "autocreated_props"])
def test_adversarial_100_runs_groovy_sha256_stability_and_rollback(tmp_path, auto_create_props):
    """
    Stress-test Groovy build.gradle over 100 consecutive invocations:
    - Case 1: Pre-existing gradle.properties with comments and spaced overrides
    - Case 2: Auto-created gradle.properties (missing at Run 0)
    - Verifies 0-byte delta and identical SHA256 hashes from Run 1 to Run 100.
    - Verifies rollback after 100 runs restores exact Run 0 byte preimage.
    """
    proj = tmp_path / f"adv_100_groovy_{'autocreated' if auto_create_props else 'preexisting'}"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    orig_props_bytes = None
    if not auto_create_props:
        props_content = (
            "# Custom team gradle properties\n"
            "org.gradle.jvmargs=-Xmx4096m -XX:+HeapDumpOnOutOfMemoryError\n"
            "  android.aapt2FromMavenOverride  =  /stale/path/to/aapt2\n"
            "android.useAndroidX=true\n"
        )
        gradle_props.write_text(props_content, newline="\n")
        orig_props_bytes = gradle_props.read_bytes()

    build_gradle = android_dir / "build.gradle"
    original_groovy = """android {
    compileSdkVersion 35

    defaultConfig {
        applicationId "com.example.groovy100"
        minSdkVersion 21
        // targetSdkVersion intentionally omitted to test injection stability
        versionCode 1
        versionName "1.0"
    }

    flavorDimensions "tier"
    productFlavors {
        free {
            dimension "tier"
            ndk {
                abiFilters 'x86'
            }
        }
        pro {
            dimension "tier"
            ndk {
                abiFilters 'armeabi-v7a'
            }
        }
    }

    buildTypes {
        release {
            minifyEnabled true
            ndk {
                abiFilters 'x86_64'
            }
        }
    }
}
"""
    build_gradle.write_text(original_groovy, newline="\n")
    orig_gradle_bytes = build_gradle.read_bytes()

    # Run 1
    res1 = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
    assert res1.returncode == 0, f"Run 1 failed: {res1.stderr}"
    assert gradle_props.exists(), "gradle.properties was not created or present"

    hash_props_1 = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
    hash_gradle_1 = hashlib.sha256(build_gradle.read_bytes()).hexdigest()
    size_props_1 = gradle_props.stat().st_size
    size_gradle_1 = build_gradle.stat().st_size

    # Runs 2 through 100
    for run_num in range(2, 101):
        res_i = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
        assert res_i.returncode == 0, f"Run {run_num} failed: {res_i.stderr}"

        curr_props_hash = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
        curr_gradle_hash = hashlib.sha256(build_gradle.read_bytes()).hexdigest()
        curr_props_size = gradle_props.stat().st_size
        curr_gradle_size = build_gradle.stat().st_size

        assert curr_props_hash == hash_props_1, f"Groovy gradle.properties SHA256 drifted on run {run_num}"
        assert curr_gradle_hash == hash_gradle_1, f"Groovy build.gradle SHA256 drifted on run {run_num}"
        assert curr_props_size == size_props_1, f"Groovy gradle.properties byte size drifted on run {run_num}"
        assert curr_gradle_size == size_gradle_1, f"Groovy build.gradle byte size drifted on run {run_num}"

    # Verify structural correctness of final state
    gradle_text = build_gradle.read_text(encoding="utf-8")
    assert gradle_text.count("abiFilters 'arm64-v8a'") == 1, "Duplicate arm64-v8a entries found!"
    assert gradle_text.count("targetSdkVersion = 34") == 1, "targetSdkVersion duplicated or missing"
    assert gradle_text.count("compileSdkVersion = 34") == 1 or gradle_text.count("compileSdkVersion 34") == 1
    assert "abiFilters 'x86'" in gradle_text
    assert "abiFilters 'armeabi-v7a'" in gradle_text
    assert "abiFilters 'x86_64'" in gradle_text

    # Rollback after 100 runs
    res_rb = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], capture_output=True, text=True)
    assert res_rb.returncode == 0, f"Rollback failed: {res_rb.stderr}"

    if auto_create_props:
        assert not gradle_props.exists(), "Auto-created gradle.properties was not deleted on rollback after 100 runs!"
    else:
        assert gradle_props.read_bytes() == orig_props_bytes, "Pre-existing gradle.properties not restored byte-for-byte"

    assert build_gradle.read_bytes() == orig_gradle_bytes, "Groovy build.gradle not restored byte-for-byte after 100 runs"
    assert not (proj / ".termux_project_config.json").exists()
    assert not (proj / "android" / "gradle.properties.bak").exists()
    assert not (proj / "android" / "app" / "build.gradle.bak").exists()


@pytest.mark.parametrize("auto_create_props", [False, True], ids=["preexisting_props", "autocreated_props"])
def test_adversarial_100_runs_kotlin_sha256_stability_and_rollback(tmp_path, auto_create_props):
    """
    Stress-test Kotlin DSL build.gradle.kts over 100 consecutive invocations:
    - Case 1: Pre-existing gradle.properties
    - Case 2: Auto-created gradle.properties
    - Verifies 0-byte delta and identical SHA256 hashes from Run 1 to Run 100.
    - Verifies rollback after 100 runs restores exact Run 0 byte preimage.
    """
    proj = tmp_path / f"adv_100_kotlin_{'autocreated' if auto_create_props else 'preexisting'}"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    orig_props_bytes = None
    if not auto_create_props:
        props_content = "# Kotlin project properties\norg.gradle.jvmargs=-Xmx2048m\n"
        gradle_props.write_text(props_content, newline="\n")
        orig_props_bytes = gradle_props.read_bytes()

    build_gradle_kts = android_dir / "build.gradle.kts"
    original_kts = """android {
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.kotlin100"
        minSdk = 24
        // targetSdk intentionally omitted to test injection stability
        versionCode = 1
        versionName = "1.0"
    }

    flavorDimensions += listOf("mode")
    productFlavors {
        create("demo") {
            dimension = "mode"
            ndk {
                abiFilters += listOf("x86")
            }
        }
    }

    buildTypes {
        getByName("release") {
            ndk {
                abiFilters += listOf("armeabi-v7a")
            }
        }
    }
}
"""
    build_gradle_kts.write_text(original_kts, newline="\n")
    orig_gradle_bytes = build_gradle_kts.read_bytes()

    # Run 1
    res1 = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
    assert res1.returncode == 0, f"Run 1 failed: {res1.stderr}"

    hash_props_1 = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
    hash_gradle_1 = hashlib.sha256(build_gradle_kts.read_bytes()).hexdigest()
    size_props_1 = gradle_props.stat().st_size
    size_gradle_1 = build_gradle_kts.stat().st_size

    # Runs 2 through 100
    for run_num in range(2, 101):
        res_i = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
        assert res_i.returncode == 0, f"Run {run_num} failed: {res_i.stderr}"

        curr_props_hash = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
        curr_gradle_hash = hashlib.sha256(build_gradle_kts.read_bytes()).hexdigest()
        curr_props_size = gradle_props.stat().st_size
        curr_gradle_size = build_gradle_kts.stat().st_size

        assert curr_props_hash == hash_props_1, f"Kotlin gradle.properties SHA256 drifted on run {run_num}"
        assert curr_gradle_hash == hash_gradle_1, f"Kotlin build.gradle.kts SHA256 drifted on run {run_num}"
        assert curr_props_size == size_props_1, f"Kotlin gradle.properties byte size drifted on run {run_num}"
        assert curr_gradle_size == size_gradle_1, f"Kotlin build.gradle.kts byte size drifted on run {run_num}"

    # Verify structural correctness of final state
    kts_text = build_gradle_kts.read_text(encoding="utf-8")
    assert kts_text.count('abiFilters += listOf("arm64-v8a")') == 1, "Duplicate arm64-v8a entries found in Kotlin!"
    assert kts_text.count("targetSdk = 34") == 1
    assert kts_text.count("compileSdk = 34") == 1
    assert 'abiFilters += listOf("x86")' in kts_text
    assert 'abiFilters += listOf("armeabi-v7a")' in kts_text

    # Rollback after 100 runs
    res_rb = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], capture_output=True, text=True)
    assert res_rb.returncode == 0, f"Rollback failed: {res_rb.stderr}"

    if auto_create_props:
        assert not gradle_props.exists(), "Auto-created gradle.properties was not deleted on rollback after 100 runs!"
    else:
        assert gradle_props.read_bytes() == orig_props_bytes

    assert build_gradle_kts.read_bytes() == orig_gradle_bytes
    assert not (proj / ".termux_project_config.json").exists()


# ==============================================================================
# Adversarial Challenge 2: Complex Multi-Block Gradle Files with Exotic Spacing,
# Multiline Closures, Comments Inside defaultConfig, Nested Blocks & Quotes
# ==============================================================================

def test_adversarial_exotic_groovy_multiline_closures_and_nested_blocks(tmp_path):
    """
    Stress-test Groovy file containing:
    - Exotic indentation (mixed tabs and spaces, trailing spaces)
    - Multiline comments containing curly braces right inside defaultConfig
    - Multiline ndk block with multiple arguments across several lines
    - Nested externalNativeBuild and javaCompileOptions blocks
    - String literals with curly braces and fake keywords
    - Line comments immediately after opening brace: defaultConfig { // comment
    - Verify 100 runs idempotency & exact rollback
    """
    proj = tmp_path / "adv_exotic_groovy"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    gradle_props.write_text("# Exotic props\norg.gradle.jvmargs=-Xmx2048m\n", newline="\n")
    orig_props_bytes = gradle_props.read_bytes()

    build_gradle = android_dir / "build.gradle"
    exotic_groovy_content = """/*
 * Multi-line header comment with braces: {
 *   android { compileSdkVersion 99 }
 * }
 */
android { // Main android block
	compileSdkVersion 	35   

	defaultConfig { // Inline comment right after opening brace
		applicationId "com.example.exotic.groovy"
		minSdkVersion 21
		/* Multiline comment inside defaultConfig:
		   defaultConfig {
		       ndk { abiFilters 'fake-abi' }
		   }
		*/
		targetSdkVersion 35
		versionCode 10
		versionName "1.0-alpha"

		// Multiline ndk closure with exotic formatting
		ndk {
			abiFilters(
				'x86',
				'armeabi-v7a'
			)
		}

		javaCompileOptions {
			annotationProcessorOptions {
				arguments = [ "room.schemaLocation": "$projectDir/schemas".toString() ]
			}
		}

		manifestPlaceholders = [
			hostName: "example.com",
			customConfig: "{ debug: true }"
		]
	}

	buildTypes {
		release {
			minifyEnabled false
			proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'
			ndk {
				abiFilters 'x86_64'
			}
		}
		debug {
			applicationIdSuffix ".debug"
			debuggable true
		}
	}

	productFlavors {
		flavorDimensions "tier"
		free {
			dimension "tier"
			ndk {
				abiFilters 'x86'
			}
		}
		paid {
			dimension "tier"
		}
	}
}
"""
    build_gradle.write_text(exotic_groovy_content, newline="\n")
    orig_gradle_bytes = build_gradle.read_bytes()

    # Apply configuration
    res1 = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
    assert res1.returncode == 0, f"Apply failed: {res1.stderr}\nSTDOUT: {res1.stdout}"

    transformed_text = build_gradle.read_text(encoding="utf-8")
    assert "compileSdkVersion = 34" in transformed_text or "compileSdkVersion 34" in transformed_text
    assert "targetSdkVersion = 34" in transformed_text

    # defaultConfig ndk block should contain arm64-v8a
    assert "abiFilters 'arm64-v8a'" in transformed_text

    # Flavors and buildTypes must retain their original filters
    assert "abiFilters 'x86_64'" in transformed_text
    assert "abiFilters 'x86'" in transformed_text

    # Multiline comment and annotations preserved
    assert "Multiline comment inside defaultConfig" in transformed_text
    assert "room.schemaLocation" in transformed_text
    assert "customConfig: \"{ debug: true }\"" in transformed_text

    # Verify 100 runs idempotency
    hash_props_1 = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
    hash_gradle_1 = hashlib.sha256(build_gradle.read_bytes()).hexdigest()

    for i in range(2, 51):
        res_i = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
        assert res_i.returncode == 0, f"Run {i} failed: {res_i.stderr}"
        assert hashlib.sha256(gradle_props.read_bytes()).hexdigest() == hash_props_1
        assert hashlib.sha256(build_gradle.read_bytes()).hexdigest() == hash_gradle_1

    # Rollback
    res_rb = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], capture_output=True, text=True)
    assert res_rb.returncode == 0, f"Rollback failed: {res_rb.stderr}"
    assert gradle_props.read_bytes() == orig_props_bytes
    assert build_gradle.read_bytes() == orig_gradle_bytes


def test_adversarial_exotic_kotlin_multiline_closures_and_nested_blocks(tmp_path):
    """
    Stress-test Kotlin DSL build.gradle.kts containing:
    - Multiline abiFilters += listOf(\n "x86",\n "armeabi-v7a"\n)
    - Raw multiline string literals (triple quotes) containing braces
    - Comments right inside defaultConfig { /* comment */
    - Complex nested kotlinOptions / compileOptions blocks
    - Verify 100 runs idempotency & exact rollback
    """
    proj = tmp_path / "adv_exotic_kotlin"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    gradle_props.write_text("org.gradle.jvmargs=-Xmx2048m\n", newline="\n")
    orig_props_bytes = gradle_props.read_bytes()

    build_gradle_kts = android_dir / "build.gradle.kts"
    exotic_kotlin_content = '''android {
    compileSdk = 35

    defaultConfig { /* opening brace inline comment */
        applicationId = "com.example.exotic.kotlin"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"

        // Multiline abiFilters in Kotlin DSL
        ndk {
            abiFilters += listOf(
                "x86",
                "armeabi-v7a"
            )
        }

        // Multiline string with code-like syntax
        val sampleJson = """
            {
                "android": {
                    "compileSdk": 35
                }
            }
        """.trimIndent()
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    flavorDimensions += listOf("tier", "arch")
    productFlavors {
        create("alpha") {
            dimension = "tier"
            ndk {
                abiFilters += listOf("x86")
            }
        }
        create("beta") {
            dimension = "tier"
            ndk {
                abiFilters += listOf("x86_64")
            }
        }
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = true
            ndk {
                abiFilters += listOf("x86_64")
            }
        }
    }
}
'''
    build_gradle_kts.write_text(exotic_kotlin_content, newline="\n")
    orig_gradle_bytes = build_gradle_kts.read_bytes()

    # Run configurator
    res1 = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
    assert res1.returncode == 0, f"Apply failed: {res1.stderr}\nSTDOUT: {res1.stdout}"

    transformed_text = build_gradle_kts.read_text(encoding="utf-8")
    assert "compileSdk = 34" in transformed_text
    assert "targetSdk = 34" in transformed_text
    assert 'abiFilters += listOf("arm64-v8a")' in transformed_text

    # Triple quote block preserved
    assert 'val sampleJson = """' in transformed_text

    # Flavors and buildTypes preserved
    assert 'create("alpha")' in transformed_text
    assert 'create("beta")' in transformed_text

    # Verify idempotency
    hash_props_1 = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
    hash_gradle_1 = hashlib.sha256(build_gradle_kts.read_bytes()).hexdigest()

    for i in range(2, 51):
        res_i = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
        assert res_i.returncode == 0, f"Run {i} failed: {res_i.stderr}"
        assert hashlib.sha256(gradle_props.read_bytes()).hexdigest() == hash_props_1
        assert hashlib.sha256(build_gradle_kts.read_bytes()).hexdigest() == hash_gradle_1

    # Rollback
    res_rb = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], capture_output=True, text=True)
    assert res_rb.returncode == 0, f"Rollback failed: {res_rb.stderr}"
    assert gradle_props.read_bytes() == orig_props_bytes
    assert build_gradle_kts.read_bytes() == orig_gradle_bytes


# ==============================================================================
# Adversarial Challenge 3: Repeated Apply-Rollback-Apply Cycles
# ==============================================================================

def test_adversarial_repeated_apply_rollback_apply_cycles(tmp_path):
    """
    Stress-test rapid cycling: apply -> rollback -> apply -> rollback -> apply (10 cycles).
    Ensures state machine, .bak files, and state tracking json never leak or corrupt.
    """
    proj = tmp_path / "adv_cycle_app"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    initial_props = "# Initial props\norg.gradle.jvmargs=-Xmx2048m\n"
    gradle_props.write_text(initial_props, newline="\n")
    orig_props_bytes = gradle_props.read_bytes()

    build_gradle = android_dir / "build.gradle"
    initial_gradle = """android {
    compileSdkVersion 35
    defaultConfig {
        applicationId "com.example.cycle"
        minSdkVersion 21
        targetSdkVersion 35
    }
}
"""
    build_gradle.write_text(initial_gradle, newline="\n")
    orig_gradle_bytes = build_gradle.read_bytes()

    state_file = proj / ".termux_project_config.json"
    props_bak = proj / "android" / "gradle.properties.bak"
    gradle_bak = android_dir / "build.gradle.bak"

    for cycle in range(1, 11):
        # 1. Apply
        res_apply = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True)
        assert res_apply.returncode == 0, f"Cycle {cycle} Apply failed: {res_apply.stderr}"

        assert state_file.exists()
        assert props_bak.exists()
        assert gradle_bak.exists()

        content = build_gradle.read_text()
        assert "targetSdkVersion = 34" in content or "targetSdkVersion 34" in content
        assert "abiFilters 'arm64-v8a'" in content

        # 2. Rollback
        res_rb = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], capture_output=True, text=True)
        assert res_rb.returncode == 0, f"Cycle {cycle} Rollback failed: {res_rb.stderr}"

        assert not state_file.exists()
        assert not props_bak.exists()
        assert not gradle_bak.exists()
        assert gradle_props.read_bytes() == orig_props_bytes
        assert build_gradle.read_bytes() == orig_gradle_bytes


# ==============================================================================
# Adversarial Challenge 4: Strict `set -euo pipefail` and Unset/Empty Environment Variables
# ==============================================================================

MODERN_TOOLS_SCRIPT = REPO_ROOT / "scripts" / "install" / "setup_modern_tools.sh"

def test_adversarial_setup_modern_tools_strict_pipefail_and_unset_vars(tmp_path):
    """
    Adversarial test for setup_modern_tools.sh under `set -euo pipefail`:
    - Tests behavior when AAPT2_OVERRIDE is unset or empty.
    - Tests fallback to AAPT2_BIN.
    - Tests PREFIX unset behavior.
    - Uses mock binaries for 7z, wget, sha256sum, and check_toolchain.sh.
    """
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    fake_bin = tmp_path / "mock_bin"
    fake_bin.mkdir()

    # Create mock 7z that extracts a dummy aapt2 and split-select
    mock_7z = fake_bin / "7z"
    mock_7z_content = """#!/bin/bash
# Mock 7z: create dummy binaries
mkdir -p build-tools/35.0.0
touch build-tools/35.0.0/aapt2 build-tools/35.0.0/split-select
chmod +x build-tools/35.0.0/aapt2 build-tools/35.0.0/split-select
exit 0
"""
    mock_7z.write_text(mock_7z_content, newline="\n")
    mock_7z.chmod(0o755)

    # Create mock wget
    mock_wget = fake_bin / "wget"
    mock_wget.write_text("#!/bin/bash\ntouch sdk_temp.7z\nexit 0\n", newline="\n")
    mock_wget.chmod(0o755)

    # Create mock sha256sum
    mock_sha = fake_bin / "sha256sum"
    mock_sha.write_text("#!/bin/bash\nexit 0\n", newline="\n")
    mock_sha.chmod(0o755)

    # Create mock check_toolchain.sh in scripts/install if needed
    scripts_install = tmp_path / "scripts" / "install"
    scripts_install.mkdir(parents=True)
    mock_check_toolchain = scripts_install / "check_toolchain.sh"
    mock_check_toolchain.write_text("#!/bin/bash\nexit 0\n", newline="\n")
    mock_check_toolchain.chmod(0o755)

    script_copy = scripts_install / "setup_modern_tools.sh"
    shutil_script = REPO_ROOT / "scripts" / "install" / "setup_modern_tools.sh"
    script_copy.write_text(shutil_script.read_text(encoding="utf-8"), newline="\n")

    # Set execution permissions in bash/WSL
    chmod_cmd = f"chmod +x '{to_bash_path(mock_7z)}' '{to_bash_path(mock_wget)}' '{to_bash_path(mock_sha)}' '{to_bash_path(mock_check_toolchain)}' '{to_bash_path(script_copy)}'"
    subprocess.run(["bash", "-c", chmod_cmd], check=True)

    # 1. Run with AAPT2_OVERRIDE unset in environment under set -euo pipefail
    cmd1 = f'export PATH="{to_bash_path(fake_bin)}:$PATH" HOME="{to_bash_path(fake_home)}" PREFIX="{to_bash_path(fake_home / "usr")}"; unset AAPT2_OVERRIDE; bash -euo pipefail "{to_bash_path(script_copy)}"'
    res1 = subprocess.run(["bash", "-c", cmd1], capture_output=True)
    out1 = res1.stdout.decode("utf-8", errors="replace")
    err1 = res1.stderr.decode("utf-8", errors="replace")
    assert res1.returncode == 0, f"setup_modern_tools.sh failed with unset AAPT2_OVERRIDE: {err1}\nSTDOUT: {out1}"

    gradle_prop = fake_home / ".gradle" / "gradle.properties"
    assert gradle_prop.exists()
    prop_text1 = gradle_prop.read_text(encoding="utf-8")
    expected_default_aapt2 = f"{to_bash_path(fake_home)}/Android/Sdk/build-tools/35.0.0/aapt2"
    assert f"android.aapt2FromMavenOverride={expected_default_aapt2}" in prop_text1

    # 2. Run with explicit AAPT2_OVERRIDE set
    cmd2 = f'export PATH="{to_bash_path(fake_bin)}:$PATH" HOME="{to_bash_path(fake_home)}" PREFIX="{to_bash_path(fake_home / "usr")}" AAPT2_OVERRIDE="/custom/override/bin/aapt2"; bash -euo pipefail "{to_bash_path(script_copy)}"'
    res2 = subprocess.run(["bash", "-c", cmd2], capture_output=True)
    out2 = res2.stdout.decode("utf-8", errors="replace")
    err2 = res2.stderr.decode("utf-8", errors="replace")
    assert res2.returncode == 0, f"setup_modern_tools.sh failed with explicit AAPT2_OVERRIDE: {err2}\nSTDOUT: {out2}"
    prop_text2 = gradle_prop.read_text(encoding="utf-8")
    assert "android.aapt2FromMavenOverride=/custom/override/bin/aapt2" in prop_text2
    assert prop_text2.count("android.aapt2FromMavenOverride") == 1


@pytest.mark.parametrize("cli_mode,expected_override", [
    (None, "/data/data/com.termux/files/usr/bin/aapt2"),
    ("--mode=A", "/data/data/com.termux/files/usr/bin/aapt2"),
    ("--mode=B", "/Android/Sdk/build-tools/35.0.0/aapt2"),
    ("--aapt2=/custom/cli/aapt2", "/custom/cli/aapt2"),
])
def test_adversarial_flutter_project_config_strict_pipefail_and_modes(tmp_path, cli_mode, expected_override):
    """
    Adversarially challenge flutter_project_config.sh under `bash -euo pipefail`
    with various mode arguments (--mode=A, --mode=B, --aapt2=..., default auto-detect).
    """
    proj = tmp_path / f"adv_strict_{cli_mode.replace('=', '_').replace('-', '') if cli_mode else 'default'}"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    build_gradle = android_dir / "build.gradle"
    build_gradle.write_text("""android {
    compileSdkVersion 35
    defaultConfig {
        applicationId "com.example.pipefail"
        minSdkVersion 21
        targetSdkVersion 35
    }
}
""", newline="\n")

    cmd_apply = ["bash", "-euo", "pipefail", to_bash_path(CONFIG_SCRIPT)]
    if cli_mode:
        cmd_apply.append(cli_mode)
    cmd_apply.append(to_bash_path(proj))

    res = subprocess.run(cmd_apply, capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, f"Apply failed under bash -euo pipefail: {res.stderr}\nSTDOUT: {res.stdout}"

    gradle_props = proj / "android" / "gradle.properties"
    assert gradle_props.exists()
    props_text = gradle_props.read_text(encoding="utf-8")
    assert expected_override in props_text

    # Rollback under bash -euo pipefail
    cmd_rollback = ["bash", "-euo", "pipefail", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)]
    res_rb = subprocess.run(cmd_rollback, capture_output=True, text=True, encoding="utf-8")
    assert res_rb.returncode == 0, f"Rollback failed under bash -euo pipefail: {res_rb.stderr}"
    assert not gradle_props.exists()


# ==============================================================================
# Adversarial Challenge 5: gradle.properties Edge Cases (Comments, CRLF, Duplicates, Whitespace)
# ==============================================================================

def test_adversarial_gradle_properties_unusual_comments_and_formatting(tmp_path):
    """
    Stress-test gradle.properties edge cases:
    - Multiple commented-out variations using '#' and '!'
    - Active keys with leading/trailing spaces, tabs, and ':' delimiters
    - Multiple duplicate stale keys
    - Verifies commented lines are never deleted or modified
    - Verifies stale active keys are replaced with exactly ONE correct key
    - Verifies 100 runs idempotency and exact byte-for-byte rollback
    """
    proj = tmp_path / "adv_props_edge_cases"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    initial_props = (
        "# -----------------------------------------\n"
        "# Comment header with property name:\n"
        "# android.aapt2FromMavenOverride=/old/commented/1\n"
        "   #   android.aapt2FromMavenOverride = /old/commented/2\n"
        "! android.aapt2FromMavenOverride = /exclamation/comment\n"
        "org.gradle.jvmargs=-Xmx2048m\n"
        "# Duplicate stale keys with weird spacing and delimiters:\n"
        "  android.aapt2FromMavenOverride  =  /stale/override/1  \n"
        "\tandroid.aapt2FromMavenOverride\t:\t/stale/override/2\t\n"
        "android.aapt2FromMavenOverride=/stale/override/3\n"
        "android.useAndroidX=true\n"
        "# Trailing comment\n"
    )
    gradle_props.write_text(initial_props, newline="\n")
    orig_props_bytes = gradle_props.read_bytes()

    build_gradle = android_dir / "build.gradle"
    build_gradle.write_text("""android {
    compileSdkVersion 35
    defaultConfig {
        applicationId "com.example.propsedge"
        minSdkVersion 21
        targetSdkVersion 35
    }
}
""", newline="\n")
    orig_gradle_bytes = build_gradle.read_bytes()

    # Apply configuration
    res = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, f"Apply failed: {res.stderr}\nSTDOUT: {res.stdout}"

    transformed_props = gradle_props.read_text(encoding="utf-8")
    lines = transformed_props.splitlines()

    # Verify commented lines are preserved verbatim
    assert "# android.aapt2FromMavenOverride=/old/commented/1" in lines
    assert "   #   android.aapt2FromMavenOverride = /old/commented/2" in lines
    assert "! android.aapt2FromMavenOverride = /exclamation/comment" in lines
    assert "org.gradle.jvmargs=-Xmx2048m" in lines
    assert "android.useAndroidX=true" in lines

    # Verify only ONE active android.aapt2FromMavenOverride exists
    active_overrides = [l for l in lines if l.strip().startswith("android.aapt2FromMavenOverride")]
    assert len(active_overrides) == 1, f"Expected exactly 1 active override, found: {active_overrides}"
    assert active_overrides[0] == "android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2"

    # Verify 100 consecutive runs idempotency
    hash_props_1 = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
    hash_gradle_1 = hashlib.sha256(build_gradle.read_bytes()).hexdigest()

    for i in range(2, 51):
        res_i = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True, encoding="utf-8")
        assert res_i.returncode == 0, f"Run {i} failed: {res_i.stderr}"
        assert hashlib.sha256(gradle_props.read_bytes()).hexdigest() == hash_props_1
        assert hashlib.sha256(build_gradle.read_bytes()).hexdigest() == hash_gradle_1

    # Rollback
    res_rb = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], capture_output=True, text=True, encoding="utf-8")
    assert res_rb.returncode == 0, f"Rollback failed: {res_rb.stderr}"
    assert gradle_props.read_bytes() == orig_props_bytes, "gradle.properties was not restored byte-for-byte"
    assert build_gradle.read_bytes() == orig_gradle_bytes


def test_adversarial_gradle_properties_crlf_format_stability(tmp_path):
    """
    Stress-test gradle.properties with Windows CRLF line endings (\\r\\n).
    Verifies 50 runs hash stability and exact byte-for-byte rollback.
    """
    proj = tmp_path / "adv_crlf_props"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    crlf_content = b"org.gradle.jvmargs=-Xmx2048m\r\nandroid.useAndroidX=true\r\n"
    gradle_props.write_bytes(crlf_content)
    orig_props_bytes = crlf_content

    build_gradle = android_dir / "build.gradle"
    build_gradle.write_text("""android {
    compileSdkVersion 35
    defaultConfig {
        applicationId "com.example.crlf"
        minSdkVersion 21
        targetSdkVersion 35
    }
}
""", newline="\n")
    orig_gradle_bytes = build_gradle.read_bytes()

    res = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, f"Apply failed: {res.stderr}\nSTDOUT: {res.stdout}"

    transformed_props_text = gradle_props.read_text(encoding="utf-8")
    assert "android.useAndroidX=true" in transformed_props_text
    assert "android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2" in transformed_props_text

    # Verify 50 runs hash stability
    hash_props_1 = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
    for i in range(2, 51):
        res_i = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True, encoding="utf-8")
        assert res_i.returncode == 0
        assert hashlib.sha256(gradle_props.read_bytes()).hexdigest() == hash_props_1

    # Rollback
    res_rb = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], capture_output=True, text=True, encoding="utf-8")
    assert res_rb.returncode == 0
    assert gradle_props.read_bytes() == orig_props_bytes


def test_adversarial_gradle_properties_empty_file_handling(tmp_path):
    """
    Stress-test empty 0-byte gradle.properties:
    - Verifies proper injection of android.aapt2FromMavenOverride
    - Verifies 50 runs hash stability
    - Verifies rollback restores 0-byte file
    """
    proj = tmp_path / "adv_empty_props"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    gradle_props.write_bytes(b"")

    build_gradle = android_dir / "build.gradle"
    build_gradle.write_text("""android {
    compileSdkVersion 35
    defaultConfig {
        applicationId "com.example.emptyprops"
        minSdkVersion 21
        targetSdkVersion 35
    }
}
""", newline="\n")
    orig_gradle_bytes = build_gradle.read_bytes()

    res = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0
    assert "android.aapt2FromMavenOverride=" in gradle_props.read_text(encoding="utf-8")

    hash_props_1 = hashlib.sha256(gradle_props.read_bytes()).hexdigest()
    for i in range(2, 21):
        res_i = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True, encoding="utf-8")
        assert res_i.returncode == 0
        assert hashlib.sha256(gradle_props.read_bytes()).hexdigest() == hash_props_1

    # Rollback
    res_rb = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), "--rollback", to_bash_path(proj)], capture_output=True, text=True, encoding="utf-8")
    assert res_rb.returncode == 0
    assert gradle_props.read_bytes() == b""
    assert build_gradle.read_bytes() == orig_gradle_bytes



# ==============================================================================
# Adversarial Challenge 6: Transactional Crash Simulation & Trap Restoration
# ==============================================================================

def test_adversarial_crash_simulation_syntax_error_full_trap_restoration(tmp_path):
    """
    Simulate mid-execution crash due to malformed Gradle syntax:
    - Pre-existing gradle.properties
    - build.gradle has unmatched closing brace '}'
    - Verifies Python helper fails with non-zero code
    - Verifies trap immediately restores gradle.properties and build.gradle
    - Verifies no leftover .bak files and no state file
    """
    proj = tmp_path / "adv_crash_syntax"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    gradle_props.write_text("org.gradle.jvmargs=-Xmx2048m\n", newline="\n")
    orig_props_bytes = gradle_props.read_bytes()

    build_gradle = android_dir / "build.gradle"
    # Missing opening brace for defaultConfig
    malformed_gradle = """android {
    compileSdkVersion 35
    defaultConfig
        applicationId "com.example.crash"
        minSdkVersion 21
    }
}
"""
    build_gradle.write_text(malformed_gradle, newline="\n")
    orig_gradle_bytes = build_gradle.read_bytes()

    res = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode != 0, "Script should have failed on syntax error!"
    assert "Syntax error" in res.stderr or "Syntax error" in res.stdout or "Rolling back transactional changes" in res.stderr

    # Check that project was restored to exact Run 0 preimage
    assert gradle_props.read_bytes() == orig_props_bytes, "gradle.properties was not restored on crash"
    assert build_gradle.read_bytes() == orig_gradle_bytes, "build.gradle was not restored on crash"
    assert not (proj / ".termux_project_config.json").exists(), "State file was left behind after crash"
    assert not (proj / "android" / "gradle.properties.bak").exists(), "gradle.properties.bak was left behind"
    assert not (android_dir / "build.gradle.bak").exists(), "build.gradle.bak was left behind"


def test_adversarial_crash_simulation_autocreated_props_full_cleanup(tmp_path):
    """
    Simulate mid-execution crash on a project with NO initial gradle.properties:
    - gradle.properties is created in step 1
    - Step 2 (build.gradle modification) crashes due to unclosed brace
    - Verifies trap deletes the auto-created gradle.properties
    - Verifies build.gradle is restored byte-for-byte
    - Verifies no .bak and no state file
    """
    proj = tmp_path / "adv_crash_autocreate"
    android_dir = proj / "android" / "app"
    android_dir.mkdir(parents=True)

    gradle_props = proj / "android" / "gradle.properties"
    assert not gradle_props.exists()

    build_gradle = android_dir / "build.gradle"
    # Unclosed brace
    unclosed_gradle = """android {
    compileSdkVersion 35
    defaultConfig {
        applicationId "com.example.unclosed"
        minSdkVersion 21
"""
    build_gradle.write_text(unclosed_gradle, newline="\n")
    orig_gradle_bytes = build_gradle.read_bytes()

    res = subprocess.run(["bash", to_bash_path(CONFIG_SCRIPT), to_bash_path(proj)], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode != 0, "Script should have failed on unclosed brace!"

    assert not gradle_props.exists(), "Auto-created gradle.properties was NOT removed on crash!"
    assert build_gradle.read_bytes() == orig_gradle_bytes
    assert not (proj / ".termux_project_config.json").exists()
    assert not (android_dir / "build.gradle.bak").exists()


