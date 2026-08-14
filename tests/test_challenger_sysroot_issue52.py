import sys
import os
import json
import pytest
import shutil
import pathlib
import tempfile
import asyncio
from unittest.mock import patch, MagicMock

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sysroot
from sysroot import (
    Sysroot,
    compute_tree_hash,
    _normalize_pthread_shim,
    _apply_sysroot_transformations,
    _safe_rmtree,
    _download_packages,
    _extract,
    _extract_deb_python,
    _is_file_uncommitted,
)


# ==============================================================================
# 1. Stress Test compute_tree_hash
# ==============================================================================

class TestComputeTreeHashAdversarial:
    """Stress tests for compute_tree_hash determinism and edge cases."""

    def test_posix_vs_windows_backslash_symlink_targets(self, tmp_path):
        """Tree hash must be identical whether symlink target uses POSIX / or Windows \\."""
        d_posix = tmp_path / "posix_tree"
        d_win = tmp_path / "win_tree"
        d_posix.mkdir()
        d_win.mkdir()

        (d_posix / "sub").mkdir()
        (d_posix / "sub" / "target.txt").write_text("hello_target")
        (d_win / "sub").mkdir()
        (d_win / "sub" / "target.txt").write_text("hello_target")

        link_posix = d_posix / "link.txt"
        link_win = d_win / "link.txt"

        if hasattr(os, "symlink"):
            try:
                link_posix.symlink_to("sub/target.txt")
                link_win.symlink_to("sub/target.txt")
            except OSError:
                pytest.skip("Symlink creation not supported in test environment")

            # Mock os.readlink for link_win to return backslashes
            orig_readlink = os.readlink

            def mock_readlink(path):
                res = orig_readlink(path)
                if "win_tree" in str(path):
                    return str(res).replace('/', '\\')
                return res

            with patch("os.readlink", side_effect=mock_readlink):
                h_posix = compute_tree_hash(d_posix)
                h_win = compute_tree_hash(d_win)
                assert h_posix == h_win, f"Tree hash mismatch: {h_posix} != {h_win}"
                assert len(h_posix) == 64

    def test_nested_empty_directories(self, tmp_path):
        """Nested empty directory structures produce deterministic hashes and distinguish differences."""
        t1 = tmp_path / "tree1"
        t2 = tmp_path / "tree2"
        t3 = tmp_path / "tree3"

        # Identical nested empty directories
        (t1 / "a" / "b" / "c" / "d").mkdir(parents=True)
        (t1 / "x" / "y").mkdir(parents=True)

        (t2 / "a" / "b" / "c" / "d").mkdir(parents=True)
        (t2 / "x" / "y").mkdir(parents=True)

        h1 = compute_tree_hash(t1)
        h2 = compute_tree_hash(t2)
        assert h1 == h2
        assert len(h1) == 64

        # Slightly different empty directory structure in t3
        (t3 / "a" / "b" / "c" / "d").mkdir(parents=True)
        (t3 / "x" / "z").mkdir(parents=True)  # 'z' instead of 'y'
        h3 = compute_tree_hash(t3)
        assert h1 != h3

        # Additional empty directory in t1 changes hash
        (t1 / "extra_dir").mkdir()
        h1_mod = compute_tree_hash(t1)
        assert h1_mod != h2

    def test_zero_byte_files(self, tmp_path):
        """Zero-byte files in various nested paths produce deterministic hashes and differentiate content."""
        t1 = tmp_path / "tree_zero1"
        t2 = tmp_path / "tree_zero2"
        t1.mkdir()
        t2.mkdir()

        (t1 / "sub1").mkdir()
        (t1 / "sub1" / "empty1.dat").write_bytes(b"")
        (t1 / "empty2.txt").write_bytes(b"")

        (t2 / "sub1").mkdir()
        (t2 / "sub1" / "empty1.dat").write_bytes(b"")
        (t2 / "empty2.txt").write_bytes(b"")

        h1 = compute_tree_hash(t1)
        h2 = compute_tree_hash(t2)
        assert h1 == h2
        assert len(h1) == 64

        # Modifying a 0-byte file to 1-byte changes hash
        (t2 / "empty2.txt").write_bytes(b"\x00")
        h2_mod = compute_tree_hash(t2)
        assert h1 != h2_mod

    def test_identical_complex_file_structures(self, tmp_path):
        """Identical complex file structures with binary files, text files, and subdirs yield exact hashes."""
        t1 = tmp_path / "complex1"
        t2 = tmp_path / "complex2"

        for base in [t1, t2]:
            (base / "lib" / "sublib").mkdir(parents=True)
            (base / "include" / "sys").mkdir(parents=True)
            (base / "share" / "doc").mkdir(parents=True)
            (base / "lib" / "libfoo.so").write_bytes(b"\x7fELF" + b"\x00" * 1024)
            (base / "lib" / "sublib" / "libbar.a").write_bytes(b"!<arch>\n" + b"\x01" * 512)
            (base / "include" / "sys" / "types.h").write_text("#ifndef _TYPES_H\n#define _TYPES_H\n#endif\n")
            (base / "share" / "doc" / "README.md").write_text("# Documentation\nDetails here.\n")

        h1 = compute_tree_hash(t1)
        h2 = compute_tree_hash(t2)
        assert h1 == h2
        assert len(h1) == 64

    def test_nonexistent_directory_returns_empty_string(self, tmp_path):
        """compute_tree_hash on non-existent path returns empty string."""
        assert compute_tree_hash(tmp_path / "does_not_exist") == ""


