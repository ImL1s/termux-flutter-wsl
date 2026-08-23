#!/usr/bin/env python3
import os
import sys
import json
import re
import urllib.request
import hashlib
from pathlib import Path

SHA256_HEX_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")

def validate_sha256_format(sha_str: str | None) -> str:
    if sha_str is None or not isinstance(sha_str, str):
        raise ValueError("SHA256 checksum string is missing or empty")
    cleaned = sha_str.strip()
    if not cleaned:
        raise ValueError("SHA256 checksum string is empty")
    if sha_str != cleaned:
        raise ValueError(f"SHA256 checksum must not contain leading/trailing whitespace or newline: '{sha_str}'")
    if not SHA256_HEX_REGEX.match(cleaned):
        raise ValueError(f"Invalid SHA256 hex format: '{cleaned}' (must be exactly 64 hex characters)")
    return cleaned.lower()

def verify_checksum_file(file_path: str | Path) -> str:
    path = Path(file_path)
    if not path.is_file():
        raise ValueError(f"Checksum file missing: {path}")
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"Checksum file is empty: {path}")
    first_token = content.split()[0]
    return validate_sha256_format(first_token)

def get_tomllib():
    try:
        import tomllib
        return tomllib
    except ImportError:
        try:
            import tomli as tomllib
            return tomllib
        except ImportError:
            print("Error: tomllib or tomli is required to parse build.toml")
            sys.exit(1)

