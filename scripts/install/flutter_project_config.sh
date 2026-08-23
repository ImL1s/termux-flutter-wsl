#!/usr/bin/env bash
# scripts/install/flutter_project_config.sh
# Configure a Flutter project for Termux environment (Mode A / Mode B compatible & transactional)

set -e

if command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
    PY_BIN="python3"
elif command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
    PY_BIN="python"
else
    echo "Error: python3 is required for flutter_project_config.sh (AST scope parsing and state serialization)." >&2
    exit 1
fi

ROLLBACK=false
SPECIFIED_MODE=""
CUSTOM_AAPT2=""
POSITIONAL_ARGS=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --rollback)
            ROLLBACK=true
            shift
            ;;
        --mode=*)
            SPECIFIED_MODE="${1#*=}"
            shift
            ;;
        --aapt2=*)
            CUSTOM_AAPT2="${1#*=}"
            shift
            ;;
        -*)
            echo "Usage: $0 [--rollback] [--mode=A|B] [--aapt2=<path>] <flutter_project_path>" >&2
            exit 1
            ;;
        *)
            POSITIONAL_ARGS+=("$1")
            shift
            ;;
    esac
done

if [ "${#POSITIONAL_ARGS[@]}" -ne 1 ]; then
    echo "Usage: $0 [--rollback] [--mode=A|B] [--aapt2=<path>] <flutter_project_path>"
    exit 1
fi

PROJ="${POSITIONAL_ARGS[0]}"
PROJ="${PROJ//\\//}"
if [[ "$PROJ" =~ ^([a-zA-Z]):/(.*) ]]; then
    _drive="${BASH_REMATCH[1]}"
    _drive="$(echo "$_drive" | tr '[:upper:]' '[:lower:]')"
    if [ -d "/mnt/${_drive}/${BASH_REMATCH[2]}" ]; then
        PROJ="/mnt/${_drive}/${BASH_REMATCH[2]}"
    else
        PROJ="/${_drive}/${BASH_REMATCH[2]}"
    fi
elif [ ! -d "$PROJ" ]; then
    if [ -d "/mnt$PROJ" ]; then
        PROJ="/mnt$PROJ"
    elif [[ "$PROJ" =~ ^/mnt/(.*) ]] && [ -d "/${BASH_REMATCH[1]}" ]; then
        PROJ="/${BASH_REMATCH[1]}"
    fi
fi

if [ ! -d "$PROJ/android" ]; then
    echo "Error: $PROJ is not a valid Flutter Android project (missing android/ directory)." >&2
    exit 1
fi

STATE_FILE="$PROJ/.termux_project_config.json"
GRADLE_PROPS="$PROJ/android/gradle.properties"
APP_BUILD_GRADLE="$PROJ/android/app/build.gradle"
APP_BUILD_GRADLE_KTS="$PROJ/android/app/build.gradle.kts"

