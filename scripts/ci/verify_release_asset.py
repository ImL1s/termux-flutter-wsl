#!/usr/bin/env python3
import io
import os
import sys
import json
import re
import datetime
import tarfile
import zipfile
import tempfile
import urllib.request
import hashlib
from pathlib import Path



SHA256_HEX_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")
INVENTORY_LINE_REGEX = re.compile(
    r"^([dlcbsph-][rwxstST-]{9})\s+(\S+)\s+(\d+(?:,\d+)?)\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}(?::\d{2})?)\s+(.*)$"
)

BUILD_CRITICAL_PREFIXES = (
    "patches/",
    "scripts/install/",
    "scripts/fix/",
    "scripts/setup/",
)

BUILD_CRITICAL_FILES = (
    "build.py",
    "package.py",
    "sysroot.py",
    "utils.py",
    "package.yaml",
    "build.toml",
    "requirements.txt",
    ".gclient",
    "sysroot.lock.json",
    ".github/workflows/build-deb.yml",
    "install_flutter_complete.sh",
    "install.sh",
    "install_termux_flutter.sh",
    "scripts/ci/check_toolchain.sh",
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


def format_tar_permissions(mode: int) -> str:
    """Format the 9-char rwxrwxrwx permission string (including setuid/setgid/sticky bits S/s/T/t) from tar mode int."""
    perm = mode & 0o7777
    r1 = "r" if perm & 0o400 else "-"
    w1 = "w" if perm & 0o200 else "-"
    if perm & 0o4000:
        x1 = "s" if perm & 0o100 else "S"
    else:
        x1 = "x" if perm & 0o100 else "-"

    r2 = "r" if perm & 0o040 else "-"
    w2 = "w" if perm & 0o020 else "-"
    if perm & 0o2000:
        x2 = "s" if perm & 0o010 else "S"
    else:
        x2 = "x" if perm & 0o010 else "-"

    r3 = "r" if perm & 0o004 else "-"
    w3 = "w" if perm & 0o002 else "-"
    if perm & 0o1000:
        x3 = "t" if perm & 0o001 else "T"
    else:
        x3 = "x" if perm & 0o001 else "-"

    return f"{r1}{w1}{x1}{r2}{w2}{x2}{r3}{w3}{x3}"


def format_tar_ownership(member: tarfile.TarInfo) -> str:
    """Derive dpkg-deb style owner/group string from TarInfo."""
    u = member.uname if member.uname else str(member.uid)
    g = member.gname if member.gname else str(member.gid)
    return f"{u}/{g}"


def parse_inventory_entries(inventory_text: str) -> list[str]:
    """Parse normalized ordered entries (mode owner size timestamp path/target) from dpkg-deb -c style inventory text."""
    entries = []
    for line in inventory_text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        m = INVENTORY_LINE_REGEX.match(line)
        if not m:
            raise ValueError(f"Malformed inventory line: '{line}'")
        mode_str, owner_group, size_str, date_str, time_str, path_part = m.groups()
        owner_str = owner_group.strip()
        time_part = f"{date_str} {time_str}"
        if " -> " in path_part:
            path_str, link_target = path_part.split(" -> ", 1)
            norm_path = normalize_member_path(path_str)
            if norm_path:
                entries.append(f"{mode_str} {owner_str} {size_str} {time_part} {norm_path} -> {link_target}")
        elif " link to " in path_part:
            path_str, link_target = path_part.split(" link to ", 1)
            norm_path = normalize_member_path(path_str)
            hardlink_target = link_target[2:] if link_target.startswith("./") else link_target
            if norm_path:
                entries.append(f"{mode_str} {owner_str} {size_str} {time_part} {norm_path} link to {hardlink_target}")
        else:
            norm_path = normalize_member_path(path_part)
            if norm_path:
                entries.append(f"{mode_str} {owner_str} {size_str} {time_part} {norm_path}")
    return entries


def extract_deb_member_paths(deb_path, first_inventory_time: str | None = None) -> list[str]:
    """Extract list of normalized ordered entries (mode owner size timestamp path/target) contained in a .deb package's data.tar.* archive."""
    with open(deb_path, "rb") as f:
        magic = f.read(8)
        if magic != b"!<arch>\n":
            raise ValueError(f"Invalid deb archive header: {magic}")

        has_seconds = False
        inv_epoch = None
        if first_inventory_time:
            parts = first_inventory_time.split()
            if len(parts) == 2:
                time_fmt = "%Y-%m-%d %H:%M:%S" if len(parts[1]) == 8 else "%Y-%m-%d %H:%M"
                has_seconds = (len(parts[1]) == 8)
                try:
                    inv_dt = datetime.datetime.strptime(first_inventory_time, time_fmt).replace(tzinfo=datetime.timezone.utc)
                    inv_epoch = int(inv_dt.timestamp())
                except ValueError:
                    inv_epoch = None

        tz = datetime.timezone.utc
        tz_set = False
        time_fmt = "%Y-%m-%d %H:%M:%S" if has_seconds else "%Y-%m-%d %H:%M"

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

                entries = []
                with tarfile.open(fileobj=io.BytesIO(data_bytes), mode="r:*") as tar:
                    for member in tar.getmembers():
                        p = normalize_member_path(member.name)
                        if not p:
                            continue
                        if not tz_set:
                            tz_set = True
                            if inv_epoch is not None:
                                raw_offset = inv_epoch - member.mtime
                                tz_seconds = round(raw_offset / 900) * 900
                                if -86400 < tz_seconds < 86400:
                                    tz = datetime.timezone(datetime.timedelta(seconds=tz_seconds))
                                else:
                                    tz = datetime.timezone.utc
                            else:
                                tz = datetime.timezone.utc

                        mtype = tar_member_type(member)
                        perm_str = format_tar_permissions(member.mode)
                        mode_str = f"{mtype}{perm_str}"
                        owner_str = format_tar_ownership(member)
                        if member.ischr() or member.isblk():
                            member_size_str = f"{member.devmajor},{member.devminor}"
                        else:
                            member_size_str = str(member.size)

                        try:
                            member_dt = datetime.datetime.fromtimestamp(member.mtime, tz)
                            time_part = member_dt.strftime(time_fmt)
                        except Exception:
                            time_part = "1970-01-01 00:00"

                        if member.issym() and member.linkname:
                            entries.append(f"{mode_str} {owner_str} {member_size_str} {time_part} {p} -> {member.linkname}")
                        elif member.islnk() and member.linkname:
                            hardlink_target = member.linkname[2:] if member.linkname.startswith("./") else member.linkname
                            entries.append(f"{mode_str} {owner_str} {member_size_str} {time_part} {p} link to {hardlink_target}")
                        else:
                            entries.append(f"{mode_str} {owner_str} {member_size_str} {time_part} {p}")
                return entries
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
        runner_temp = os.environ.get("RUNNER_TEMP")
        download_path = None
        if runner_temp and (Path(runner_temp) / expected_asset).is_file():
            download_path = Path(runner_temp) / expected_asset
        elif (Path(".") / expected_asset).is_file():
            download_path = Path(".") / expected_asset

        if download_path and download_path.is_file():
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

    # 4. Validate all 6 release companion assets
    aux_assets = {
        f"{expected_asset}.sha256": "sha256",
        f"{expected_asset}.size.txt": "size_txt",
        "inventory.txt": "inventory",
        "build_metadata.json": "metadata",
        "build_evidence.json": "build_evidence",
        "device_smoke_evidence.json": "device_smoke_evidence",
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
            if not size_content.isdigit():
                print(f"Error: Companion .size.txt asset content is not a valid integer: '{size_content}'")
                sys.exit(1)
            parsed_size = int(size_content)
            if parsed_size != actual_size:
                print(f"Error: .size.txt asset content mismatch! Expected actual deb size {actual_size}, got {parsed_size}")
                sys.exit(1)
            if expected_size is not None and parsed_size != expected_size:
                print(f"Error: .size.txt asset content mismatch! Expected manifest size {expected_size}, got {parsed_size}")
                sys.exit(1)
            print(f"  ✓ Verified companion .size.txt asset matches exact bytes: {parsed_size}")
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

            # Enforce full 9-field required provenance schema
            required_provenance_fields = [
                "version",
                "arch",
                "run_id",
                "build_number",
                "source_commit",
                "tree_sha",
                "sha256",
                "size_bytes",
                "build_duration_seconds",
            ]
            for rf in required_provenance_fields:
                if rf not in meta_data or meta_data[rf] is None:
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
                        raw_files = compare_obj.get("files", [])
                        if len(raw_files) >= 300 or compare_obj.get("truncated", False):
                            print(f"Error: GitHub compare API returned truncated file list (count={len(raw_files)} >= 300). Cannot safely verify lineage diff without complete diff.")
                            sys.exit(1)

                        # Verify that differences only affect documentation/metadata, not build sources or patches
                        changed_files = []
                        for f_entry in raw_files:
                            fname = f_entry.get("filename")
                            if fname:
                                changed_files.append(fname)
                            prev_fname = f_entry.get("previous_filename")
                            if prev_fname:
                                changed_files.append(prev_fname)

                        disallowed_changed = [
                            f for f in changed_files
                            if f.startswith(BUILD_CRITICAL_PREFIXES) or f in BUILD_CRITICAL_FILES
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
            if meta_size != actual_size:
                print(f"Error: build_metadata.json size_bytes mismatch! Expected actual deb size {actual_size}, got {meta_size}")
                sys.exit(1)
            if expected_size is not None and meta_size != expected_size:
                print(f"Error: build_metadata.json size_bytes mismatch! Expected manifest size {expected_size}, got {meta_size}")
                sys.exit(1)

            # Validate build_number and duration fields
            b_num = meta_data["build_number"]
            if not (isinstance(b_num, int) or (isinstance(b_num, str) and str(b_num).isdigit())):
                print(f"Error: build_metadata.json build_number '{b_num}' is not a valid integer")
                sys.exit(1)

            b_dur = meta_data["build_duration_seconds"]
            if not (isinstance(b_dur, (int, float)) and b_dur >= 0):
                print(f"Error: build_metadata.json build_duration_seconds '{b_dur}' is not a valid non-negative number")
                sys.exit(1)

            # Verify workflow run provenance
            run_id = meta_data["run_id"]
            if not (isinstance(run_id, int) or (isinstance(run_id, str) and str(run_id).isdigit())):
                print(f"Error: build_metadata.json run_id '{run_id}' is not a valid integer")
                sys.exit(1)
            run_api_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
            try:
                run_req = urllib.request.Request(run_api_url, headers=headers)
                with urllib.request.urlopen(run_req) as resp:
                    run_obj = json.loads(resp.read().decode("utf-8"))
                    run_head_sha = str(run_obj.get("head_sha", "")).lower()
                    run_conclusion = str(run_obj.get("conclusion", "")).lower()
                    run_path = str(run_obj.get("path", "")).strip()
                    run_num = run_obj.get("run_number")

                    if run_path != ".github/workflows/build-deb.yml":
                        print(f"Error: Workflow run {run_id} workflow path mismatch! Expected '.github/workflows/build-deb.yml', got '{run_path}'")
                        sys.exit(1)
                    if run_head_sha != meta_commit.lower():
                        print(f"Error: Workflow run {run_id} head_sha mismatch! Claimed {meta_commit}, but run head_sha is '{run_head_sha}'")
                        sys.exit(1)
                    if run_conclusion != "success":
                        print(f"Error: Workflow run {run_id} conclusion is not 'success' (got '{run_conclusion}')")
                        sys.exit(1)
                    if run_num is not None and int(run_num) != int(b_num):
                        print(f"Error: Workflow run {run_id} run_number mismatch! Claimed build_number {b_num}, but run run_number is '{run_num}'")
                        sys.exit(1)
                    print(f"  ✓ Verified workflow run_id {run_id} (# {b_num} on .github/workflows/build-deb.yml) succeeded for source_commit {meta_commit[:8]}...")

                # Verify workflow run produced and published the matching release artifact
                run_artifacts_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts"
                with urllib.request.urlopen(urllib.request.Request(run_artifacts_url, headers=headers)) as art_resp:
                    art_data = json.loads(art_resp.read().decode("utf-8"))
                    artifacts = art_data.get("artifacts", [])
                    artifact_names = [a.get("name", "") for a in artifacts]
                    expected_artifact_patterns = (
                        f"flutter-termux-{meta_ver}-{meta_arch}",
                        f"flutter-termux-{meta_ver}-arm64",
                        f"flutter-termux-{meta_ver}-aarch64",
                        expected_asset,
                    )
                    matching_artifact = None
                    for a in artifacts:
                        aname = a.get("name", "")
                        if any(pat in aname or aname in pat for pat in expected_artifact_patterns):
                            matching_artifact = a
                            break

                    if not matching_artifact:
                        print(f"Error: Workflow run {run_id} artifacts do not match expected release package patterns {expected_artifact_patterns} (found: {artifact_names})")
                        sys.exit(1)

                    art_id = matching_artifact.get("id")
                    if matching_artifact.get("expired", False):
                        print(f"Error: Workflow run {run_id} artifact {art_id} has expired; cannot verify artifact contents")
                        sys.exit(1)

                    if art_id:

                        zip_url = f"https://api.github.com/repos/{repo}/actions/artifacts/{art_id}/zip"
                        zip_req = urllib.request.Request(zip_url, headers=headers)
                        with urllib.request.urlopen(zip_req) as zip_resp:
                            zip_data = io.BytesIO(zip_resp.read())
                            with zipfile.ZipFile(zip_data) as zf:
                                deb_names = [name for name in zf.namelist() if name.endswith(".deb")]
                                if not deb_names:
                                    print(f"Error: Workflow run {run_id} artifact zip contains no .deb file: {zf.namelist()}")
                                    sys.exit(1)
                                artifact_deb_bytes = zf.read(deb_names[0])
                                artifact_deb_sha = hashlib.sha256(artifact_deb_bytes).hexdigest().lower()
                                if artifact_deb_sha != meta_sha.lower():
                                    print(f"Error: Workflow run {run_id} artifact {deb_names[0]} sha256 mismatch! Workflow artifact sha256 is {artifact_deb_sha}, but release claimed {meta_sha}")
                                    sys.exit(1)
                                print(f"  ✓ Verified workflow artifact {deb_names[0]} sha256 ({artifact_deb_sha[:8]}...) cryptographically matches release deb")

            except Exception as e:
                print(f"Error: Failed to verify workflow run {run_id} provenance via GitHub API: {e}")
                sys.exit(1)

            print(f"  ✓ Verified build_metadata.json full 9-field provenance schema (version={meta_ver}, arch={meta_arch}, run_id={run_id}, build_number={b_num}, commit={meta_commit[:8]}..., tree={meta_tree[:8]}..., sha256={meta_sha[:8]}..., size={meta_size}, duration={b_dur}s)")

    except Exception as e:
        print(f"Error: Failed to fetch/verify companion build_metadata.json asset: {e}")
        sys.exit(1)

    # 7. Verify build_evidence.json
    build_ev_url = assets["build_evidence.json"].get("browser_download_url")
    if not build_ev_url:
        print("Error: Missing download URL for companion build_evidence.json")
        sys.exit(1)
    try:
        with urllib.request.urlopen(urllib.request.Request(build_ev_url, headers=headers)) as resp:
            b_ev_data = json.loads(resp.read().decode("utf-8"))
            if b_ev_data.get("type") != "build_evidence":
                print(f"Error: build_evidence.json type mismatch! Expected 'build_evidence', got '{b_ev_data.get('type')}'")
                sys.exit(1)
            b_ev_ver = _normalize_ver(b_ev_data.get("version", ""))
            if b_ev_ver != expected_ver:
                print(f"Error: build_evidence.json version mismatch! Expected {expected_ver}, got {b_ev_ver}")
                sys.exit(1)
            b_ev_arch = str(b_ev_data.get("arch", "")).lower()
            if b_ev_arch not in ("arm64", "aarch64") or b_ev_arch != meta_arch:
                print(f"Error: build_evidence.json arch mismatch! Expected {meta_arch}, got {b_ev_arch}")
                sys.exit(1)
            b_ev_run_id = b_ev_data.get("run_id")
            if str(b_ev_run_id) != str(run_id):
                print(f"Error: build_evidence.json run_id mismatch! Expected {run_id}, got {b_ev_run_id}")
                sys.exit(1)
            b_ev_num = b_ev_data.get("build_number")
            if str(b_ev_num) != str(b_num):
                print(f"Error: build_evidence.json build_number mismatch! Expected {b_num}, got {b_ev_num}")
                sys.exit(1)
            b_ev_commit = str(b_ev_data.get("source_commit", "")).strip().lower()
            if b_ev_commit != meta_commit:
                print(f"Error: build_evidence.json source_commit mismatch! Expected {meta_commit}, got {b_ev_commit}")
                sys.exit(1)
            b_ev_tree = str(b_ev_data.get("tree_sha", "")).strip().lower()
            if b_ev_tree != meta_tree:
                print(f"Error: build_evidence.json tree_sha mismatch! Expected {meta_tree}, got {b_ev_tree}")
                sys.exit(1)
            b_ev_sha = str(b_ev_data.get("deb_sha256", "")).strip().lower()
            if b_ev_sha != expected_sha256.lower():
                print(f"Error: build_evidence.json deb_sha256 mismatch! Expected {expected_sha256}, got {b_ev_sha}")
                sys.exit(1)
            b_ev_size = b_ev_data.get("deb_size_bytes")
            if not isinstance(b_ev_size, int) or b_ev_size != actual_size:
                print(f"Error: build_evidence.json deb_size_bytes mismatch! Expected {actual_size}, got {b_ev_size}")
                sys.exit(1)
            b_ev_inv_cnt = b_ev_data.get("inventory_file_count")
            if not isinstance(b_ev_inv_cnt, int) or b_ev_inv_cnt <= 0 or b_ev_inv_cnt != len(inventory_paths):
                print(f"Error: build_evidence.json inventory_file_count mismatch! Expected {len(inventory_paths)}, got {b_ev_inv_cnt}")
                sys.exit(1)
            b_ev_dur = b_ev_data.get("build_duration_seconds")
            if not (isinstance(b_ev_dur, (int, float)) and b_ev_dur >= 0):
                print(f"Error: build_evidence.json build_duration_seconds is invalid: {b_ev_dur}")
                sys.exit(1)
            print(f"  ✓ Verified build_evidence.json full schema (run_id={b_ev_run_id}, build_number={b_ev_num}, files={b_ev_inv_cnt}, sha256={b_ev_sha[:8]}...)")
    except Exception as e:
        print(f"Error: Failed to fetch/verify companion build_evidence.json asset: {e}")
        sys.exit(1)

    # 8. Verify device_smoke_evidence.json
    dev_ev_url = assets["device_smoke_evidence.json"].get("browser_download_url")
    if not dev_ev_url:
        print("Error: Missing download URL for companion device_smoke_evidence.json")
        sys.exit(1)
    try:
        with urllib.request.urlopen(urllib.request.Request(dev_ev_url, headers=headers)) as resp:
            dev_ev_data = json.loads(resp.read().decode("utf-8"))
            if dev_ev_data.get("status") != "passed":
                print(f"Error: device_smoke_evidence.json status is not 'passed' (got '{dev_ev_data.get('status')}')")
                sys.exit(1)
            if dev_ev_data.get("mode_a_status") != "passed":
                print(f"Error: device_smoke_evidence.json mode_a_status is not 'passed' (got '{dev_ev_data.get('mode_a_status')}')")
                sys.exit(1)
            if dev_ev_data.get("mode_b_status") != "passed":
                print(f"Error: device_smoke_evidence.json mode_b_status is not 'passed' (got '{dev_ev_data.get('mode_b_status')}')")
                sys.exit(1)

            dev_src_commit = str(dev_ev_data.get("artifact_source_commit") or dev_ev_data.get("source_commit") or "").strip().lower()
            dev_ver_commit = str(dev_ev_data.get("verifier_commit") or "").strip().lower()
            if dev_src_commit != meta_commit:
                print(f"Error: device_smoke_evidence.json artifact_source_commit mismatch! Expected {meta_commit}, got {dev_src_commit}")
                sys.exit(1)
            if dev_ver_commit != meta_commit:
                print(f"Error: device_smoke_evidence.json verifier_commit mismatch! Expected {meta_commit}, got {dev_ver_commit}")
                sys.exit(1)

            dev_build_run_id = dev_ev_data.get("build_run_id") or dev_ev_data.get("run_id")
            if str(dev_build_run_id) != str(run_id):
                print(f"Error: device_smoke_evidence.json build_run_id mismatch! Expected {run_id}, got {dev_build_run_id}")
                sys.exit(1)

            dev_artifacts = dev_ev_data.get("artifacts", {})
            if not isinstance(dev_artifacts, dict):
                print("Error: device_smoke_evidence.json missing 'artifacts' object")
                sys.exit(1)

            dev_deb_sha = str(dev_artifacts.get("deb_sha256", "")).strip().lower()
            if dev_deb_sha != expected_sha256.lower():
                print(f"Error: device_smoke_evidence.json artifacts.deb_sha256 mismatch! Expected {expected_sha256}, got {dev_deb_sha}")
                sys.exit(1)

            dev_deb_sz = dev_artifacts.get("deb_size")
            if not isinstance(dev_deb_sz, int) or dev_deb_sz != actual_size:
                print(f"Error: device_smoke_evidence.json artifacts.deb_size mismatch! Expected {actual_size}, got {dev_deb_sz}")
                sys.exit(1)

            apk_sha = str(dev_artifacts.get("apk_sha256", "")).strip().lower()
            if not re.match(r"^[0-9a-f]{64}$", apk_sha):
                print(f"Error: device_smoke_evidence.json artifacts.apk_sha256 is not a valid 64-char sha256: '{apk_sha}'")
                sys.exit(1)

            apk_sz = dev_artifacts.get("apk_size")
            if not (isinstance(apk_sz, int) and apk_sz > 0):
                print(f"Error: device_smoke_evidence.json artifacts.apk_size is not a positive integer: {apk_sz}")
                sys.exit(1)

            aab_sha = str(dev_artifacts.get("aab_sha256", "")).strip().lower()
            if not re.match(r"^[0-9a-f]{64}$", aab_sha):
                print(f"Error: device_smoke_evidence.json artifacts.aab_sha256 is not a valid 64-char sha256: '{aab_sha}'")
                sys.exit(1)

            aab_sz = dev_artifacts.get("aab_size")
            if not (isinstance(aab_sz, int) and aab_sz > 0):
                print(f"Error: device_smoke_evidence.json artifacts.aab_size is not a positive integer: {aab_sz}")
                sys.exit(1)

            print(f"  ✓ Verified device_smoke_evidence.json full schema (status=passed, mode_a=passed, mode_b=passed, build_run_id={dev_build_run_id}, deb_sha256={dev_deb_sha[:8]}..., apk_size={apk_sz}, aab_size={aab_sz})")
    except Exception as e:
        print(f"Error: Failed to fetch/verify companion device_smoke_evidence.json asset: {e}")
        sys.exit(1)


    # 8. Download asset to RUNNER_TEMP
    runner_temp = os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()
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
        first_time = None
        if inventory_paths:
            tokens = inventory_paths[0].split(maxsplit=5)
            if len(tokens) >= 5:
                first_time = f"{tokens[3]} {tokens[4]}"
        deb_entries = extract_deb_member_paths(download_path, first_inventory_time=first_time)
        if inventory_paths != deb_entries:
            print(f"Error: Semantic mismatch between inventory.txt and {expected_asset} contents!")
            inv_set = set(inventory_paths)
            deb_set = set(deb_entries)
            missing_in_deb = inv_set - deb_set
            extra_in_deb = deb_set - inv_set
            if missing_in_deb:
                print(f"  In inventory.txt but missing from deb ({len(missing_in_deb)} entries): {list(missing_in_deb)[:5]}")
            if extra_in_deb:
                print(f"  In deb but missing from inventory.txt ({len(extra_in_deb)} entries): {list(extra_in_deb)[:5]}")
            if not missing_in_deb and not extra_in_deb:
                print(f"  Multiplicity or ordering mismatch: inventory has {len(inventory_paths)} entries, deb has {len(deb_entries)} entries")
            sys.exit(1)
        print(f"  ✓ Inventory perfectly matches package contents ({len(deb_entries)} entries verified)")
    except Exception as e:
        print(f"Error: Failed to verify package inventory integrity: {e}")
        sys.exit(1)

    print(f"Release OK: {target_tag} | {expected_asset} | {actual_size} bytes | Digest cross-check: {'OK' if digest else 'Unavailable'}")

if __name__ == "__main__":
    main()