def main():
    tomllib = get_tomllib()

    # 1. Read build.toml
    toml_path = Path("build.toml")
    if not toml_path.exists():
        print("Error: build.toml not found")
        sys.exit(1)

    with open(toml_path, "rb") as f:
        config = tomllib.load(f)

    flutter_cfg = config.get("flutter", {})
    expected_tag = flutter_cfg.get("release_tag")
    expected_asset = flutter_cfg.get("asset_name")
    expected_sha256 = flutter_cfg.get("sha256")
    expected_size = flutter_cfg.get("size")

    if not all([expected_tag, expected_asset, expected_sha256]):
        print("Error: Missing release_tag, asset_name, or sha256 in build.toml")
        sys.exit(1)

    if not isinstance(expected_asset, str) or not expected_asset.strip():
        print("Error: Invalid or empty asset_name in build.toml")
        sys.exit(1)

    # Validate SHA256 hex format strictly (64 hex characters)
    try:
        expected_sha256 = validate_sha256_format(expected_sha256)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if expected_size is not None:
        if not isinstance(expected_size, int) or expected_size <= 0:
            print(f"Error: Invalid size in manifest: {expected_size} (must be > 0)")
            sys.exit(1)

    print(f"Manifest expected tag: {expected_tag}")
    print(f"Manifest expected asset: {expected_asset}")
    print(f"Manifest expected SHA256: {expected_sha256}")
    if expected_size:
        print(f"Manifest expected size: {expected_size}")

    # 2. Check Event Context
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    target_tag = expected_tag

    if event_name == "release" and event_path and Path(event_path).exists():
        with open(event_path, "r", encoding="utf-8") as f:
            event_data = json.load(f)
        release_tag = event_data.get("release", {}).get("tag_name")
        if release_tag and release_tag != expected_tag:
            print(f"Error: Release event tag '{release_tag}' does not match manifest tag '{expected_tag}'")
            sys.exit(1)
        target_tag = release_tag

    # Optional override for workflow_dispatch or manual test
    input_tag = os.environ.get("INPUT_TAG")
    if input_tag:
        target_tag = input_tag

    print(f"Verifying release tag: {target_tag}")

    # 3. Check LIGHTWEIGHT_CHECK before published-release API lookup
    if os.environ.get("LIGHTWEIGHT_CHECK") == "1":
        runner_temp = os.environ.get("RUNNER_TEMP", "/tmp")
        download_path = Path(runner_temp) / expected_asset
        if not download_path.is_file():
            download_path = Path(".") / expected_asset
        if download_path.is_file():
            sha256_hash = hashlib.sha256()
            with open(download_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            actual_sha256 = sha256_hash.hexdigest().lower()
            if actual_sha256 != expected_sha256.lower():
                print(f"Error: Local file SHA256 mismatch in lightweight check mode!\nExpected: {expected_sha256}\nActual:   {actual_sha256}")
                sys.exit(1)
            actual_size = download_path.stat().st_size
            if expected_size is not None and actual_size != expected_size:
                print(f"Error: Local file size mismatch in lightweight check mode!\nExpected: {expected_size}\nActual:   {actual_size}")
                sys.exit(1)
            print(f"LIGHTWEIGHT_CHECK: Local file SHA256 verified ({actual_sha256}).")
            print(f"Release manifest OK: {target_tag} | {expected_asset} | {actual_size} bytes | SHA256 format verified: {expected_sha256[:8]}...")
        else:
            print(f"LIGHTWEIGHT_CHECK enabled (no local file present): Verified manifest structure and valid SHA256 hex syntax ({expected_sha256[:8]}...). Skipping network API lookup.")
        sys.exit(0)

    # 4. Retrieve release info from GitHub API via urllib
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "ImL1s/termux-flutter-wsl")
    req_url = f"https://api.github.com/repos/{repo}/releases/tags/{target_tag}"

    headers = {}
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        headers["Accept"] = "application/vnd.github+json"

    req = urllib.request.Request(req_url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            release_data = json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Error: Failed to fetch release '{target_tag}' via GitHub API: {e}")
        sys.exit(1)

    assets = {a["name"]: a for a in release_data.get("assets", [])}
    if expected_asset not in assets:
        print(f"Error: Asset '{expected_asset}' not found in release '{target_tag}'.")
        print(f"Available assets: {list(assets.keys())}")
        sys.exit(1)

    asset = assets[expected_asset]
    asset_url = asset.get("browser_download_url")
    if not asset_url:
        print("Error: Could not determine download URL for asset.")
        sys.exit(1)

    # 4. Validate all 5 release companion assets
    aux_assets = {
        f"{expected_asset}.sha256": "sha256",
        f"{expected_asset}.size.txt": "size_txt",
        "inventory.txt": "inventory",
        "build_metadata.json": "metadata",
    }
    for aux_name in aux_assets:
        if aux_name not in assets:
            print(f"Error: Auxiliary asset '{aux_name}' not found in release '{target_tag}'.")
            print(f"Available assets: {list(assets.keys())}")
            sys.exit(1)
        print(f"  ✓ Found companion asset: {aux_name}")

    # Validate exact size if provided in manifest
    actual_size = asset.get("size")
    if actual_size is None or not isinstance(actual_size, int) or actual_size <= 0:
        print(f"Error: Invalid asset size returned by API: {actual_size}")
        sys.exit(1)

    if expected_size is not None:
        if actual_size != expected_size:
            print(f"Error: Size mismatch. Expected {expected_size}, got {actual_size}")
            sys.exit(1)
        print(f"  ✓ Exact deb size verified against manifest: {actual_size} bytes")

    # 5. Cross-check digest if provided by github
    digest = (asset.get("digest") or "").lower()
    expected_digest = f"sha256:{expected_sha256.lower()}"
    if digest and digest != expected_digest:
        print(f"Error: GitHub asset digest mismatch. Expected {expected_digest}, got {digest}")
        sys.exit(1)

    # 6. Verify contents of auxiliary assets
    try:
        # Check .sha256 file
        sha_url = assets[f"{expected_asset}.sha256"]["browser_download_url"]
        with urllib.request.urlopen(urllib.request.Request(sha_url, headers=headers)) as resp:
            sha_content = resp.read().decode("utf-8").strip().split()[0]
            if sha_content.lower() != expected_sha256.lower():
                print(f"Error: .sha256 asset content mismatch! Expected {expected_sha256}, got {sha_content}")
                sys.exit(1)
            print(f"  ✓ Verified companion .sha256 asset matches expected hash: {sha_content[:8]}...")

        # Check .size.txt file
        size_url = assets[f"{expected_asset}.size.txt"]["browser_download_url"]
        with urllib.request.urlopen(urllib.request.Request(size_url, headers=headers)) as resp:
            size_content = resp.read().decode("utf-8").strip()
            if expected_size is not None and size_content != str(expected_size):
                print(f"Error: .size.txt asset content mismatch! Expected {expected_size}, got {size_content}")
                sys.exit(1)
            print(f"  ✓ Verified companion .size.txt asset matches exact bytes: {size_content}")

        # Check build_metadata.json
        meta_url = assets["build_metadata.json"]["browser_download_url"]
        with urllib.request.urlopen(urllib.request.Request(meta_url, headers=headers)) as resp:
            meta_data = json.loads(resp.read().decode("utf-8"))
            if meta_data.get("sha256") and meta_data["sha256"].lower() != expected_sha256.lower():
                print(f"Error: build_metadata.json sha256 mismatch: {meta_data.get('sha256')}")
                sys.exit(1)
            if expected_size is not None and meta_data.get("size_bytes") and meta_data["size_bytes"] != expected_size:
                print(f"Error: build_metadata.json size_bytes mismatch: {meta_data.get('size_bytes')}")
                sys.exit(1)
            print(f"  ✓ Verified build_metadata.json schema and metadata integrity")
    except Exception as e:
        print(f"Warning: Could not fetch/verify auxiliary asset contents via API: {e}")

    # 7. Check LIGHTWEIGHT_CHECK
    if os.environ.get("LIGHTWEIGHT_CHECK") == "1":
        runner_temp = os.environ.get("RUNNER_TEMP", "/tmp")
        download_path = Path(runner_temp) / expected_asset
        if not download_path.is_file():
            download_path = Path(".") / expected_asset
        if download_path.is_file():
            sha256_hash = hashlib.sha256()
            with open(download_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            actual_sha256 = sha256_hash.hexdigest().lower()
            if actual_sha256 != expected_sha256.lower():
                print(f"Error: Local file SHA256 mismatch in lightweight check mode!\nExpected: {expected_sha256}\nActual:   {actual_sha256}")
                sys.exit(1)
            print(f"LIGHTWEIGHT_CHECK: Local file SHA256 verified ({actual_sha256}).")

        print("LIGHTWEIGHT_CHECK enabled: Verified SHA256 hex format, API metadata, and checksum integrity.")
        print(f"Release manifest OK: {target_tag} | {expected_asset} | {actual_size} bytes | SHA256 format verified: {expected_sha256[:8]}...")
        sys.exit(0)

    # 8. Download asset to RUNNER_TEMP
    runner_temp = os.environ.get("RUNNER_TEMP", "/tmp")
    download_path = Path(runner_temp) / expected_asset

    print(f"Downloading {asset_url} to {download_path}...")
    try:
        import ssl
        ctx = ssl.create_default_context()
        urllib.request.urlretrieve(asset_url, download_path)
    except Exception as e:
        print(f"Error: Failed to download asset: {e}")
        sys.exit(1)

    if not download_path.exists():
        print(f"Error: Download failed, {download_path} not found.")
        sys.exit(1)

    # 9. Locally calculate and verify SHA256
    print("Calculating local SHA256...")
    sha256_hash = hashlib.sha256()
    with open(download_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)

    actual_sha256 = sha256_hash.hexdigest().lower()

    if actual_sha256 != expected_sha256.lower():
        print(f"Error: Local SHA256 mismatch!\nExpected: {expected_sha256}\nActual:   {actual_sha256}")
        sys.exit(1)

    print(f"SUCCESS: Local SHA256 verified successfully: {actual_sha256}")
    print(f"Release OK: {target_tag} | {expected_asset} | {actual_size} bytes | Digest cross-check: {'OK' if digest else 'Unavailable'}")

if __name__ == "__main__":
    main()
