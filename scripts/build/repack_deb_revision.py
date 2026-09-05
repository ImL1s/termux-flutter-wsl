#!/usr/bin/env python3
"""Repack an existing Flutter Termux .deb with current packaging scripts.

Used when engine binaries are already verified (same Flutter tag) but install
scripts / package metadata need a new Debian revision. Does not rebuild the
engine; replaces package-owned scripts and regenerates version manifests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parents[2]
PREFIX = Path("data/data/com.termux/files/usr")
DISTRO = PREFIX / "opt" / "flutter"


def load_flutter_cfg() -> dict:
    data = tomllib.loads((ROOT / "build.toml").read_text(encoding="utf-8"))
    return dict(data["flutter"])


def package_version(cfg: dict) -> str:
    tag = str(cfg["tag"])
    rev = str(cfg.get("revision", "0"))
    return f"{tag}-{rev}" if rev != "0" else tag


def write_text(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(mode)


def copy_script(src: Path, dest: Path, mode: int = 0o755) -> None:
    if not src.is_file():
        raise FileNotFoundError(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    dest.chmod(mode)


def extract_deb(deb: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["dpkg-deb", "-R", str(deb), str(dest)], check=True)


def build_deb(tree: Path, out_deb: Path) -> None:
    out_deb.parent.mkdir(parents=True, exist_ok=True)
    if out_deb.exists():
        out_deb.unlink()
    subprocess.run(
        ["dpkg-deb", "-Zxz", "-b", str(tree), str(out_deb)],
        check=True,
    )


def update_control(control_path: Path, version: str) -> None:
    lines = control_path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        if line.startswith("Version:"):
            out.append(f"Version: {version}")
        else:
            out.append(line)
    write_text(control_path, "\n".join(out) + "\n")


def write_manifests(tree: Path, cfg: dict, pkg_ver: str) -> None:
    engine = str(cfg["engine_commit"])
    payload = {
        "frameworkVersion": str(cfg["tag"]),
        "channel": "stable",
        "repositoryUrl": "https://github.com/flutter/flutter.git",
        "frameworkRevision": str(cfg["framework_revision"]),
        "frameworkCommitDate": str(cfg["framework_commit_date"]),
        "engineRevision": engine,
        "dartSdkVersion": str(cfg["dart_version"]),
        "devToolsVersion": str(cfg["devtools_version"]),
        "flutterVersion": str(cfg["tag"]),
    }
    manifest = {
        "flutter_version": str(cfg["tag"]),
        "package_version": pkg_ver,
        "framework_revision": str(cfg["framework_revision"]),
        "framework_commit_date": str(cfg["framework_commit_date"]),
        "engine_revision": engine,
        "dart_version": str(cfg["dart_version"]),
        "devtools_version": str(cfg["devtools_version"]),
        "channel": "stable",
        "repository_url": "https://github.com/flutter/flutter.git",
    }
    cache = tree / DISTRO / "bin" / "cache"
    write_text(cache / "flutter.version.json", json.dumps(payload, indent=2) + "\n")
    write_text(cache / "canonical_manifest.json", json.dumps(manifest, indent=2) + "\n")
    write_text(
        tree / PREFIX / "share" / "flutter" / "manifest.json",
        json.dumps(manifest, indent=2) + "\n",
    )


def replace_package_scripts(tree: Path) -> None:
    share = tree / PREFIX / "share" / "flutter"
    copy_script(ROOT / "scripts/install/post_install.sh", share / "post_install.sh")
    copy_script(ROOT / "scripts/ci/check_toolchain.sh", share / "check_toolchain.sh")
    copy_script(
        ROOT / "scripts/install/setup_modern_tools.sh", share / "setup_modern_tools.sh"
    )
    copy_script(
        ROOT / "scripts/install/flutter_project_config.sh",
        share / "flutter_project_config.sh",
    )
    copy_script(
        ROOT / "scripts/install/flutter_termux_doctor.sh",
        tree / PREFIX / "bin" / "flutter-termux",
    )


def patch_profile_engine(tree: Path, engine: str) -> None:
    profile = tree / PREFIX / "etc" / "profile.d" / "flutter.sh"
    if not profile.is_file():
        return
    text = profile.read_text(encoding="utf-8")
    import re

    updated, n = re.subn(
        r'export FLUTTER_PREBUILT_ENGINE_VERSION="[^"]*"',
        f'export FLUTTER_PREBUILT_ENGINE_VERSION="{engine}"',
        text,
        count=1,
    )
    if n:
        write_text(profile, updated if updated.endswith("\n") else updated + "\n", 0o755)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def update_build_toml_hash(sha: str, size: int) -> None:
    path = ROOT / "build.toml"
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        if line.startswith("sha256"):
            out.append(f"sha256 = '{sha}'")
        elif line.startswith("size"):
            out.append(f"size = {size}")
        else:
            out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-deb",
        type=Path,
        default=ROOT / "release" / "flutter_3.44.9_aarch64.deb",
        help="Existing verified same-tag .deb to repack",
    )
    parser.add_argument(
        "--update-build-toml",
        action="store_true",
        help="Write measured sha256/size back into build.toml",
    )
    args = parser.parse_args()

    cfg = load_flutter_cfg()
    pkg_ver = package_version(cfg)
    asset_name = str(cfg.get("asset_name") or f"flutter_{pkg_ver}_aarch64.deb")
    out_deb = ROOT / "release" / asset_name

    if not args.source_deb.is_file():
        print(f"error: source deb not found: {args.source_deb}", file=sys.stderr)
        return 1

    expected_src_sha = str(cfg.get("sha256") or "")
    # Allow repack when build.toml already points at the new revision asset;
    # verify source bytes against the known published r0 hash when present.
    published_r0 = "8b32041a11452b8d995ba45dcc2bb196e4d841410c46871853a6f4c24acddd20"
    src_sha = sha256_file(args.source_deb)
    if src_sha != published_r0 and expected_src_sha and src_sha != expected_src_sha:
        print(
            f"error: source deb sha256 {src_sha} does not match expected "
            f"published r0 or build.toml sha256",
            file=sys.stderr,
        )
        return 1

    with tempfile.TemporaryDirectory(prefix="repack-deb-") as tmp:
        tree = Path(tmp) / "tree"
        extract_deb(args.source_deb, tree)
        update_control(tree / "DEBIAN" / "control", pkg_ver)
        replace_package_scripts(tree)
        write_manifests(tree, cfg, pkg_ver)
        patch_profile_engine(tree, str(cfg["engine_commit"]))
        build_deb(tree, out_deb)

    digest = sha256_file(out_deb)
    size = out_deb.stat().st_size
    (ROOT / "release" / f"{asset_name}.sha256").write_text(
        f"{digest}  {asset_name}\n", encoding="utf-8"
    )
    (ROOT / "release" / f"{asset_name}.size.txt").write_text(
        f"{size}\n", encoding="utf-8"
    )

    if args.update_build_toml:
        update_build_toml_hash(digest, size)

    print(f"wrote {out_deb}")
    print(f"package_version={pkg_ver}")
    print(f"sha256={digest}")
    print(f"size={size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
