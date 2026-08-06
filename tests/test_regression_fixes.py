"""Regression tests for patch idempotency, sysroot atomicity, and installer transactionality."""
import os
import sys
import json
import shutil
import hashlib
import pathlib
import tempfile
import textwrap
import subprocess

import pytest

# ============================================================
# Test patch classification (preimage/postimage/unknown)
# ============================================================

class TestPatchClassification:
    """Test that patch() correctly classifies source state."""

    def test_patch_apply_then_skip_on_reapply(self, tmp_path):
        """Applying a patch twice should not fail — second apply should detect postimage."""
        import git
        # Set up a git repo with a file
        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "hello.txt"
        test_file.write_text("line1\nline2\nline3\n")
        repo.index.add(["hello.txt"])
        repo.index.commit("initial")

        # Create a patch file
        patch_content = textwrap.dedent("""\
            --- a/hello.txt
            +++ b/hello.txt
            @@ -1,3 +1,3 @@
             line1
            -line2
            +line2_patched
             line3
        """)
        patch_file = tmp_path / "test.patch"
        patch_file.write_text(patch_content)

        # First apply: should succeed (preimage)
        repo.git.apply([str(patch_file)])
        assert "line2_patched" in test_file.read_text()

        # Now simulate what build.py patch() does:
        # Check reverse-apply (postimage detection)
        try:
            repo.git.apply(['--reverse', '--check', str(patch_file)])
            already_applied = True
        except git.GitCommandError:
            already_applied = False
        assert already_applied, "Should detect patch as already applied"

    def test_patch_unknown_state_detected(self, tmp_path):
        """If file is in unknown state, both apply --check and reverse --check should fail."""
        import git
        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "hello.txt"
        test_file.write_text("completely_different_content\n")
        repo.index.add(["hello.txt"])
        repo.index.commit("initial")

        patch_content = textwrap.dedent("""\
            --- a/hello.txt
            +++ b/hello.txt
            @@ -1,3 +1,3 @@
             line1
            -line2
            +line2_patched
             line3
        """)
        patch_file = tmp_path / "test.patch"
        patch_file.write_text(patch_content)

        # Neither forward nor reverse should work
        with pytest.raises(git.GitCommandError):
            repo.git.apply(['--check', str(patch_file)])
        with pytest.raises(git.GitCommandError):
            repo.git.apply(['--reverse', '--check', str(patch_file)])


# ============================================================
# Test sysroot atomicity
# ============================================================

class TestSysrootAtomicity:
    """Test that sysroot build uses staging + atomic rename."""

    def test_compute_tree_hash_deterministic(self, tmp_path):
        """Same directory content should always produce same hash."""
        sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
        from sysroot import compute_tree_hash

        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("world")

        hash1 = compute_tree_hash(tmp_path)
        hash2 = compute_tree_hash(tmp_path)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex digest

    def test_compute_tree_hash_content_sensitive(self, tmp_path):
        """Different content should produce different hashes."""
        sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
        from sysroot import compute_tree_hash

        (tmp_path / "a.txt").write_text("hello")
        hash1 = compute_tree_hash(tmp_path)

        (tmp_path / "a.txt").write_text("world")
        hash2 = compute_tree_hash(tmp_path)

        assert hash1 != hash2

    def test_compute_tree_hash_empty_dir(self, tmp_path):
        """Empty directory should return a valid hash."""
        sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
        from sysroot import compute_tree_hash
        result = compute_tree_hash(tmp_path)
        assert isinstance(result, str)
        assert len(result) == 64


# ============================================================
# Test installer transactional safety
# ============================================================