# Handle Rollback
if [ "$ROLLBACK" = "true" ]; then
    echo "Rolling back Termux project configuration for $PROJ..."

    # Read created files from state file if available
    CREATED_FILES=()
    if [ -f "$STATE_FILE" ]; then
        CREATED_FILES=($("$PY_BIN" -c '
import json, sys, os
p = sys.argv[1]
if len(p) > 2 and p[0] == "/" and p[2] == "/" and p[1].isalpha() and (os.name == "nt" or not os.path.exists(p)):
    p = f"{p[1]}:{p[2:]}"
try:
    with open(p) as f:
        data = json.load(f)
    print(" ".join(data.get("created_files", [])))
except Exception:
    pass
' "$STATE_FILE" 2>/dev/null || true))
    fi

    for file in "$GRADLE_PROPS" "$APP_BUILD_GRADLE" "$APP_BUILD_GRADLE_KTS"; do
        if [ -f "${file}.bak" ]; then
            cp "${file}.bak" "$file"
            rm -f "${file}.bak"
            echo "Restored $file from backup"
        fi
    done

    for rel_created in "${CREATED_FILES[@]}"; do
        created_path="$PROJ/$rel_created"
        if [ -f "$created_path" ] && [ ! -f "${created_path}.bak" ]; then
            rm -f "$created_path"
            echo "Removed created file $created_path"
        fi
    done

    rm -f "$STATE_FILE"
    echo "Rollback complete."
    exit 0
fi

# Determine build.gradle file
TARGET_GRADLE=""
if [ -f "$APP_BUILD_GRADLE_KTS" ]; then
    TARGET_GRADLE="$APP_BUILD_GRADLE_KTS"
elif [ -f "$APP_BUILD_GRADLE" ]; then
    TARGET_GRADLE="$APP_BUILD_GRADLE"
fi

if [ -z "$TARGET_GRADLE" ]; then
    echo "Could not find build.gradle or build.gradle.kts in $PROJ/android/app/" >&2
    exit 1
fi

# Preimage verification: check that build.gradle contains compileSdk or defaultConfig
TARGET_CONTENT=$(cat "$TARGET_GRADLE")
if ! echo "$TARGET_CONTENT" | grep -E -q "compileSdk|compileSdkVersion|defaultConfig"; then
    echo "Error: Preimage verification failed for $TARGET_GRADLE: missing compileSdk/compileSdkVersion/defaultConfig block." >&2
    exit 1
fi

# Transactional State Tracking & Trap Setup
TRANSACTION_SUCCESS=false
TRACKED_BACKUPS=()
TRACKED_CREATED=()
MODIFIED_FILES=()
CREATED_FILES=()

STATE_FILE_PREEXISTED=false
if [ -f "$STATE_FILE" ]; then
    STATE_FILE_PREEXISTED=true
    cp "$STATE_FILE" "${STATE_FILE}.bak"
    TRACKED_BACKUPS+=("${STATE_FILE}.bak")
fi

cleanup_on_error() {
    local exit_code=$?
    if [ "$TRANSACTION_SUCCESS" != "true" ]; then
        echo "Configuration interrupted or failed (exit code $exit_code). Rolling back transactional changes..." >&2
        for bak in "${TRACKED_BACKUPS[@]}"; do
            orig="${bak%.bak}"
            if [ -f "$bak" ]; then
                cp "$bak" "$orig" 2>/dev/null || true
                rm -f "$bak" 2>/dev/null || true
            fi
        done
        for created in "${TRACKED_CREATED[@]}"; do
            rm -f "$created" 2>/dev/null || true
        done
        if [ "$STATE_FILE_PREEXISTED" != "true" ]; then
            rm -f "$STATE_FILE" 2>/dev/null || true
        fi
        echo "Transactional rollback complete. Project restored." >&2
    fi
}

trap cleanup_on_error EXIT ERR INT TERM

# Resolve AAPT2 Path (Mode A vs Mode B)
PREFIX_PATH="${PREFIX:-/data/data/com.termux/files/usr}"
HOME_PATH="${HOME:-/data/data/com.termux/files/home}"
MODE_A_AAPT2="$PREFIX_PATH/bin/aapt2"
MODE_B_AAPT2="$HOME_PATH/Android/Sdk/build-tools/35.0.0/aapt2"
SYSTEM_BT_AAPT2="$PREFIX_PATH/opt/android-sdk/build-tools/35.0.0/aapt2"

if [ -n "$CUSTOM_AAPT2" ]; then
    TERMUX_AAPT2="$CUSTOM_AAPT2"
elif [ -n "${AAPT2_OVERRIDE:-}" ]; then
    TERMUX_AAPT2="$AAPT2_OVERRIDE"
elif [ -n "${TERMUX_AAPT2_PATH:-}" ]; then
    TERMUX_AAPT2="$TERMUX_AAPT2_PATH"
elif [ "$SPECIFIED_MODE" = "B" ]; then
    if [ -x "$MODE_B_AAPT2" ]; then
        TERMUX_AAPT2="$MODE_B_AAPT2"
    elif [ -x "$SYSTEM_BT_AAPT2" ]; then
        TERMUX_AAPT2="$SYSTEM_BT_AAPT2"
    else
        TERMUX_AAPT2="$MODE_B_AAPT2"
    fi
elif [ "$SPECIFIED_MODE" = "A" ]; then
    TERMUX_AAPT2="$MODE_A_AAPT2"
else
    # Auto-detect Mode B if valid static binary exists, else Mode A
    if [ -x "$MODE_B_AAPT2" ] && [ ! -L "$MODE_B_AAPT2" ]; then
        TERMUX_AAPT2="$MODE_B_AAPT2"
    elif [ -x "$SYSTEM_BT_AAPT2" ] && [ ! -L "$SYSTEM_BT_AAPT2" ]; then
        TERMUX_AAPT2="$SYSTEM_BT_AAPT2"
    else
        TERMUX_AAPT2="$MODE_A_AAPT2"
    fi
fi

# 1. Update or Create gradle.properties
EXISTING_CREATED=()
if [ -f "$STATE_FILE" ]; then
    EXISTING_CREATED=($("$PY_BIN" -c '
import json, sys, os
p = sys.argv[1]
if len(p) > 2 and p[0] == "/" and p[2] == "/" and p[1].isalpha() and (os.name == "nt" or not os.path.exists(p)):
    p = f"{p[1]}:{p[2:]}"
try:
    with open(p) as f:
        data = json.load(f)
    print(" ".join(data.get("created_files", [])))
except Exception:
    pass
' "$STATE_FILE" 2>/dev/null || true))
fi

is_previously_created=false
for c in "${EXISTING_CREATED[@]}"; do
    if [ "$c" = "android/gradle.properties" ]; then
        is_previously_created=true
        break
    fi
done

if [ ! -f "$GRADLE_PROPS" ]; then
    echo "android.aapt2FromMavenOverride=$TERMUX_AAPT2" > "$GRADLE_PROPS"
    TRACKED_CREATED+=("$GRADLE_PROPS")
    CREATED_FILES+=("android/gradle.properties")
    echo "Created $GRADLE_PROPS with android.aapt2FromMavenOverride=$TERMUX_AAPT2"
elif [ "$is_previously_created" = "true" ]; then
    CREATED_FILES+=("android/gradle.properties")
    sed -i -E '/^[[:space:]]*android\.aapt2FromMavenOverride[[:space:]]*[=:]/d' "$GRADLE_PROPS"
    echo "android.aapt2FromMavenOverride=$TERMUX_AAPT2" >> "$GRADLE_PROPS"
    echo "Set android.aapt2FromMavenOverride=$TERMUX_AAPT2 in $GRADLE_PROPS"
else
    if [ ! -f "${GRADLE_PROPS}.bak" ]; then
        cp "$GRADLE_PROPS" "${GRADLE_PROPS}.bak"
        TRACKED_BACKUPS+=("${GRADLE_PROPS}.bak")
    fi
    # Remove any existing (spaced, colon or stale) override entry safely
    sed -i -E '/^[[:space:]]*android\.aapt2FromMavenOverride[[:space:]]*[=:]/d' "$GRADLE_PROPS"
    echo "android.aapt2FromMavenOverride=$TERMUX_AAPT2" >> "$GRADLE_PROPS"
    MODIFIED_FILES+=("android/gradle.properties")
    echo "Set android.aapt2FromMavenOverride=$TERMUX_AAPT2 in $GRADLE_PROPS"
fi

# 2. Backup and Update build.gradle / build.gradle.kts
if [ ! -f "${TARGET_GRADLE}.bak" ]; then
    cp "$TARGET_GRADLE" "${TARGET_GRADLE}.bak"
    TRACKED_BACKUPS+=("${TARGET_GRADLE}.bak")
fi

# Call Python helper for scope-aware Gradle transformation
"$PY_BIN" - "$TARGET_GRADLE" << 'EOF'
import sys
import re
import os

gradle_file = sys.argv[1]
if len(gradle_file) > 2 and gradle_file[0] == '/' and gradle_file[2] == '/' and gradle_file[1].isalpha():
    if os.name == 'nt' or not os.path.exists(gradle_file):
        gradle_file = f"{gradle_file[1]}:{gradle_file[2:]}"
with open(gradle_file, 'r', encoding='utf-8') as f:
    text = f.read()

is_kts = gradle_file.endswith('.kts')

def parse_scopes(src):
    n = len(src)
    i = 0
    in_line_comment = False
    in_block_comment = False
    in_str = None

    scope_stack = [] # (ident, open_brace_idx, parent_path)
    blocks = [] # (name, full_path, start_idx, end_idx)

    while i < n:
        if in_line_comment:
            if src[i] == '\n':
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if src[i:i+2] == '*/':
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue
        if in_str:
            if in_str in ('"""', "'''"):
                if src[i:i+3] == in_str:
                    in_str = None
                    i += 3
                else:
                    if src[i] == '\\':
                        i += 2
                    else:
                        i += 1
            else:
                if src[i] == in_str:
                    in_str = None
                    i += 1
                elif src[i] == '\\':
                    i += 2
                else:
                    i += 1
            continue

        if src[i:i+2] == '//':
            in_line_comment = True
            i += 2
            continue
        if src[i:i+2] == '/*':
            in_block_comment = True
            i += 2
            continue
        if src[i:i+3] in ('"""', "'''"):
            in_str = src[i:i+3]
            i += 3
            continue
        if src[i] in ('"', "'"):
            in_str = src[i]
            i += 1
            continue

        if src[i] == '{':
            j = i - 1
            while j >= 0 and src[j] in ' \t\r\n':
                j -= 1
            end_ident = j + 1
            if j >= 0 and src[j] == ')':
                paren_depth = 1
                j -= 1
                while j >= 0 and paren_depth > 0:
                    if src[j] == ')':
                        paren_depth += 1
                    elif src[j] == '(':
                        paren_depth -= 1
                    j -= 1
                while j >= 0 and src[j] in ' \t\r\n':
                    j -= 1
            while j >= 0 and (src[j].isalnum() or src[j] in '._-'):
                j -= 1
            start_ident = j + 1
            ident = src[start_ident:end_ident].strip()
            if not ident:
                ident = 'anonymous'

            current_path = tuple(s[0] for s in scope_stack)
            scope_stack.append((ident, i, current_path))
            i += 1
            continue

        if src[i] == '}':
            if not scope_stack:
                raise ValueError(f"Syntax error: Unmatched closing brace '}}' at offset {i} in {gradle_file}")
            name, start_idx, parent_path = scope_stack.pop()
            full_path = parent_path + (name,)
            blocks.append((name, full_path, start_idx, i))
            i += 1
            continue

        i += 1

    if scope_stack:
        raise ValueError(f"Syntax error: Unclosed braces ({len(scope_stack)}) in {gradle_file}")

    return blocks

lines = text.split('\n')
blocks = parse_scopes(text)

android_block = None
default_config_block = None
dc_ndk_block = None
root_ndk_block = None

for name, path, start_idx, end_idx in blocks:
    if name == 'android' and len(path) == 1:
        android_block = (start_idx, end_idx)
    elif name == 'defaultConfig' and ('android' in path or len(path) == 1):
        default_config_block = (start_idx, end_idx)
    elif name == 'ndk':
        if 'defaultConfig' in path:
            dc_ndk_block = (start_idx, end_idx)
        elif 'android' in path and not any(p in path for p in ('buildTypes', 'productFlavors')):
            root_ndk_block = (start_idx, end_idx)

compile_sdk_pattern = re.compile(r'^([ \t]*)(compileSdkVersion|compileSdk)[ \t]*=?[ \t]*(.*)$')
target_sdk_pattern = re.compile(r'^([ \t]*)(targetSdkVersion|targetSdk)[ \t]*=?[ \t]*(.*)$')

compile_sdk_found = False
target_sdk_found = False

new_lines = []
current_offset = 0

for line in lines:
    line_len = len(line) + 1
    line_start = current_offset
    line_end = current_offset + len(line)
    current_offset += line_len

    stripped = line.strip()
    if stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*'):
        new_lines.append(line)
        continue

    m_comp = compile_sdk_pattern.match(line)
    if m_comp and (android_block is None or (line_start >= android_block[0] and line_end <= android_block[1])):
        is_in_subblock = False
        for name, path, s_idx, e_idx in blocks:
            if name in ('defaultConfig', 'buildTypes', 'productFlavors') and line_start >= s_idx and line_end <= e_idx:
                is_in_subblock = True
                break
        if not is_in_subblock:
            compile_sdk_found = True
            indent = m_comp.group(1)
            key = m_comp.group(2)
            new_lines.append(f"{indent}{key} = 34")
            continue

    m_targ = target_sdk_pattern.match(line)
    if m_targ and default_config_block is not None and (line_start >= default_config_block[0] and line_end <= default_config_block[1]):
        if dc_ndk_block is None or not (line_start >= dc_ndk_block[0] and line_end <= dc_ndk_block[1]):
            target_sdk_found = True
            indent = m_targ.group(1)
            key = m_targ.group(2)
            new_lines.append(f"{indent}{key} = 34")
            continue

    new_lines.append(line)

text = '\n'.join(new_lines)
print(f"Updated compileSdk and targetSdk to 34 in {gradle_file}")

# Re-parse scopes
blocks = parse_scopes(text)
default_config_block = None
dc_ndk_block = None
root_ndk_block = None
android_block = None

for name, path, start_idx, end_idx in blocks:
    if name == 'android' and len(path) == 1:
        android_block = (start_idx, end_idx)
    elif name == 'defaultConfig' and ('android' in path or len(path) == 1):
        default_config_block = (start_idx, end_idx)
    elif name == 'ndk':
        if 'defaultConfig' in path:
            dc_ndk_block = (start_idx, end_idx)
        elif 'android' in path and not any(p in path for p in ('buildTypes', 'productFlavors')):
            root_ndk_block = (start_idx, end_idx)

# If targetSdk was missing from defaultConfig, inject it
if not target_sdk_found and default_config_block is not None:
    open_brace_pos = default_config_block[0]
    targ_line = "        targetSdk = 34\n" if is_kts else "        targetSdkVersion = 34\n"
    nl_pos = text.find('\n', open_brace_pos)
    if nl_pos != -1:
        text = text[:nl_pos+1] + targ_line + text[nl_pos+1:]
    else:
        text = text[:open_brace_pos+1] + "\n" + targ_line + text[open_brace_pos+1:]

    blocks = parse_scopes(text)
    default_config_block = None
    dc_ndk_block = None
    root_ndk_block = None
    for name, path, start_idx, end_idx in blocks:
        if name == 'defaultConfig' and ('android' in path or len(path) == 1):
            default_config_block = (start_idx, end_idx)
        elif name == 'ndk':
            if 'defaultConfig' in path:
                dc_ndk_block = (start_idx, end_idx)
            elif 'android' in path and not any(p in path for p in ('buildTypes', 'productFlavors')):
                root_ndk_block = (start_idx, end_idx)

target_ndk_block = dc_ndk_block if dc_ndk_block is not None else root_ndk_block
abi_line = '            abiFilters += listOf("arm64-v8a")' if is_kts else "            abiFilters 'arm64-v8a'"

if target_ndk_block is not None:
    s_idx, e_idx = target_ndk_block
    ndk_inner = text[s_idx:e_idx+1]

    abi_pattern_groovy = re.compile(r'^[ \t]*abiFilters(?:\s*\(|\s+|=|\.add|\+=)[^\n]*$', re.MULTILINE)
    abi_pattern_kotlin = re.compile(r'^[ \t]*abiFilters(?:\s*\+=|\.addAll|\.add|\s*=)[^\n]*$', re.MULTILINE)
    active_pattern = abi_pattern_kotlin if is_kts else abi_pattern_groovy

    matches = list(active_pattern.finditer(ndk_inner))
    if matches:
        matched_texts = [m.group(0).strip() for m in matches]
        exact_target = 'abiFilters += listOf("arm64-v8a")' if is_kts else "abiFilters 'arm64-v8a'"
        is_exact = (len(matches) == 1 and (matched_texts[0] == exact_target or (not is_kts and matched_texts[0] == "abiFilters('arm64-v8a')")))
        if is_exact:
            print(f"arm64-v8a ABI filter already canonically present in {gradle_file}")
        else:
            # Replace all existing abiFilters lines in ndk block with the single canonical line
            new_ndk_inner = active_pattern.sub('', ndk_inner)
            open_pos = new_ndk_inner.find('{')
            nl_pos = new_ndk_inner.find('\n', open_pos)
            if nl_pos != -1:
                new_ndk_inner = new_ndk_inner[:nl_pos+1] + abi_line + '\n' + new_ndk_inner[nl_pos+1:]
            else:
                new_ndk_inner = new_ndk_inner[:open_pos+1] + '\n' + abi_line + '\n' + new_ndk_inner[open_pos+1:]
            text = text[:s_idx] + new_ndk_inner + text[e_idx+1:]
            print(f"Canonicalized abiFilters strictly to arm64-v8a in {gradle_file}")
    else:
        open_brace_pos = target_ndk_block[0]
        nl_pos = text.find('\n', open_brace_pos)
        if nl_pos != -1:
            text = text[:nl_pos+1] + abi_line + '\n' + text[nl_pos+1:]
        else:
            text = text[:open_brace_pos+1] + '\n' + abi_line + '\n' + text[open_brace_pos+1:]
        print(f"Added abiFilters to existing ndk block in {gradle_file}")
else:
    if default_config_block is not None:
        open_brace_pos = default_config_block[0]
        nl_pos = text.find('\n', open_brace_pos)
        block_to_inject = f"        ndk {{\n{abi_line}\n        }}\n"
        if nl_pos != -1:
            text = text[:nl_pos+1] + block_to_inject + text[nl_pos+1:]
        else:
            text = text[:open_brace_pos+1] + '\n' + block_to_inject + text[open_brace_pos+1:]
        print(f"Added ndk block with abiFilters to {gradle_file}")
    elif android_block is not None:
        open_brace_pos = android_block[0]
        nl_pos = text.find('\n', open_brace_pos)
        target_sdk_str = "        targetSdk = 34\n" if is_kts else "        targetSdkVersion = 34\n"
        block_to_inject = f"    defaultConfig {{\n{target_sdk_str}        ndk {{\n{abi_line}\n        }}\n    }}\n"
        if nl_pos != -1:
            text = text[:nl_pos+1] + block_to_inject + text[nl_pos+1:]
        else:
            text = text[:open_brace_pos+1] + '\n' + block_to_inject + text[open_brace_pos+1:]
        print(f"Added defaultConfig and ndk block with canonical arm64-v8a abiFilters to {gradle_file}")

with open(gradle_file, 'w', encoding='utf-8', newline='\n') as f:
    f.write(text)
EOF

if [ "$TARGET_GRADLE" = "$APP_BUILD_GRADLE_KTS" ]; then
    MODIFIED_FILES+=("android/app/build.gradle.kts")
else
    MODIFIED_FILES+=("android/app/build.gradle")
fi

# Write state file
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
"$PY_BIN" - "$STATE_FILE" "$TIMESTAMP" "$TERMUX_AAPT2" "${#MODIFIED_FILES[@]}" "${MODIFIED_FILES[@]}" "${CREATED_FILES[@]}" << 'PYSTATE'
import sys, json, os

state_file = sys.argv[1]
if len(state_file) > 2 and state_file[0] == '/' and state_file[2] == '/' and state_file[1].isalpha():
    if os.name == 'nt' or not os.path.exists(state_file):
        state_file = f"{state_file[1]}:{state_file[2:]}"
timestamp = sys.argv[2]
aapt2_path = sys.argv[3]
num_mod = int(sys.argv[4])
rest = sys.argv[5:]
mod_files = rest[:num_mod]
created_files = rest[num_mod:]

data = {
  "status": "configured",
  "timestamp": timestamp,
  "modified_files": mod_files,
  "created_files": created_files,
  "aapt2_path": aapt2_path
}

with open(state_file, 'w', encoding='utf-8', newline='\n') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
PYSTATE

if [ -f "${STATE_FILE}.bak" ]; then
    rm -f "${STATE_FILE}.bak" 2>/dev/null || true
fi

TRANSACTION_SUCCESS=true
echo "Done. $PROJ is configured for Termux."
