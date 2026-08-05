#!/usr/bin/env bash
# scripts/install/flutter_project_config.sh
# Configure a Flutter project for Termux environment

set -e

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <flutter_project_path>"
    exit 1
fi

PROJ="$1"

if [ ! -d "$PROJ/android" ]; then
    echo "Error: $PROJ is not a valid Flutter Android project."
    exit 1
fi

GRADLE_PROPS="$PROJ/android/gradle.properties"
if [ -f "$GRADLE_PROPS" ]; then
    if ! grep -q "android.aapt2FromMavenOverride" "$GRADLE_PROPS"; then
        echo "" >> "$GRADLE_PROPS"
        echo "android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2" >> "$GRADLE_PROPS"
        echo "Added android.aapt2FromMavenOverride to $GRADLE_PROPS"
    else
        echo "android.aapt2FromMavenOverride already present in $GRADLE_PROPS"
    fi
fi

APP_BUILD_GRADLE="$PROJ/android/app/build.gradle"
APP_BUILD_GRADLE_KTS="$PROJ/android/app/build.gradle.kts"

inject_abi_filters() {
    local file="$1"
    local ext="${file##*.}"
    local abi_line=""

    if [ "$ext" = "kts" ]; then
        abi_line="            abiFilters += listOf(\"arm64-v8a\")"
    else
        abi_line="            abiFilters 'arm64-v8a'"
    fi

    if grep -q "ndk {" "$file"; then
        if ! grep -q "abiFilters" "$file"; then
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

    # Replace hardcoded versions or flutter.compileSdkVersion with 34
    sed -i -E 's/^([[:space:]]*)(compileSdk|compileSdkVersion)[[:space:]]*=?.*/\1\2 = 34/g' "$file"
    sed -i -E 's/^([[:space:]]*)(targetSdk|targetSdkVersion)[[:space:]]*=?.*/\1\2 = 34/g' "$file"

    echo "Updated compileSdk and targetSdk to 34 in $file"
}

if [ -f "$APP_BUILD_GRADLE_KTS" ]; then
    echo "Processing $APP_BUILD_GRADLE_KTS..."
    update_sdk_version "$APP_BUILD_GRADLE_KTS"
    inject_abi_filters "$APP_BUILD_GRADLE_KTS"
elif [ -f "$APP_BUILD_GRADLE" ]; then
    echo "Processing $APP_BUILD_GRADLE..."
    update_sdk_version "$APP_BUILD_GRADLE"
    inject_abi_filters "$APP_BUILD_GRADLE"
else
    echo "Could not find build.gradle or build.gradle.kts in $PROJ/android/app/"
fi

echo "Done. $PROJ is configured for Termux."
