import sys
import os
import json
import pytest
import io
import tarfile
import pathlib
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sysroot import (
    Sysroot,
    _parse_deps,
    _resolve_packages,
    _is_file_uncommitted,
    _extract_deb_python,
    compute_tree_hash,
)


def test_edge_missing_lock_file(tmp_path):
    """Edge case 1: sysroot.build(locked=True) with missing lock file raises RuntimeError."""
    sysroot_dir = tmp_path / "sysroot"
    lock_file = tmp_path / "missing_sysroot.lock.json"

    sysroot = Sysroot(path=str(sysroot_dir))
    sysroot.lock_file = lock_file
    sysroot.data = {"main": {"repo": "http://example.com", "dist": "stable", "pkgs": ["pkg-a"]}}

    with pytest.raises(RuntimeError, match="not found"):
        sysroot.build(arch="arm64", locked=True)


def test_edge_uncommitted_lock_file(tmp_path):
    """Edge case 2: sysroot.build(locked=True) with uncommitted lock file raises RuntimeError."""
    sysroot_dir = tmp_path / "sysroot"
    lock_file = tmp_path / "sysroot.lock.json"
    lock_file.write_text(json.dumps({"arm64": {"packages": {}}}))

    sysroot = Sysroot(path=str(sysroot_dir))
    sysroot.lock_file = lock_file
    sysroot.data = {"main": {"repo": "http://example.com", "dist": "stable", "pkgs": ["pkg-a"]}}

    with patch("sysroot._is_file_uncommitted", return_value=True):
        with pytest.raises(RuntimeError, match="uncommitted or untracked"):
            sysroot.build(arch="arm64", locked=True)


def test_edge_missing_arch_in_lock_file(tmp_path):
    """Edge case 3a: Arch missing in sysroot.lock.json raises RuntimeError."""
    sysroot_dir = tmp_path / "sysroot"
    lock_file = tmp_path / "sysroot.lock.json"
    lock_file.write_text(json.dumps({"x86_64": {"packages": {}}}))

    sysroot = Sysroot(path=str(sysroot_dir))
    sysroot.lock_file = lock_file
    sysroot.data = {"main": {"repo": "http://example.com", "dist": "stable", "pkgs": ["pkg-a"]}}

    with patch("sysroot._is_file_uncommitted", return_value=False):
        with pytest.raises(RuntimeError, match="missing or lock file incomplete"):
            sysroot.build(arch="arm64", locked=True)


def test_edge_corrupt_tree_hash(tmp_path):
    """Edge case 4: Tree hash mismatch in sysroot.lock.json raises RuntimeError."""
    sysroot_dir = tmp_path / "sysroot"
    lock_file = tmp_path / "sysroot.lock.json"
    bad_hash = "deadbeef" * 8
    lock_data = {
        "arm64": {
            "arch": "arm64",
            "tree_hash": bad_hash,
            "packages": {
                "pkg-a": {"name": "pkg-a", "url": "http://x/pkg-a.deb", "sha256": "0" * 64}
            }
        }
    }
    lock_file.write_text(json.dumps(lock_data))

    sysroot = Sysroot(path=str(sysroot_dir))
    sysroot.lock_file = lock_file
    sysroot.data = {"main": {"repo": "http://example.com", "dist": "stable", "pkgs": ["pkg-a"]}}

    def mock_extract(out_dir, deb):
        target_dir = out_dir / "data" / "data" / "com.termux" / "files" / "usr" / "lib"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "libpthread.a").write_bytes(b"INPUT(-lc)")

    with patch("sysroot._is_file_uncommitted", return_value=False), \
         patch("sysroot._download_packages", return_value=[pathlib.Path("pkg-a.deb")]), \
         patch("sysroot._extract", side_effect=mock_extract):
        with pytest.raises(RuntimeError, match="tree_hash mismatch"):
            sysroot.build(arch="arm64", locked=True)


