import sys
import os
import json
import pytest
import shutil
import pathlib
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sysroot import (
    Sysroot,
    _parse_deps,
    _resolve_packages,
    _is_file_uncommitted,
    compute_tree_hash,
)


def test_parse_deps():
    assert _parse_deps("libcairo (>= 1.16.0), libffi, zlib") == ["libcairo", "libffi", "zlib"]
    assert _parse_deps("zlib | zlib1g, dpkg (>= 1.19.0)") == ["zlib", "dpkg"]
    assert _parse_deps("libglvnd (>= 1.3.0)") == ["libglvnd"]
    assert _parse_deps("") == []


def test_compute_tree_hash_determinism(tmp_path):
    d1 = tmp_path / "sys1"
    d2 = tmp_path / "sys2"
    d1.mkdir()
    d2.mkdir()

    (d1 / "dirA").mkdir()
    (d1 / "dirA" / "file1.txt").write_text("hello world")
    (d1 / "file2.txt").write_text("another file")

    (d2 / "dirA").mkdir()
    (d2 / "dirA" / "file1.txt").write_text("hello world")
    (d2 / "file2.txt").write_text("another file")

    h1 = compute_tree_hash(d1)
    h2 = compute_tree_hash(d2)

    assert len(h1) == 64
    assert h1 == h2

    # Change content in d2 -> hash changes
    (d2 / "file2.txt").write_text("modified file")
    h3 = compute_tree_hash(d2)
    assert h1 != h3


@pytest.mark.asyncio
async def test_transitive_dependency_resolution():
    mock_packages_index = """
Package: pkg-a
Version: 1.0
Depends: pkg-b (>= 2.0), pkg-c
Filename: pool/main/p/pkg-a/pkg-a_1.0_aarch64.deb
Size: 1000
SHA256: aaa111

Package: pkg-b
Version: 2.0
Pre-Depends: pkg-d
Filename: pool/main/p/pkg-b/pkg-b_2.0_aarch64.deb
Size: 2000
SHA256: bbb222

Package: pkg-c
Version: 3.0
Filename: pool/main/p/pkg-c/pkg-c_3.0_aarch64.deb
Size: 3000
SHA256: ccc333

Package: pkg-d
Version: 4.0
Filename: pool/main/p/pkg-d/pkg-d_4.0_aarch64.deb
Size: 4000
SHA256: ddd444
"""
    sysroot_data = {
        "main": {
            "repo": "https://example.com/apt/",
            "dist": "stable",
            "pkgs": ["pkg-a"]
        }
    }

    class DummyResponse:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        def raise_for_status(self):
            pass
        async def text(self):
            return mock_packages_index

    class DummySession:
        def get(self, url):
            return DummyResponse()

    sess = DummySession()
    resolved = await _resolve_packages(sess, "arm64", sysroot_data)

    assert set(resolved.keys()) == {"pkg-a", "pkg-b", "pkg-c", "pkg-d"}
    assert resolved["pkg-a"]["sha256"] == "aaa111"
    assert resolved["pkg-b"]["sha256"] == "bbb222"
    assert resolved["pkg-c"]["sha256"] == "ccc333"
    assert resolved["pkg-d"]["sha256"] == "ddd444"


def test_committed_sysroot_lockfile_exists():
    lock_file = pathlib.Path("sysroot.lock.json")
    assert lock_file.is_file(), "sysroot.lock.json must exist in repository root"
    assert not _is_file_uncommitted(lock_file), "sysroot.lock.json must be committed/tracked in git"

    with open(lock_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "arm64" in data
    arm64_data = data["arm64"]
    assert "tree_hash" in arm64_data
    assert len(arm64_data["tree_hash"]) == 64
    assert "packages" in arm64_data

    packages = arm64_data["packages"]
    assert len(packages) > 0

    sample_pkg = next(iter(packages.values()))
    required_keys = {"name", "version", "url", "sha256", "size", "archive_path", "repo", "dist"}
    assert required_keys.issubset(sample_pkg.keys())


def test_sysroot_build_locked_missing_lock_file(tmp_path):
    sysroot_dir = tmp_path / "sysroot"
    lock_file = tmp_path / "non_existent_sysroot.lock.json"

    sysroot = Sysroot(path=str(sysroot_dir))
    sysroot.lock_file = lock_file
    sysroot.data = {"main": {"repo": "http://x", "dist": "d", "pkgs": ["p"]}}

    with pytest.raises(RuntimeError, match="not found"):
        sysroot.build(arch="arm64", locked=True)


def test_sysroot_build_locked_uncommitted_lock_file(tmp_path):
    sysroot_dir = tmp_path / "sysroot"
    lock_file = tmp_path / "sysroot.lock.json"
    lock_file.write_text("{}")

    sysroot = Sysroot(path=str(sysroot_dir))
    sysroot.lock_file = lock_file
    sysroot.data = {"main": {"repo": "http://x", "dist": "d", "pkgs": ["p"]}}

    with patch("sysroot._is_file_uncommitted", return_value=True):
        with pytest.raises(RuntimeError, match="uncommitted or untracked"):
            sysroot.build(arch="arm64", locked=True)


def test_sysroot_build_locked_tree_hash_mismatch(tmp_path):
    sysroot_dir = tmp_path / "sysroot"
    lock_file = tmp_path / "sysroot.lock.json"
    lock_data = {
        "arm64": {
            "arch": "arm64",
            "tree_hash": "0" * 64,  # Intentionally wrong hash
            "packages": {
                "dummy": {"name": "dummy", "url": "http://x/dummy.deb", "sha256": "abc"}
            }
        }
    }
    lock_file.write_text(json.dumps(lock_data))

    sysroot = Sysroot(path=str(sysroot_dir))
    sysroot.lock_file = lock_file
    sysroot.data = {"main": {"repo": "http://x", "dist": "d", "pkgs": ["dummy"]}}

    def mock_extract(out_dir, deb):
        target_dir = out_dir / "data" / "data" / "com.termux" / "files" / "usr" / "lib"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "libpthread.a").write_bytes(b"INPUT(-lc)")

    with patch("sysroot._is_file_uncommitted", return_value=False), \
         patch("sysroot._download_packages", return_value=[pathlib.Path("dummy.deb")]), \
         patch("sysroot._extract", side_effect=mock_extract):
        with pytest.raises(RuntimeError, match="tree_hash mismatch"):
            sysroot.build(arch="arm64", locked=True)