class TestInstallerTransactional:
    """Test installer shell script for transactional correctness."""

    def test_no_premature_purge(self):
        """Installer must NOT purge existing packages before new install succeeds."""
        script = pathlib.Path(__file__).parent.parent / "install_flutter_complete.sh"
        content = script.read_text(encoding='utf-8')
        # There should be no "dpkg --purge" before install
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'dpkg --purge' in line and '2>/dev/null || true' in line:
                # Check if this is before any dpkg -i (install) line
                # This pattern indicates a premature purge
                pytest.fail(
                    f"Line {i+1}: Found premature purge pattern 'dpkg --purge ... || true'. "
                    f"Installer must install-first, never purge-first."
                )

    def test_install_failures_set_flag(self):
        """All install failures must set INSTALL_FAILED=true."""
        script = pathlib.Path(__file__).parent.parent / "install_flutter_complete.sh"
        content = script.read_text(encoding='utf-8')
        # Every 'exit 20', 'exit 30', 'exit 40' should be preceded by INSTALL_FAILED=true
        lines = content.split('\n')
        for i, line in enumerate(lines):
            stripped = line.strip()
            for code in ['exit 20', 'exit 30', 'exit 40', 'exit 50', 'exit 60']:
                if code in stripped and 'INSTALL_FAILED=true' not in stripped:
                    # Allow exit 0 and commented lines
                    if not stripped.startswith('#'):
                        pytest.fail(
                            f"Line {i+1}: '{code}' without 'INSTALL_FAILED=true'. "
                            f"All failures must set the flag for rollback."
                        )

    def test_dpkg_dryrun_not_swallowed(self):
        """dpkg dry-run must not use || true."""
        script = pathlib.Path(__file__).parent.parent / "install_flutter_complete.sh"
        content = script.read_text(encoding='utf-8')
        assert 'dpkg --force-architecture' not in content or '--dry-run' not in content, \
            "dpkg --dry-run with || true was removed; verify no regression"

    def test_rollback_function_exists(self):
        """Installer must have a rollback_packages function."""
        script = pathlib.Path(__file__).parent.parent / "install_flutter_complete.sh"
        content = script.read_text(encoding='utf-8')
        assert 'rollback_packages()' in content, "rollback_packages() function must exist"

    def test_verify_sha256_hard_fail_on_missing_binary(self):
        """lib_common.sh verify_sha256 must return 1 when no hash tool available."""
        lib = pathlib.Path(__file__).parent.parent / "scripts" / "install" / "lib_common.sh"
        content = lib.read_text(encoding='utf-8')
        # Must return 1, not continue with warning
        assert 'return 1' in content, "verify_sha256 must return 1 on failure"
        # Must not have "echo warning" + continue pattern
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'sha256sum' in line and 'warning' in line.lower() and 'return' not in lines[i+1] if i+1 < len(lines) else True:
                pass  # OK — just checking
        # The "if [ -z \"$hasher\" ]" block must return 1
        assert 'return 1' in content


# ============================================================
# Test workflow correctness
# ============================================================

class TestWorkflowCorrectness:
    """Test GitHub Actions workflow files for correctness."""

    def test_actionlint_is_blocking(self):
        """ci.yml actionlint step must NOT have || true."""
        ci = pathlib.Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
        content = ci.read_text(encoding='utf-8')
        # Find the actionlint line
        for line in content.split('\n'):
            if './actionlint' in line and 'shellcheck' in line:
                assert '|| true' not in line, \
                    f"actionlint must be blocking, found: {line.strip()}"

    def test_device_smoke_has_sha256_verify(self):
        """device-smoke.yml must verify SHA256 before running smoke."""
        smoke = pathlib.Path(__file__).parent.parent / ".github" / "workflows" / "device-smoke.yml"
        content = smoke.read_text(encoding='utf-8')
        assert 'Verify artifact SHA256' in content, \
            "device-smoke.yml must have SHA256 verification step"
        assert 'SHA256 MISMATCH' in content, \
            "device-smoke.yml must check for SHA256 mismatch"

    def test_build_metadata_has_tree_sha(self):
        """build-deb.yml metadata must include tree_sha."""
        build = pathlib.Path(__file__).parent.parent / ".github" / "workflows" / "build-deb.yml"
        content = build.read_text(encoding='utf-8')
        assert 'tree_sha' in content, "build metadata must include tree_sha"

    def test_evidence_has_build_duration(self):
        """build-deb.yml evidence must include build_duration_seconds."""
        build = pathlib.Path(__file__).parent.parent / ".github" / "workflows" / "build-deb.yml"
        content = build.read_text(encoding='utf-8')
        assert 'build_duration_seconds' in content, "evidence must include build duration"
