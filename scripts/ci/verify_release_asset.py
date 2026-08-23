#!/usr/bin/env python3
import io
import os
import sys
import json
import re
import tarfile
import urllib.request
import hashlib
from pathlib import Path

SHA256_HEX_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")
INVENTORY_LINE_REGEX = re.compile(
    r"^([dlcbsph-][rwxst-]{9})\s+(\S+)\s+(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}(?::\d{2})?)\s+(.*)$"
)


def normalize_member_path(p: str) -> str:
    """Normalize tar member / inventory path by stripping leading './' and trailing '/' without clobbering whitespace or leading dots."""
    s = p
    if s == ".":
        return ""
    if s.startswith("./"):
        s = s[2:]
    if s.endswith("/") and s != "/":
        s = s[:-1]
    return s


def tar_member_type(member: tarfile.TarInfo) -> str:
    """Derive dpkg-deb style single-character type indicator from tar member."""
    if member.isdir():
        return "d"
    if member.issym():
        return "l"
    if member.islnk():
        return "h"
    if member.ischr():
        return "c"
    if member.isblk():
        return "b"
    if member.isfifo():
        return "p"
    return "-"


def parse_inventory_entries(inventory_text: str) -> set:
    """Parse normalized (type:path/target) entries from dpkg-deb -c style inventory text."""
    paths = set()
    for line in inventory_text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        m = INVENTORY_LINE_REGEX.match(line)
        if not m:
            raise ValueError(f"Malformed inventory line: '{line}'")
        mode_str, _, _, _, _, path_part = m.groups()
        entry_type = mode_str[0]
        if " -> " in path_part:
            path_str, link_target = path_part.split(" -> ", 1)
            norm_path = normalize_member_path(path_str)
            norm_target = normalize_member_path(link_target)
            if norm_path:
                paths.add(f"{entry_type}:{norm_path} -> {norm_target}")
        elif " link to " in path_part:
            path_str, link_target = path_part.split(" link to ", 1)
            norm_path = normalize_member_path(path_str)
            norm_target = normalize_member_path(link_target)
            if norm_path:
                paths.add(f"{entry_type}:{norm_path} link to {norm_target}")
        else:
            norm_path = normalize_member_path(path_part)
            if norm_path:
                paths.add(f"{entry_type}:{norm_path}")
    return paths