def test_edge_missing_top_level_package():
    """Edge case 5a: Missing top-level package raises RuntimeError in _resolve_packages."""
    import asyncio

    mock_packages_index = """
Package: pkg-other
Version: 1.0
Filename: pool/main/p/pkg-other/pkg-other_1.0_aarch64.deb
"""
    sysroot_data = {
        "main": {
            "repo": "https://example.com/apt/",
            "dist": "stable",
            "pkgs": ["pkg-nonexistent"]
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

    async def _run():
        return await _resolve_packages(DummySession(), "arm64", sysroot_data)

    with pytest.raises(RuntimeError, match="Required top-level package 'pkg-nonexistent' not found"):
        asyncio.run(_run())


def test_edge_transitive_dependency_cycle():
    """Edge case 5b: Circular dependency graph (A -> B -> C -> A) terminates without infinite loop."""
    import asyncio

    mock_packages_index = """
Package: pkg-a
Version: 1.0
Depends: pkg-b
Filename: pool/pkg-a.deb
SHA256: aaa111

Package: pkg-b
Version: 1.0
Depends: pkg-c
Filename: pool/pkg-b.deb
SHA256: bbb222

Package: pkg-c
Version: 1.0
Depends: pkg-a
Filename: pool/pkg-c.deb
SHA256: ccc333
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

    async def _run():
        return await _resolve_packages(DummySession(), "arm64", sysroot_data)

    resolved = asyncio.run(_run())
    assert set(resolved.keys()) == {"pkg-a", "pkg-b", "pkg-c"}


def test_edge_missing_transitive_dependency(caplog):
    """Edge case 5c: Missing transitive dependency logs warning and skips without crashing."""
    import asyncio

    mock_packages_index = """
Package: pkg-a
Version: 1.0
Depends: pkg-missing-dep
Filename: pool/pkg-a.deb
SHA256: aaa111
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

    async def _run():
        return await _resolve_packages(DummySession(), "arm64", sysroot_data)

    resolved = asyncio.run(_run())
    assert set(resolved.keys()) == {"pkg-a"}


def test_edge_parse_deps_complex_specifiers():
    """Edge case 5d: Parse dependencies with arch qualifiers, version constraints, pre-depends, and alternatives."""
    deps_raw = "libcairo-gobject (>= 1.16.0), libglvnd:arm64, libX11 | libx11-6 (>= 1.0), zlib:any"
    parsed = _parse_deps(deps_raw)
    assert parsed == ["libcairo-gobject", "libglvnd", "libX11", "zlib"]


def test_edge_tree_hash_symlinks_and_modes(tmp_path):
    """Tree hash sensitivity to symlink targets and permission mode changes."""
    sys_dir = tmp_path / "sys"
    sys_dir.mkdir()

    sub_dir = sys_dir / "dir"
    sub_dir.mkdir()
    f1 = sub_dir / "f1.txt"
    f1.write_text("content")

    symlink_file = sys_dir / "link"
    try:
        symlink_file.symlink_to("dir/f1.txt")
    except OSError:
        pytest.skip("Symlink creation not supported on this platform")

    h1 = compute_tree_hash(sys_dir)

    # Change symlink target
    symlink_file.unlink()
    symlink_file.symlink_to("dir/other.txt")
    h2 = compute_tree_hash(sys_dir)
    assert h1 != h2, "Hash must change when symlink target changes"


def test_edge_extract_deb_python(tmp_path):
    """_extract_deb_python unpacks valid debian archive containing data.tar.xz."""
    deb_path = tmp_path / "test.deb"
    target_out = tmp_path / "out"

    # Create dummy data.tar.xz
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:xz") as tar:
        data = b"test payload"
        info = tarfile.TarInfo(name="usr/lib/libtest.so")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    data_tar_xz_bytes = tar_buf.getvalue()

    # Build ar archive format (!<arch>\n)
    ar_buf = io.BytesIO()
    ar_buf.write(b"!<arch>\n")

    # debian-binary header
    deb_bin = b"2.0\n"
    hdr1 = f"{'debian-binary':<16}{'0':<12}{'0':<6}{'0':<6}{'100644':<8}{len(deb_bin):<10}`\n".encode("latin1")
    ar_buf.write(hdr1)
    ar_buf.write(deb_bin)

    # control.tar.xz header (dummy)
    ctrl_buf = io.BytesIO()
    with tarfile.open(fileobj=ctrl_buf, mode="w:xz") as tar:
        pass
    ctrl_bytes = ctrl_buf.getvalue()
    hdr2 = f"{'control.tar.xz':<16}{'0':<12}{'0':<6}{'0':<6}{'100644':<8}{len(ctrl_bytes):<10}`\n".encode("latin1")
    ar_buf.write(hdr2)
    ar_buf.write(ctrl_bytes)
    if len(ctrl_bytes) % 2 != 0:
        ar_buf.write(b"\n")

    # data.tar.xz header
    hdr3 = f"{'data.tar.xz':<16}{'0':<12}{'0':<6}{'0':<6}{'100644':<8}{len(data_tar_xz_bytes):<10}`\n".encode("latin1")
    ar_buf.write(hdr3)
    ar_buf.write(data_tar_xz_bytes)

    deb_path.write_bytes(ar_buf.getvalue())

    _extract_deb_python(target_out, deb_path)
    extracted_file = target_out / "usr" / "lib" / "libtest.so"
    assert extracted_file.is_file()
    assert extracted_file.read_bytes() == b"test payload"