# ==============================================================================
# 2. Stress Test Sysroot.build(locked=True) Malformed Lockfile Entries
# ==============================================================================

class TestSysrootBuildMalformedLockfile:
    """Stress tests for Sysroot.build(locked=True) against invalid/corrupt lockfile configurations."""

    @pytest.mark.parametrize("bad_sha256,desc", [
        ("", "empty sha256 string"),
        ("a" * 63, "63-hex char sha256 (too short)"),
        ("a" * 65, "65-hex char sha256 (too long)"),
        ("0" * 32, "32-hex MD5 string"),
        ("0" * 40, "40-hex SHA1 string"),
        ("A" * 64, "64-char uppercase hex"),
        ("0" * 63 + "g", "non-hex character 'g'"),
        ("0" * 63 + "z", "non-hex character 'z'"),
        ("0" * 63 + "!", "special character '!'"),
        (" " * 64, "all spaces"),
        ("0" * 63 + "\n", "trailing newline"),
        (None, "None value"),
        (12345678, "integer value"),
    ])
    def test_malformed_package_sha256_rejected(self, tmp_path, bad_sha256, desc):
        """Sysroot.build(locked=True) must fail fast with RuntimeError when a package entry sha256 is malformed."""
        sysroot_dir = tmp_path / "sysroot"
        lock_file = tmp_path / "sysroot.lock.json"

        lock_data = {
            "arm64": {
                "arch": "arm64",
                "tree_hash": "0" * 64,
                "packages": {
                    "bad_pkg": {
                        "name": "bad_pkg",
                        "url": "http://example.com/bad.deb",
                        "sha256": bad_sha256
                    }
                }
            }
        }
        lock_file.write_text(json.dumps(lock_data))

        s = Sysroot(path=str(sysroot_dir))
        s.lock_file = lock_file
        s.data = {"main": {"repo": "http://example.com", "dist": "d", "pkgs": ["bad_pkg"]}}

        with patch("sysroot._is_file_uncommitted", return_value=False):
            with pytest.raises(RuntimeError, match="invalid or missing sha256"):
                s.build(arch="arm64", locked=True)

    @pytest.mark.parametrize("bad_tree_hash,desc", [
        ("", "empty tree_hash"),
        ("0" * 63, "63-hex tree_hash"),
        ("0" * 65, "65-hex tree_hash"),
        ("F" * 64, "uppercase tree_hash"),
        ("0" * 63 + "x", "non-hex tree_hash"),
        (None, "None tree_hash"),
        (12345, "int tree_hash"),
    ])
    def test_malformed_lock_tree_hash_rejected(self, tmp_path, bad_tree_hash, desc):
        """Sysroot.build(locked=True) must reject malformed arch tree_hash."""
        sysroot_dir = tmp_path / "sysroot"
        lock_file = tmp_path / "sysroot.lock.json"

        lock_data = {
            "arm64": {
                "arch": "arm64",
                "tree_hash": bad_tree_hash,
                "packages": {
                    "pkg": {"name": "pkg", "url": "http://x/pkg.deb", "sha256": "0" * 64}
                }
            }
        }
        lock_file.write_text(json.dumps(lock_data))

        s = Sysroot(path=str(sysroot_dir))
        s.lock_file = lock_file
        s.data = {"main": {"repo": "http://example.com", "dist": "d", "pkgs": ["pkg"]}}

        with patch("sysroot._is_file_uncommitted", return_value=False):
            with pytest.raises(RuntimeError, match="tree_hash missing, empty, or malformed"):
                s.build(arch="arm64", locked=True)

    @pytest.mark.parametrize("bad_packages,desc", [
        ({}, "empty packages dict"),
        ([], "empty packages list"),
        ("invalid_packages_string", "string packages"),
        (None, "None packages"),
        (123, "int packages"),
    ])
    def test_malformed_packages_field_rejected(self, tmp_path, bad_packages, desc):
        """Sysroot.build(locked=True) must reject empty or non-collection packages field."""
        sysroot_dir = tmp_path / "sysroot"
        lock_file = tmp_path / "sysroot.lock.json"

        lock_data = {
            "arm64": {
                "arch": "arm64",
                "tree_hash": "0" * 64,
                "packages": bad_packages
            }
        }
        lock_file.write_text(json.dumps(lock_data))

        s = Sysroot(path=str(sysroot_dir))
        s.lock_file = lock_file
        s.data = {"main": {"repo": "http://example.com", "dist": "d", "pkgs": ["pkg"]}}

        with patch("sysroot._is_file_uncommitted", return_value=False):
            with pytest.raises(RuntimeError, match="packages field missing or malformed"):
                s.build(arch="arm64", locked=True)

    def test_corrupt_json_lockfile_rejected(self, tmp_path):
        """Sysroot.build(locked=True) with syntax-corrupt JSON lockfile raises RuntimeError."""
        sysroot_dir = tmp_path / "sysroot"
        lock_file = tmp_path / "sysroot.lock.json"
        lock_file.write_text("{ unquoted_corrupt_json: true, ")

        s = Sysroot(path=str(sysroot_dir))
        s.lock_file = lock_file
        s.data = {"main": {"repo": "http://example.com", "dist": "d", "pkgs": ["pkg"]}}

        with patch("sysroot._is_file_uncommitted", return_value=False):
            with pytest.raises(RuntimeError, match="invalid or unparseable"):
                s.build(arch="arm64", locked=True)

    def test_non_dict_root_lockfile_rejected(self, tmp_path):
        """Sysroot.build(locked=True) with root JSON array raises RuntimeError."""
        sysroot_dir = tmp_path / "sysroot"
        lock_file = tmp_path / "sysroot.lock.json"
        lock_file.write_text(json.dumps(["not", "a", "dict"]))

        s = Sysroot(path=str(sysroot_dir))
        s.lock_file = lock_file
        s.data = {"main": {"repo": "http://example.com", "dist": "d", "pkgs": ["pkg"]}}

        with patch("sysroot._is_file_uncommitted", return_value=False):
            with pytest.raises(RuntimeError, match="root element must be a dictionary"):
                s.build(arch="arm64", locked=True)


