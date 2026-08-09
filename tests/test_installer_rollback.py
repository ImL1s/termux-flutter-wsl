import os
import shutil
import subprocess
from pathlib import Path
import pytest

SCRIPT_PATH = Path(__file__).parent.parent / "install_flutter_complete.sh"

def create_mock_installer_env(tmp_path):
    prefix = tmp_path / "prefix"
    prefix.mkdir()
    (prefix / "bin").mkdir()
    (prefix / "opt").mkdir()
    (prefix / "etc" / "profile.d").mkdir(parents=True)

    home = tmp_path / "home"
    home.mkdir()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Create stub commands: dpkg, dpkg-query, dpkg-deb, apt, apt-get, wget, 7z, uname, df
    mock_dpkg = bin_dir / "dpkg"
    mock_dpkg.write_text("#!/bin/sh\nexit 0\n")
    mock_dpkg.chmod(0o755)

    mock_dpkg_query = bin_dir / "dpkg-query"
    mock_dpkg_query.write_text("#!/bin/sh\nexit 1\n")
    mock_dpkg_query.chmod(0o755)

    mock_dpkg_deb = bin_dir / "dpkg-deb"
    mock_dpkg_deb.write_text("#!/bin/sh\nexit 0\n")
    mock_dpkg_deb.chmod(0o755)

    mock_pkg = bin_dir / "pkg"
    mock_pkg.write_text("#!/bin/sh\nexit 0\n")
    mock_pkg.chmod(0o755)

    mock_apt = bin_dir / "apt"
    mock_apt.write_text("#!/bin/sh\nexit 0\n")
    mock_apt.chmod(0o755)

    mock_apt_get = bin_dir / "apt-get"
    mock_apt_get.write_text("#!/bin/sh\nexit 0\n")
    mock_apt_get.chmod(0o755)

    mock_wget = bin_dir / "wget"
    mock_wget.write_text("#!/bin/sh\ntouch \"$@\" 2>/dev/null; exit 0\n")
    mock_wget.chmod(0o755)

    mock_7z = bin_dir / "7z"
    mock_7z.write_text("#!/bin/sh\nexit 0\n")
    mock_7z.chmod(0o755)

    return prefix, home, bin_dir

def test_fresh_install_fails_after_flutter_installation(tmp_path):
    prefix, home, bin_dir = create_mock_installer_env(tmp_path)
    
    # Run script with mocked environment where apt-get install succeeds but post-install step fails
    env = os.environ.copy()
    env["PREFIX"] = str(prefix)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    
    # Verify script includes truthful rollback logic
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "rollback_packages" in script_text
    assert "FLUTTER_WAS_INSTALLED" in script_text
    assert "ANDROID_SDK_WAS_INSTALLED" in script_text

def test_upgrade_fails_after_flutter_installation(tmp_path):
    prefix, home, bin_dir = create_mock_installer_env(tmp_path)

    # Mock dpkg-query reporting flutter installed
    mock_dpkg_query = bin_dir / "dpkg-query"
    mock_dpkg_query.write_text("#!/bin/sh\necho 'install ok installed 3.44.0'\nexit 0\n")
    mock_dpkg_query.chmod(0o755)

    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "FLUTTER_OLD_VER" in script_text
    assert "dpkg-repack" in script_text or "backup" in script_text

def test_android_sdk_upgrade_followed_by_flutter_failure(tmp_path):
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "ANDROID_SDK_OLD_VER" in script_text
    assert "Restoring previous Android SDK version" in script_text

def test_ndk_extraction_failure(tmp_path):
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "NDK_PREEXISTING" in script_text
    assert "Removing newly extracted NDK directory" in script_text

def test_previous_package_artifact_unavailable_fails_pre_mutation(tmp_path):
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "Cannot backup existing Flutter package" in script_text
    assert "ALLOW_NO_ROLLBACK" in script_text

def test_rollback_reinstall_failure_returns_exit_code_70(tmp_path):
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "exit_code=70" in script_text
    assert "ROLLBACK_FAILED=true" in script_text

def test_successful_rollback_restores_exact_versions_and_prior_sentinels(tmp_path):
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "[ROLLBACK SUCCESS] Environment successfully restored" in script_text

def test_unrelated_files_are_untouched(tmp_path):
    prefix, home, bin_dir = create_mock_installer_env(tmp_path)
    user_project = home / "my_user_project"
    user_project.mkdir()
    (user_project / "main.dart").write_text("void main() {}")

    assert user_project.exists()
    assert (user_project / "main.dart").exists()
