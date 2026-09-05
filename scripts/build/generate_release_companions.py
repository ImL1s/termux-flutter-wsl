#!/usr/bin/env python3
"""Generate release companion files for the current build.toml asset."""
from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Immutable historical r0 package this revision may repack from.
SOURCE_DEB_SHA256_R0 = "8b32041a11452b8d995ba45dcc2bb196e4d841410c46871853a6f4c24acddd20"


def main() -> int:
    cfg = tomllib.loads((ROOT / "build.toml").read_text(encoding="utf-8"))
    flutter = cfg["flutter"]
    rev = str(flutter.get("revision", "0"))
    tag = str(flutter["tag"])
    package_version = f"{tag}-{rev}" if rev != "0" else tag
    asset_name = str(flutter["asset_name"])
    sha256 = str(flutter["sha256"]).strip().lower()
    size = int(flutter["size"])
    deb = ROOT / "release" / asset_name
    if not deb.is_file():
        raise SystemExit(f"missing deb: {deb}")

    listing = subprocess.check_output(["dpkg-deb", "-c", str(deb)], text=True)
    inv = ROOT / "release" / "inventory.txt"
    inv.write_text(listing if listing.endswith("\n") else listing + "\n", encoding="utf-8")
    inventory_count = sum(1 for line in listing.splitlines() if line.strip())

    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    tree_sha = subprocess.check_output(
        ["git", "log", "-1", "--format=%T", "HEAD"], cwd=ROOT, text=True
    ).strip()

    meta = {
        "version": tag,
        "arch": "aarch64",
        "run_id": 0,
        "build_number": int(rev) if rev.isdigit() else 0,
        "source_commit": source_commit,
        "tree_sha": tree_sha,
        "sha256": sha256,
        "size_bytes": size,
        "build_duration_seconds": 0,
        "provenance_mode": "repack_device_smoke",
        "source": "repack_deb_revision",
        "source_deb_sha256": SOURCE_DEB_SHA256_R0,
        "flutter_version": tag,
        "package_version": package_version,
        "release_tag": flutter["release_tag"],
        "asset_name": asset_name,
        "framework_revision": flutter["framework_revision"],
        "engine_commit": flutter["engine_commit"],
        "dart_version": flutter["dart_version"],
        "inventory_entries": inventory_count,
        # Back-compat aliases consumed by some smoke helpers.
        "size": size,
    }
    (ROOT / "release" / "build_metadata.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    evidence = {
        "type": "build_evidence",
        "version": tag,
        "arch": "aarch64",
        "run_id": 0,
        "build_number": int(rev) if rev.isdigit() else 0,
        "source_commit": source_commit,
        "tree_sha": tree_sha,
        "deb_sha256": sha256,
        "deb_size_bytes": size,
        "inventory_file_count": inventory_count,
        "build_duration_seconds": 0,
        "provenance_mode": "repack_device_smoke",
        "source": "repack_deb_revision",
        "source_deb_sha256": SOURCE_DEB_SHA256_R0,
    }
    (ROOT / "release" / "build_evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