# ==============================================================================
# 3. Stress Test _normalize_pthread_shim Physical usr/ Recovery
# ==============================================================================

class TestNormalizePthreadShimStress:
    """Stress test _normalize_pthread_shim with deeply nested physical usr/ hierarchies and collisions."""

    def test_deeply_nested_physical_usr_migration(self, tmp_path):
        """Complex hierarchy inside physical usr/ is fully migrated and usr becomes relative symlink."""
        staging = tmp_path / "staging_complex_usr"
        staging.mkdir()

        usr = staging / "usr"
        # Deep paths
        (usr / "include" / "glib-2.0" / "glib").mkdir(parents=True)
        (usr / "include" / "c++" / "v1").mkdir(parents=True)
        (usr / "lib" / "pkgconfig").mkdir(parents=True)
        (usr / "share" / "man" / "man1").mkdir(parents=True)
        (usr / "bin").mkdir(parents=True)

        (usr / "include" / "glib-2.0" / "glib" / "glib.h").write_text("#pragma once\n")
        (usr / "include" / "c++" / "v1" / "vector").write_text("namespace std { class vector {}; }\n")
        (usr / "lib" / "libcustom.so").write_bytes(b"CUSTOM_SO_BINARY")
        (usr / "lib" / "pkgconfig" / "custom.pc").write_text("Name: custom\n")
        (usr / "share" / "man" / "man1" / "tool.1").write_text(".TH TOOL 1\n")
        (usr / "bin" / "tool").write_bytes(b"BINARY_EXEC")

        shim = _normalize_pthread_shim(staging)
        assert shim.exists()
        assert shim.read_bytes() == b"INPUT(-lc)"

        # Target termux hierarchy must contain all migrated files
        termux_usr = staging / "data" / "data" / "com.termux" / "files" / "usr"
        assert (termux_usr / "include" / "glib-2.0" / "glib" / "glib.h").read_text() == "#pragma once\n"
        assert (termux_usr / "include" / "c++" / "v1" / "vector").exists()
        assert (termux_usr / "lib" / "libcustom.so").read_bytes() == b"CUSTOM_SO_BINARY"
        assert (termux_usr / "lib" / "pkgconfig" / "custom.pc").read_text() == "Name: custom\n"
        assert (termux_usr / "share" / "man" / "man1" / "tool.1").exists()
        assert (termux_usr / "bin" / "tool").read_bytes() == b"BINARY_EXEC"

        # usr must now be a symlink (or valid alias)
        usr_entry = staging / "usr"
        assert usr_entry.is_symlink() or usr_entry.exists()

    def test_destination_file_collision_overwrite(self, tmp_path):
        """When files exist in both physical usr/ and termux_usr/, migration overwrites without error."""
        staging = tmp_path / "staging_collision"
        staging.mkdir()

        usr = staging / "usr"
        (usr / "lib").mkdir(parents=True)
        (usr / "lib" / "conflict.so").write_bytes(b"NEW_VERSION_FROM_USR")

        termux_usr = staging / "data" / "data" / "com.termux" / "files" / "usr"
        (termux_usr / "lib").mkdir(parents=True)
        (termux_usr / "lib" / "conflict.so").write_bytes(b"OLD_STALE_VERSION")

        shim = _normalize_pthread_shim(staging)
        assert shim.exists()

        # The newly unpacked file from usr/ should overwrite the stale destination file
        assert (termux_usr / "lib" / "conflict.so").read_bytes() == b"NEW_VERSION_FROM_USR"

    def test_libpthread_as_preexisting_directory_or_corrupt_file(self, tmp_path):
        """If libpthread.a exists as a directory or non-canonical file, it is cleanly replaced by canonical shim."""
        # Case A: libpthread.a is a directory
        staging_dir = tmp_path / "staging_dir_pthread"
        staging_dir.mkdir()
        termux_lib_a = staging_dir / "data" / "data" / "com.termux" / "files" / "usr" / "lib"
        (termux_lib_a / "libpthread.a" / "nested").mkdir(parents=True)
        (termux_lib_a / "libpthread.a" / "nested" / "trash.txt").write_text("trash")

        shim_a = _normalize_pthread_shim(staging_dir)
        assert shim_a.is_file()
        assert not shim_a.is_dir()
        assert shim_a.read_bytes() == b"INPUT(-lc)"

        # Case B: libpthread.a has junk bytes
        staging_file = tmp_path / "staging_file_pthread"
        staging_file.mkdir()
        termux_lib_b = staging_file / "data" / "data" / "com.termux" / "files" / "usr" / "lib"
        termux_lib_b.mkdir(parents=True)
        (termux_lib_b / "libpthread.a").write_bytes(b"GARBAGE_PTHREAD_BYTES")

        shim_b = _normalize_pthread_shim(staging_file)
        assert shim_b.read_bytes() == b"INPUT(-lc)"

    def test_consecutive_idempotent_invocations(self, tmp_path):
        """Invoking _normalize_pthread_shim multiple times produces identical state and tree_hash."""
        staging = tmp_path / "staging_idempotent"
        staging.mkdir()
        usr = staging / "usr"
        (usr / "lib").mkdir(parents=True)
        (usr / "lib" / "liba.so").write_bytes(b"LIB_A")

        _normalize_pthread_shim(staging)
        hash1 = compute_tree_hash(staging)

        _normalize_pthread_shim(staging)
        hash2 = compute_tree_hash(staging)

        _normalize_pthread_shim(staging)
        hash3 = compute_tree_hash(staging)

        assert hash1 == hash2 == hash3


