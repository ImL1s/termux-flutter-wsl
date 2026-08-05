#!/usr/bin/env python3
import os
import sys
import json
import urllib.request
import hashlib
from pathlib import Path

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

    # 3. Retrieve release info from GitHub API via urllib
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

    # 4. Validate exact size if provided in manifest
    actual_size = asset.get("size")
    if expected_size is not None:
        if actual_size != expected_size:
            print(f"Error: Size mismatch. Expected {expected_size}, got {actual_size}")
            sys.exit(1)

    # 5. Cross-check digest if provided by github
    # GitHub REST API doesn't standardly return 'digest', but if it's there we check it.
    digest = (asset.get("digest") or "").lower()
    expected_digest = f"sha256:{expected_sha256.lower()}"
    if digest and digest != expected_digest:
        print(f"Error: GitHub asset digest mismatch. Expected {expected_digest}, got {digest}")
        sys.exit(1)

    # 6. Download asset to RUNNER_TEMP
    runner_temp = os.environ.get("RUNNER_TEMP", "/tmp")
    download_path = Path(runner_temp) / expected_asset

    # In lightweight check mode, we skip downloading and hashing
    if os.environ.get("LIGHTWEIGHT_CHECK") == "1":
        print("LIGHTWEIGHT_CHECK enabled: Skipping download and hash verification.")
        print(f"Release manifest OK: {target_tag} | {expected_asset} | {actual_size} bytes")
        sys.exit(0)

    print(f"Downloading {asset_url} to {download_path}...")
    try:
        req_dl = urllib.request.Request(asset_url)
        # If it redirects, urlretrieve handles it, but let's just use urlretrieve
        import ssl
        ctx = ssl.create_default_context()
        urllib.request.urlretrieve(asset_url, download_path)
    except Exception as e:
        print(f"Error: Failed to download asset: {e}")
        sys.exit(1)

    if not download_path.exists():
        print(f"Error: Download failed, {download_path} not found.")
        sys.exit(1)

    # 7. Locally calculate and verify SHA256
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
