#!/usr/bin/env bash
# scripts/install/flutter_project_config.sh
# Configure a Flutter project for Termux environment

set -e

ROLLBACK=false
if [ "$1" = "--rollback" ]; then
    ROLLBACK=true
    shift
fi

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 [--rollback] <flutter_project_path>"
    exit 1
fi

PROJ="$1"

if [ ! -d "$PROJ/android" ]; then
    echo "Error: $PROJ is not a valid Flutter Android project."
    exit 1
fi

STATE_FILE="$PROJ/.termux_project_config.json"

if [ "$ROLLBACK" = "true" ]; then
    echo "Rolling back Termux project configuration for $PROJ..."
    for file in "$PROJ/android/gradle.properties" "$PROJ/android/app/build.gradle" "$PROJ/android/app/build.gradle.kts"; do
        if [ -f "${file}.bak" ]; then
            cp "${file}.bak" "$file"
            rm -f "${file}.bak"
            echo "Restored $file from backup"
        fi
    done
    rm -f "$STATE_FILE"
    echo "Rollback complete."
    exit 0
fi

GRADLE_PROPS="$PROJ/android/gradle.properties"
APP_BUILD_GRADLE="$PROJ/android/app/build.gradle"
APP_BUILD_GRADLE_KTS="$PROJ/android/app/build.gradle.kts"

# Determine build.gradle file
TARGET_GRADLE=""
if [ -f "$APP_BUILD_GRADLE_KTS" ]; then
    TARGET_GRADLE="$APP_BUILD_GRADLE_KTS"
elif [ -f "$APP_BUILD_GRADLE" ]; then
    TARGET_GRADLE="$APP_BUILD_GRADLE"
fi

if [ -z "$TARGET_GRADLE" ]; then
    echo "Could not find build.gradle or build.gradle.kts in $PROJ/android/app/"
    exit 1
fi

# Preimage verification: check that build.gradle contains compileSdk or defaultConfig
TARGET_CONTENT=$(cat "$TARGET_GRADLE")
if ! echo "$TARGET_CONTENT" | grep -E -q "compileSdk|compileSdkVersion|defaultConfig"; then
    echo "Warning: Preimage verification failed for $TARGET_GRADLE: missing compileSdk/compileSdkVersion/defaultConfig"
    echo "Done. $PROJ is configured for Termux."
    exit 0
fi

MODIFIED_FILES=()

# Backup and update gradle.properties
if [ -f "$GRADLE_PROPS" ]; then
    if [ ! -f "${GRADLE_PROPS}.bak" ]; then
        cp "$GRADLE_PROPS" "${GRADLE_PROPS}.bak"
    fi
    if ! grep -q "android.aapt2FromMavenOverride" "$GRADLE_PROPS"; then
        echo "" >> "$GRADLE_PROPS"
        echo "android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2" >> "$GRADLE_PROPS"
        echo "Added android.aapt2FromMavenOverride to $GRADLE_PROPS"
    fi
    MODIFIED_FILES+=("android/gradle.properties")
fi

# Backup and update build.gradle / build.gradle.kts
if [ ! -f "${TARGET_GRADLE}.bak" ]; then
    cp "$TARGET_GRADLE" "${TARGET_GRADLE}.bak"
fi

inject_abi_filters() {
    local file="$1"
    local ext="${file##*.}"
    local abi_line=""

    if [ "$ext" = "kts" ]; then
        abi_line="            abiFilters += listOf(\"arm64-v8a\")"
    else
        abi_line="            abiFilters 'arm64-v8a'"
    fi

    if grep -q "arm64-v8a" "$file"; then
        echo "arm64-v8a ABI filter already present in $file"
        return 0
    fi

    if grep -q "ndk {" "$file"; then
        if grep -q "abiFilters" "$file"; then
            sed -i "/abiFilters/a \\$abi_line" "$file"
            echo "Added arm64-v8a to existing abiFilters block in $file"
        else
            sed -i "/ndk {/a \\$abi_line" "$file"
            echo "Added abiFilters to existing ndk block in $file"
        fi
    else
        sed -i "/defaultConfig {/a \        ndk {\n$abi_line\n        }" "$file"
        echo "Added ndk block with abiFilters to $file"
    fi
}

update_sdk_version() {
    local file="$1"
    sed -i -E 's/^([[:space:]]*)(compileSdk|compileSdkVersion)[[:space:]]*=?.*/\1\2 = 34/g' "$file"
    sed -i -E 's/^([[:space:]]*)(targetSdk|targetSdkVersion)[[:space:]]*=?.*/\1\2 = 34/g' "$file"
    echo "Updated compileSdk and targetSdk to 34 in $file"
}

update_sdk_version "$TARGET_GRADLE"
inject_abi_filters "$TARGET_GRADLE"

if [ "$TARGET_GRADLE" = "$APP_BUILD_GRADLE_KTS" ]; then
    MODIFIED_FILES+=("android/app/build.gradle.kts")
else
    MODIFIED_FILES+=("android/app/build.gradle")
fi

# Write state file
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
MOD_FILES_JSON=$(python3 -c "import json, sys; print(json.dumps(sys.argv[1:]))" "${MODIFIED_FILES[@]}")
cat > "$STATE_FILE" << EOF
{
  "status": "configured",
  "timestamp": "$TIMESTAMP",
  "modified_files": $MOD_FILES_JSON
}
EOF

echo "Done. $PROJ is configured for Termux."