def test_sysroot_build_locked_sha256_mismatch(tmp_path):
    sysroot_dir = tmp_path / "sysroot"
    lock_file = tmp_path / "sysroot.lock.json"
    lock_data = {
        "arm64": {
            "arch": "arm64",
            "tree_hash": "1" * 64,
            "packages": {
                "dummy": {"name": "dummy", "url": "http://x/dummy.deb", "sha256": "expected_hash"}
            }
        }
    }
    lock_file.write_text(json.dumps(lock_data))

    sysroot = Sysroot(path=str(sysroot_dir))
    sysroot.lock_file = lock_file
    sysroot.data = {"main": {"repo": "http://x", "dist": "d", "pkgs": ["dummy"]}}

    with patch("sysroot._is_file_uncommitted", return_value=False), \
         patch("sysroot._download_packages", side_effect=RuntimeError("SHA256 mismatch for dummy.deb")):
        with pytest.raises(RuntimeError, match="SHA256 mismatch"):
            sysroot.build(arch="arm64", locked=True)


def test_sysroot_build_locked_success(tmp_path):
    sysroot_dir = tmp_path / "sysroot"
    lock_file = tmp_path / "sysroot.lock.json"

    # Pre-calculate tree_hash for the expected staging structure
    staging_temp = tmp_path / "sample_staging"
    usr_target = staging_temp / "data" / "data" / "com.termux" / "files" / "usr"
    usr_target.mkdir(parents=True, exist_ok=True)
    lib_dir = usr_target / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "libpthread.a").write_bytes(b"INPUT(-lc)")
    (staging_temp / "usr").symlink_to("data/data/com.termux/files/usr", True)

    expected_hash = compute_tree_hash(staging_temp)

    lock_data = {
        "arm64": {
            "arch": "arm64",
            "tree_hash": expected_hash,
            "packages": {
                "dummy": {"name": "dummy", "url": "http://x/dummy.deb", "sha256": "abc"}
            }
        }
    }
    lock_file.write_text(json.dumps(lock_data))

    sysroot = Sysroot(path=str(sysroot_dir))
    sysroot.lock_file = lock_file
    sysroot.data = {"main": {"repo": "http://x", "dist": "d", "pkgs": ["dummy"]}}

    def mock_extract(out_dir, deb):
        target_dir = out_dir / "data" / "data" / "com.termux" / "files" / "usr" / "lib"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "libpthread.a").write_bytes(b"INPUT(-lc)")

    with patch("sysroot._is_file_uncommitted", return_value=False), \
         patch("sysroot._download_packages", return_value=[pathlib.Path("dummy.deb")]), \
         patch("sysroot._extract", side_effect=mock_extract):
        sysroot.build(arch="arm64", locked=True)

    assert sysroot_dir.is_dir()
    assert (sysroot_dir / "usr").is_symlink() or (sysroot_dir / "usr").exists()
    target_pthread = sysroot_dir / "data" / "data" / "com.termux" / "files" / "usr" / "lib" / "libpthread.a"
    assert target_pthread.read_bytes() == b"INPUT(-lc)"


def test_sysroot_lock_generation(tmp_path):
    sysroot_dir = tmp_path / "sysroot"
    lock_file = tmp_path / "sysroot.lock.json"

    sysroot = Sysroot(path=str(sysroot_dir))
    sysroot.lock_file = lock_file
    sysroot.data = {"main": {"repo": "http://x", "dist": "d", "pkgs": ["dummy"]}}

    mock_resolved = {
        "dummy": {
            "name": "dummy",
            "version": "1.0",
            "url": "http://x/dummy.deb",
            "sha256": "abc",
            "size": 100,
            "archive_path": "dummy.deb",
            "repo": "http://x",
            "dist": "d"
        }
    }

    def mock_extract(out_dir, deb):
        target_dir = out_dir / "data" / "data" / "com.termux" / "files" / "usr" / "lib"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "libpthread.a").write_bytes(b"INPUT(-lc)")

    async def mock_resolve_packages(sess, arch, sysroot_data):
        return mock_resolved

    async def mock_spawn(tasks):
        for t in tasks:
            t.close()
        return [pathlib.Path("dummy.deb")]

    with patch("sysroot._resolve_packages", side_effect=mock_resolve_packages), \
         patch("sysroot._spawn", side_effect=mock_spawn), \
         patch("sysroot._extract", side_effect=mock_extract):
        sysroot.lock(arch="arm64")

    assert lock_file.is_file()
    with open(lock_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "arm64" in data
    assert "aarch64" in data
    arm64_entry = data["arm64"]
    assert arm64_entry["arch"] == "arm64"
    assert "created_at" in arm64_entry
    assert "tree_hash" in arm64_entry
    assert len(arm64_entry["tree_hash"]) == 64
    assert arm64_entry["packages"] == mock_resolved

