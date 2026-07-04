#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

AAPT2_PATH="${1:-/data/data/com.termux/files/usr/bin/aapt2}"
SPLIT_SELECT_PATH="${2:-}"

echo "=== Checking AAPT2 Binary: $AAPT2_PATH ==="
if [ ! -x "$AAPT2_PATH" ]; then
    echo "❌ AAPT2 binary not executable or not found."
    exit 1
fi

# Check static linkage or dynamic library dependencies
echo "Checking linkage dependencies..."
if command -v readelf >/dev/null 2>&1; then
    if ! readelf -h "$AAPT2_PATH" >/dev/null 2>&1; then
        echo "⚠️ Warning: $AAPT2_PATH is not a valid ELF binary (might be a wrapper script). Skipping linkage check." >&2
    else
        if readelf -d "$AAPT2_PATH" 2>/dev/null | grep -q -F 'libprotobuf'; then
            if [ "${ALLOW_DYNAMIC_AAPT2:-0}" != "1" ]; then
                echo "❌ Error: AAPT2 is dynamically linked to libprotobuf. Linkage validation failed." >&2
                echo "   Rolling-release updates might break this binary. Set ALLOW_DYNAMIC_AAPT2=1 to bypass." >&2
                exit 1
            fi
            echo "⚠️ Warning: AAPT2 is dynamically linked to libprotobuf (allowed via ALLOW_DYNAMIC_AAPT2=1)." >&2
        else
            echo "✅ AAPT2 is statically linked or protobuf-independent."
        fi
    fi
else
    echo "⚠️ Warning: readelf is not installed. Skipping linkage dependency check." >&2
fi

# Test runtime execution
echo "Executing version command..."
if "$AAPT2_PATH" version; then
    echo "✅ AAPT2 runtime execution passed."
else
    echo "❌ AAPT2 runtime execution failed."
    exit 1
fi

# Verify split-select if path provided
if [ -n "$SPLIT_SELECT_PATH" ]; then
    echo "=== Checking split-select Binary: $SPLIT_SELECT_PATH ==="
    if [ ! -x "$SPLIT_SELECT_PATH" ]; then
        echo "❌ split-select is not executable or missing."
        exit 1
    fi
    echo "✅ split-select is executable."

    # Test split-select runtime execution without arguments
    echo "Testing split-select runtime execution..."
    exit_code=0
    "$SPLIT_SELECT_PATH" >/dev/null 2>&1 || exit_code=$?
    if [ "$exit_code" -eq 0 ] || [ "$exit_code" -eq 1 ] || [ "$exit_code" -eq 2 ]; then
        echo "✅ split-select runtime execution passed."
    else
        echo "❌ split-select runtime execution failed (exit code: $exit_code)."
        exit 1
    fi
fi