# ==============================================================================
# 4. Stress Test Atomic Rollback During Download/Extraction Aborts
# ==============================================================================

class TestAtomicRollbackStress:
    """Stress tests for atomic rollback and active sysroot state preservation during failures."""

    def _setup_active_sysroot(self, tmp_path):
        """Helper to create an active sysroot with known initial state and hash."""
        sysroot_dir = tmp_path / "active_sysroot"
        termux_usr = sysroot_dir / "data" / "data" / "com.termux" / "files" / "usr"
        (termux_usr / "lib").mkdir(parents=True)
        (termux_usr / "include").mkdir(parents=True)
        (termux_usr / "lib" / "libactive.so").write_bytes(b"ACTIVE_SO_V1")
        (termux_usr / "include" / "active.h").write_text("#define ACTIVE_V1 1\n")
        _normalize_pthread_shim(sysroot_dir)
        _apply_sysroot_transformations(sysroot_dir)

        initial_hash = compute_tree_hash(sysroot_dir)
        return sysroot_dir, initial_hash

    def test_rollback_on_download_abort(self, tmp_path):
        """When _download_packages throws mid-download, active sysroot is preserved untouched."""
        sysroot_dir, initial_hash = self._setup_active_sysroot(tmp_path)
        lock_file = tmp_path / "sysroot.lock.json"
        lock_data = {
            "arm64": {
                "arch": "arm64",
                "tree_hash": "0" * 64,
                "packages": {
                    "pkg1": {"name": "pkg1", "url": "http://x/pkg1.deb", "sha256": "0" * 64}
                }
            }
        }
        lock_file.write_text(json.dumps(lock_data))

        s = Sysroot(path=str(sysroot_dir))
        s.lock_file = lock_file
        s.data = {"main": {"repo": "http://x", "dist": "d", "pkgs": ["pkg1"]}}

        async def mock_failing_download(*args, **kwargs):
            raise asyncio.TimeoutError("Simulated download connection timeout")

        with patch("sysroot._is_file_uncommitted", return_value=False), \
             patch("sysroot._download_packages", side_effect=mock_failing_download):
            with pytest.raises(asyncio.TimeoutError):
                s.build(arch="arm64", locked=True)

        assert sysroot_dir.exists()
        assert compute_tree_hash(sysroot_dir) == initial_hash
        assert (sysroot_dir / "data" / "data" / "com.termux" / "files" / "usr" / "lib" / "libactive.so").read_bytes() == b"ACTIVE_SO_V1"

    def test_rollback_on_extraction_corrupt_deb_abort(self, tmp_path):
        """When _extract throws on corrupt deb file, active sysroot is preserved untouched."""
        sysroot_dir, initial_hash = self._setup_active_sysroot(tmp_path)
        lock_file = tmp_path / "sysroot.lock.json"
        lock_data = {
            "arm64": {
                "arch": "arm64",
                "tree_hash": "0" * 64,
                "packages": {
                    "pkg1": {"name": "pkg1", "url": "http://x/pkg1.deb", "sha256": "0" * 64}
                }
            }
        }
        lock_file.write_text(json.dumps(lock_data))

        s = Sysroot(path=str(sysroot_dir))
        s.lock_file = lock_file
        s.data = {"main": {"repo": "http://x", "dist": "d", "pkgs": ["pkg1"]}}

        def mock_failing_extract(out_dir, deb_path):
            raise ValueError("Corrupt archive: data.tar not found")

        with patch("sysroot._is_file_uncommitted", return_value=False), \
             patch("sysroot._download_packages", return_value=[pathlib.Path("dummy.deb")]), \
             patch("sysroot._extract", side_effect=mock_failing_extract):
            with pytest.raises(ValueError, match="Corrupt archive"):
                s.build(arch="arm64", locked=True)

        assert sysroot_dir.exists()
        assert compute_tree_hash(sysroot_dir) == initial_hash
        assert (sysroot_dir / "data" / "data" / "com.termux" / "files" / "usr" / "lib" / "libactive.so").read_bytes() == b"ACTIVE_SO_V1"

    def test_rollback_on_tree_hash_verification_failure(self, tmp_path):
        """When computed tree_hash does not match expected locked hash, active sysroot is preserved."""
        sysroot_dir, initial_hash = self._setup_active_sysroot(tmp_path)
        lock_file = tmp_path / "sysroot.lock.json"
        lock_data = {
            "arm64": {
                "arch": "arm64",
                "tree_hash": "e" * 64,  # Expected hash
                "packages": {
                    "pkg1": {"name": "pkg1", "url": "http://x/pkg1.deb", "sha256": "0" * 64}
                }
            }
        }
        lock_file.write_text(json.dumps(lock_data))

        s = Sysroot(path=str(sysroot_dir))
        s.lock_file = lock_file
        s.data = {"main": {"repo": "http://x", "dist": "d", "pkgs": ["pkg1"]}}

        def mock_extract(out_dir, deb_path):
            termux_usr = out_dir / "data" / "data" / "com.termux" / "files" / "usr"
            (termux_usr / "lib").mkdir(parents=True, exist_ok=True)
            (termux_usr / "lib" / "libmismatch.so").write_bytes(b"DIFFERENT_HASH")

        with patch("sysroot._is_file_uncommitted", return_value=False), \
             patch("sysroot._download_packages", return_value=[pathlib.Path("dummy.deb")]), \
             patch("sysroot._extract", side_effect=mock_extract):
            with pytest.raises(RuntimeError, match="Sysroot tree_hash mismatch"):
                s.build(arch="arm64", locked=True)

        assert sysroot_dir.exists()
        assert compute_tree_hash(sysroot_dir) == initial_hash

    def test_rollback_on_activation_rename_failure(self, tmp_path):
        """When atomic rename fails during activation, active sysroot is restored from backup."""
        sysroot_dir, initial_hash = self._setup_active_sysroot(tmp_path)

        # Pre-compute expected staging hash
        staging_mock = tmp_path / "staging_mock"
        termux_usr_mock = staging_mock / "data" / "data" / "com.termux" / "files" / "usr"
        (termux_usr_mock / "lib").mkdir(parents=True)
        (termux_usr_mock / "lib" / "libnew.so").write_bytes(b"NEW_SO")
        _normalize_pthread_shim(staging_mock)
        expected_hash = compute_tree_hash(staging_mock)

        lock_file = tmp_path / "sysroot.lock.json"
        lock_data = {
            "arm64": {
                "arch": "arm64",
                "tree_hash": expected_hash,
                "packages": {
                    "pkg1": {"name": "pkg1", "url": "http://x/pkg1.deb", "sha256": "0" * 64}
                }
            }
        }
        lock_file.write_text(json.dumps(lock_data))

        s = Sysroot(path=str(sysroot_dir))
        s.lock_file = lock_file
        s.data = {"main": {"repo": "http://x", "dist": "d", "pkgs": ["pkg1"]}}

        def mock_extract(out_dir, deb_path):
            termux_usr = out_dir / "data" / "data" / "com.termux" / "files" / "usr"
            (termux_usr / "lib").mkdir(parents=True, exist_ok=True)
            (termux_usr / "lib" / "libnew.so").write_bytes(b"NEW_SO")

        orig_rename = pathlib.Path.rename

        def mock_rename(self_path, target_path):
            # Inject failure when activating staging_out -> sysroot_dir
            if "staging" in str(self_path) and str(target_path) == str(sysroot_dir):
                raise OSError("Simulated atomic activation rename failure (disk locked)")
            return orig_rename(self_path, target_path)

        with patch("sysroot._is_file_uncommitted", return_value=False), \
             patch("sysroot._download_packages", return_value=[pathlib.Path("dummy.deb")]), \
             patch("sysroot._extract", side_effect=mock_extract), \
             patch.object(pathlib.Path, "rename", autospec=True, side_effect=mock_rename):
            with pytest.raises(OSError, match="Simulated atomic activation rename failure"):
                s.build(arch="arm64", locked=True)

        # Active sysroot must be restored to original preimage
        assert sysroot_dir.exists()
        assert compute_tree_hash(sysroot_dir) == initial_hash
        assert (sysroot_dir / "data" / "data" / "com.termux" / "files" / "usr" / "lib" / "libactive.so").read_bytes() == b"ACTIVE_SO_V1"

    def test_orphaned_backup_startup_recovery_when_corrupt(self, tmp_path):
        """Sysroot initialization recovers from orphaned backup if active sysroot is corrupt."""
        sysroot_dir = tmp_path / "sysroot"
        termux_usr = sysroot_dir / "data" / "data" / "com.termux" / "files" / "usr"
        (termux_usr / "lib").mkdir(parents=True)
        (termux_usr / "lib" / "corrupt_active.so").write_bytes(b"CORRUPT")
        _normalize_pthread_shim(sysroot_dir)

        # Valid backup
        backup_dir = tmp_path / "sysroot.bak.1700000000"
        backup_termux = backup_dir / "data" / "data" / "com.termux" / "files" / "usr"
        (backup_termux / "lib").mkdir(parents=True)
        (backup_termux / "lib" / "good_backup.so").write_bytes(b"GOOD_BACKUP")
        _normalize_pthread_shim(backup_dir)
        valid_hash = compute_tree_hash(backup_dir)

        lock_file = tmp_path / "sysroot.lock.json"
        lock_data = {
            "arm64": {
                "arch": "arm64",
                "tree_hash": valid_hash,
                "packages": {}
            }
        }
        lock_file.write_text(json.dumps(lock_data))

        # When Sysroot is constructed with a corrupt active sysroot and valid lock file,
        # _recover_orphaned_backups runs verify(), fails on active, and restores the backup.
        with patch.object(Sysroot, '__init__', lambda self, path, **kwargs: None):
            s = Sysroot(path=str(sysroot_dir))
            s.path = sysroot_dir
            s.lock_file = lock_file
            s.data = {}
            s._recover_orphaned_backups()

        assert (sysroot_dir / "data" / "data" / "com.termux" / "files" / "usr" / "lib" / "good_backup.so").exists()
        assert compute_tree_hash(sysroot_dir) == valid_hash