def extract_deb_member_paths(deb_path) -> set:
    """Extract set of normalized (type:path/target) entries contained in a .deb package's data.tar.* archive."""
    with open(deb_path, "rb") as f:
        magic = f.read(8)
        if magic != b"!<arch>\n":
            raise ValueError(f"Invalid deb archive header: {magic}")

        while True:
            header = f.read(60)
            if not header or len(header) < 60:
                break
            name = header[:16].decode("ascii", errors="ignore").strip().rstrip("/")
            size_str = header[48:58].decode("ascii", errors="ignore").strip()
            if not size_str:
                break
            size = int(size_str)

            if name.startswith("data.tar"):
                data_bytes = f.read(size)
                if size % 2 == 1:
                    f.read(1)

                paths = set()
                with tarfile.open(fileobj=io.BytesIO(data_bytes), mode="r:*") as tar:
                    for member in tar.getmembers():
                        p = normalize_member_path(member.name)
                        if not p:
                            continue
                        mtype = tar_member_type(member)
                        if member.issym() and member.linkname:
                            norm_target = normalize_member_path(member.linkname)
                            paths.add(f"{mtype}:{p} -> {norm_target}")
                        elif member.islnk() and member.linkname:
                            norm_target = normalize_member_path(member.linkname)
                            paths.add(f"{mtype}:{p} link to {norm_target}")
                        else:
                            paths.add(f"{mtype}:{p}")
                return paths
            else:
                skip = size + (1 if size % 2 == 1 else 0)
                f.seek(skip, io.SEEK_CUR)

    raise ValueError("No data.tar member found in .deb archive")


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

    # 6. Verify contents of auxiliary assets (Strict Fail-Closed)
    # Check .sha256 file
    sha_url = assets[f"{expected_asset}.sha256"].get("browser_download_url")
    if not sha_url:
        print(f"Error: Missing download URL for companion {expected_asset}.sha256")
        sys.exit(1)
    try:
        with urllib.request.urlopen(urllib.request.Request(sha_url, headers=headers)) as resp:
            sha_content = resp.read().decode("utf-8").strip().split()[0]
            if sha_content.lower() != expected_sha256.lower():
                print(f"Error: .sha256 asset content mismatch! Expected {expected_sha256}, got {sha_content}")
                sys.exit(1)
            print(f"  ✓ Verified companion .sha256 asset matches expected hash: {sha_content[:8]}...")
    except Exception as e:
        print(f"Error: Failed to fetch/verify companion .sha256 asset: {e}")
        sys.exit(1)

    # Check .size.txt file
    size_url = assets[f"{expected_asset}.size.txt"].get("browser_download_url")
    if not size_url:
        print(f"Error: Missing download URL for companion {expected_asset}.size.txt")
        sys.exit(1)
    try:
        with urllib.request.urlopen(urllib.request.Request(size_url, headers=headers)) as resp:
            size_content = resp.read().decode("utf-8").strip()
            if expected_size is not None and size_content != str(expected_size):
                print(f"Error: .size.txt asset content mismatch! Expected {expected_size}, got {size_content}")
                sys.exit(1)
            print(f"  ✓ Verified companion .size.txt asset matches exact bytes: {size_content}")
    except Exception as e:
        print(f"Error: Failed to fetch/verify companion .size.txt asset: {e}")
        sys.exit(1)

    # Check inventory.txt file
    inv_url = assets["inventory.txt"].get("browser_download_url")
    if not inv_url:
        print("Error: Missing download URL for companion inventory.txt")
        sys.exit(1)
    inventory_paths = set()
    try:
        with urllib.request.urlopen(urllib.request.Request(inv_url, headers=headers)) as resp:
            inv_content = resp.read().decode("utf-8")
            if not inv_content.strip():
                print("Error: Companion inventory.txt is empty!")
                sys.exit(1)
            inventory_paths = parse_inventory_entries(inv_content)
            if len(inventory_paths) < 10:
                print(f"Error: Companion inventory.txt contains suspicious entry count: {len(inventory_paths)}")
                sys.exit(1)
            print(f"  ✓ Verified companion inventory.txt format ({len(inventory_paths)} valid entries)")
    except Exception as e:
        print(f"Error: Failed to fetch/verify companion inventory.txt asset: {e}")
        sys.exit(1)

    # Check build_metadata.json with required schema
    meta_url = assets["build_metadata.json"].get("browser_download_url")
    if not meta_url:
        print("Error: Missing download URL for companion build_metadata.json")
        sys.exit(1)
    try:
        with urllib.request.urlopen(urllib.request.Request(meta_url, headers=headers)) as resp:
            meta_data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(meta_data, dict):
                print("Error: build_metadata.json is not a valid JSON dictionary")
                sys.exit(1)

            # Enforce full required provenance schema
            required_provenance_fields = ["version", "arch", "source_commit", "tree_sha", "sha256", "size_bytes"]
            for rf in required_provenance_fields:
                if rf not in meta_data:
                    print(f"Error: build_metadata.json missing required provenance field '{rf}'")
                    sys.exit(1)

            # Validate version (strip at most one leading 'v' and one trailing '-termux')
            def _normalize_ver(v_str: str) -> str:
                s = str(v_str).strip()
                if s.startswith("v"):
                    s = s[1:]
                if s.endswith("-termux"):
                    s = s[:-len("-termux")]
                return s

            expected_ver = _normalize_ver(expected_tag)
            meta_ver = _normalize_ver(meta_data["version"])
            if meta_ver != expected_ver:
                print(f"Error: build_metadata.json version mismatch! Expected {expected_ver}, got {meta_ver}")
                sys.exit(1)

            # Validate arch
            meta_arch = str(meta_data["arch"]).lower()
            if meta_arch not in ("arm64", "aarch64"):
                print(f"Error: build_metadata.json unexpected arch: {meta_arch}")
                sys.exit(1)

            # Validate source_commit & tree_sha format (40 hex chars)
            meta_commit = str(meta_data["source_commit"]).strip().lower()
            if not re.match(r"^[0-9a-f]{40}$", meta_commit):
                print(f"Error: build_metadata.json source_commit '{meta_commit}' is not a valid 40-char git commit hash")
                sys.exit(1)

            meta_tree = str(meta_data["tree_sha"]).strip().lower()
            if not re.match(r"^[0-9a-f]{40}$", meta_tree):
                print(f"Error: build_metadata.json tree_sha '{meta_tree}' is not a valid 40-char git tree hash")
                sys.exit(1)

            # Cryptographically bind source_commit and tree_sha against GitHub commit API
            commit_api_url = f"https://api.github.com/repos/{repo}/git/commits/{meta_commit}"
            try:
                commit_req = urllib.request.Request(commit_api_url, headers=headers)
                with urllib.request.urlopen(commit_req) as resp:
                    commit_obj = json.loads(resp.read().decode("utf-8"))
                    actual_tree_sha = commit_obj.get("tree", {}).get("sha", "").lower()
                    if actual_tree_sha != meta_tree.lower():
                        print(f"Error: build_metadata.json tree_sha mismatch! Claimed '{meta_tree}', but commit {meta_commit} tree is '{actual_tree_sha}'")
                        sys.exit(1)
                    print(f"  ✓ Verified tree_sha is cryptographically bound to source_commit: {meta_tree[:8]}...")
            except Exception as e:
                print(f"Error: Failed to verify commit provenance via GitHub API for {meta_commit}: {e}")
                sys.exit(1)

            # Verify source_commit is bound to the release tag's lineage
            compare_url = f"https://api.github.com/repos/{repo}/compare/{meta_commit}...{target_tag}"
            try:
                compare_req = urllib.request.Request(compare_url, headers=headers)
                with urllib.request.urlopen(compare_req) as resp:
                    compare_obj = json.loads(resp.read().decode("utf-8"))
                    behind_by = compare_obj.get("behind_by", 0)
                    ahead_by = compare_obj.get("ahead_by", 0)
                    status = compare_obj.get("status", "")
                    if behind_by > 0 or status not in ("ahead", "identical"):
                        print(f"Error: build_metadata.json source_commit {meta_commit} is not on the release lineage of {target_tag} (status={status}, behind_by={behind_by})")
                        sys.exit(1)

                    if status == "identical":
                        print(f"  ✓ Verified source_commit is identical to release tag {target_tag}")
                    else:
                        if ahead_by > 5:
                            print(f"Error: build_metadata.json source_commit {meta_commit} is too far behind {target_tag} (ahead_by={ahead_by} > 5)")
                            sys.exit(1)
                        # Verify that differences only affect documentation/metadata, not build sources or patches
                        changed_files = [f.get("filename", "") for f in compare_obj.get("files", [])]
                        disallowed_changed = [
                            f for f in changed_files
                            if f.startswith("patches/") or f in ("build.py", "package.py", "sysroot.py", "utils.py", "package.yaml")
                        ]
                        if disallowed_changed:
                            print(f"Error: Disallowed build/engine source files changed between build commit {meta_commit} and release {target_tag}: {disallowed_changed}")
                            sys.exit(1)
                        print(f"  ✓ Verified source_commit belongs to release {target_tag} lineage (status={status}, ahead_by={ahead_by}, zero build source drift)")
            except Exception as e:
                print(f"Error: Failed to verify commit lineage for {meta_commit} against {target_tag}: {e}")
                sys.exit(1)

            # Validate sha256
            meta_sha = str(meta_data["sha256"]).strip().lower()
            if meta_sha != expected_sha256.lower():
                print(f"Error: build_metadata.json sha256 mismatch! Expected {expected_sha256}, got {meta_sha}")
                sys.exit(1)

            # Validate size_bytes
            meta_size = meta_data["size_bytes"]
            if not isinstance(meta_size, int) or meta_size <= 0:
                print(f"Error: build_metadata.json size_bytes '{meta_size}' is not a positive integer")
                sys.exit(1)
            if expected_size is not None and meta_size != expected_size:
                print(f"Error: build_metadata.json size_bytes mismatch! Expected {expected_size}, got {meta_size}")
                sys.exit(1)

            print(f"  ✓ Verified build_metadata.json full provenance schema (version={meta_ver}, arch={meta_arch}, commit={meta_commit[:8]}..., tree={meta_tree[:8]}..., sha256={meta_sha[:8]}..., size={meta_size})")
    except Exception as e:
        print(f"Error: Failed to fetch/verify companion build_metadata.json asset: {e}")
        sys.exit(1)

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

    # 10. Cross-check inventory.txt against downloaded .deb package entries
    print("Cross-checking inventory.txt against downloaded package entries...")
    try:
        deb_paths = extract_deb_member_paths(download_path)
        missing_in_deb = inventory_paths - deb_paths
        extra_in_deb = deb_paths - inventory_paths
        if missing_in_deb or extra_in_deb:
            print(f"Error: Semantic mismatch between inventory.txt and {expected_asset} contents!")
            if missing_in_deb:
                print(f"  In inventory.txt but missing from deb ({len(missing_in_deb)} entries): {list(missing_in_deb)[:5]}")
            if extra_in_deb:
                print(f"  In deb but missing from inventory.txt ({len(extra_in_deb)} entries): {list(extra_in_deb)[:5]}")
            sys.exit(1)
        print(f"  ✓ Inventory perfectly matches package contents ({len(deb_paths)} entries verified)")
    except Exception as e:
        print(f"Error: Failed to verify package inventory integrity: {e}")
        sys.exit(1)

    print(f"Release OK: {target_tag} | {expected_asset} | {actual_size} bytes | Digest cross-check: {'OK' if digest else 'Unavailable'}")

if __name__ == "__main__":
    main()
