#!/usr/bin/env python3
"""Generate release companion files for the current build.toml asset."""
from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    cfg = tomllib.loads((ROOT / "build.toml").read_text(encoding="utf-8"))
    flutter = cfg["flutter"]
    rev = str(flutter.get("revision", "0"))
    tag = str(flutter["tag"])
    package_version = f"{tag}-{rev}" if rev != "0" else tag
    asset_name = str(flutter["asset_name"])
    deb = ROOT / "release" / asset_name
    if not deb.is_file():
        raise SystemExit(f"missing deb: {deb}")

    listing = subprocess.check_output(["dpkg-deb", "-c", str(deb)], text=True)
    paths = []
    for line in listing.splitlines():
        parts = line.split(None, 5)
        if len(parts) >= 6:
            paths.append(parts[5])
    inv = ROOT / "release" / "inventory.txt"
    inv.write_text("\n".join(paths) + "\n", encoding="utf-8")

    meta = {
        "flutter_version": tag,
        "package_version": package_version,
        "release_tag": flutter["release_tag"],
        "asset_name": asset_name,
        "sha256": flutter["sha256"],
        "size": flutter["size"],
        "framework_revision": flutter["framework_revision"],
        "engine_commit": flutter["engine_commit"],
        "dart_version": flutter["dart_version"],
        "source": "repack_deb_revision",
        "source_deb_sha256": "8b32041a11452b8d995ba45dcc2bb196e4d841410c46871853a6f4c24acddd20",
        "inventory_entries": len(paths),
    }
    (ROOT / "release" / "build_metadata.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
