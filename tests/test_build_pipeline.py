import os
import sys
import json
import pytest
import unittest.mock
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils
from build import Build, windows_to_wsl_path, wsl_to_windows_path, validate_wsl_mount


def test_utils_mode_ordering():
    assert utils.__MODE__ == ('debug', 'release', 'profile')
    assert utils.__MODE__[0] == 'debug'


def test_output_any_debug_priority(tmp_path):
    root = tmp_path / 'flutter'
    root.mkdir()
    
    # 1. No output dirs exist yet -> default to debug
    out = utils.Output(root, 'arm64')
    expected_debug = str((root / 'engine' / 'src' / 'out' / 'linux_debug_arm64').resolve())
    assert os.path.normpath(out.any) == os.path.normpath(expected_debug)

    # 2. Both debug and release dirs exist -> select debug and issue warning
    debug_dir = Path(utils.target_output(root, 'arm64', 'debug'))
    release_dir = Path(utils.target_output(root, 'arm64', 'release'))
    debug_dir.mkdir(parents=True, exist_ok=True)
    release_dir.mkdir(parents=True, exist_ok=True)

    out = utils.Output(root, 'arm64')
    assert os.path.normpath(out.any) == os.path.normpath(str(debug_dir.resolve()))

    # 3. Only release dir exists -> fallback to release
    import shutil
    shutil.rmtree(debug_dir)
    out = utils.Output(root, 'arm64')
    assert os.path.normpath(out.any) == os.path.normpath(str(release_dir.resolve()))


def test_wsl_path_conversions():
    # Windows to WSL
    assert windows_to_wsl_path('C:\\Users\\test') == '/mnt/c/Users/test'
    assert windows_to_wsl_path('D:/OtherProject/mine') == '/mnt/d/OtherProject/mine'
    assert windows_to_wsl_path('/mnt/c/Users/test') == '/mnt/c/Users/test'

    # WSL to Windows
    assert wsl_to_windows_path('/mnt/c/Users/test') == 'C:\\Users\\test'
    assert wsl_to_windows_path('/mnt/d/OtherProject') == 'D:\\OtherProject'
    assert wsl_to_windows_path('C:\\Users\\test') == 'C:\\Users\\test'


def test_wsl_mount_validation():
    # Valid mount format - mock os.path.exists for non-WSL Linux CI
    with unittest.mock.patch('os.path.exists', return_value=True):
        validate_wsl_mount('/mnt/c/Users/test')
        validate_wsl_mount('/mnt/d/project')

    # Invalid mount format should fail
    with pytest.raises(ValueError, match="Unsupported WSL mount configuration"):
        validate_wsl_mount('/mnt/invalid_mount/test')

    with pytest.raises(ValueError, match="Unsupported WSL mount configuration"):
        validate_wsl_mount('/mnt/')


def test_build_all_deduplication_and_skipping(tmp_path, monkeypatch):
    # Setup mock Build environment
    conf_path = tmp_path / 'build.toml'
    flutter_dir = tmp_path / 'flutter'
    sysroot_dir = tmp_path / 'sysroot'
    package_yaml = tmp_path / 'package.yaml'
    
    flutter_dir.mkdir()
    sysroot_dir.mkdir()

    flutter_dir_str = str(flutter_dir).replace('\\', '/')
    sysroot_dir_str = str(sysroot_dir).replace('\\', '/')
    package_yaml_str = str(package_yaml).replace('\\', '/')

    conf_content = f"""
    [flutter]
    tag = "3.44.0"
    path = "{flutter_dir_str}"

    [sysroot]
    path = "{sysroot_dir_str}"

    [package]
    conf = "{package_yaml_str}"
    """
    conf_path.write_text(conf_content, encoding='utf-8')
    package_yaml.write_text("""
    control:
      Package: flutter
      Version: 3.44.0
      Architecture: aarch64
      Maintainer: Test <test@example.com>
      Description: Test package
    resource:
      flutter:
        source: $root
        output: $distro
    """, encoding='utf-8')

    b = Build(conf=str(conf_path))
    
    # Mock preflight, debuild, configure, build so we isolate step skipping logic
    monkeypatch.setattr(b, 'preflight', lambda: True)
    monkeypatch.setattr(b, 'debuild', lambda **kwargs: None)
    monkeypatch.setattr(b, 'configure', lambda **kwargs: None)
    monkeypatch.setattr(b, 'build', lambda **kwargs: None)
    monkeypatch.setattr(b, 'build_dart', lambda **kwargs: None)
    monkeypatch.setattr(b, 'build_impellerc', lambda **kwargs: None)
    monkeypatch.setattr(b, 'build_const_finder', lambda **kwargs: None)
    monkeypatch.setattr(b, 'configure_android', lambda **kwargs: None)
    monkeypatch.setattr(b, 'build_android_gen_snapshot', lambda **kwargs: None)
    
    executed_steps = []
    def mock_clone(**kwargs): executed_steps.append('clone')
    def mock_sync(**kwargs): executed_steps.append('sync')
    def mock_sysroot(**kwargs): executed_steps.append('sysroot')

    monkeypatch.setattr(b, 'clone', mock_clone)
    monkeypatch.setattr(b, 'sync', mock_sync)
    monkeypatch.setattr(b, 'sysroot', mock_sysroot)

    # 1. First run without outputs: steps should execute
    b.build_all(arch='arm64', force=False)
    assert 'clone' in executed_steps
    assert 'sync' in executed_steps
    assert 'sysroot' in executed_steps

    # 2. Create mock output artifacts for clone, sync, sysroot
    (flutter_dir / 'bin').mkdir(exist_ok=True)
    (flutter_dir / 'bin' / 'flutter').write_text('dummy flutter')
    (flutter_dir / '.gclient').write_text('dummy gclient')
    (flutter_dir / '.gclient_sync.receipt.json').write_text(json.dumps({'flutter_head': 'dummy', 'gclient_sha256': 'dummy', 'completed': True}))
    dart_ver = flutter_dir / 'engine' / 'src' / 'third_party' / 'dart' / 'tools' / 'sdks' / 'dart-sdk'
    dart_ver.mkdir(parents=True, exist_ok=True)
    (dart_ver / 'version').write_text('3.12.1')
    (sysroot_dir / 'usr').mkdir(exist_ok=True)
    monkeypatch.setattr(b._sysroot, 'verify', lambda arch: True)
    monkeypatch.setattr(b, 'is_sync_complete', lambda: True)

    executed_steps.clear()
    b.build_all(arch='arm64', force=False)
    # clone is invoked to run workspace validation (and skips internally), sync & sysroot skip step execution
    assert 'clone' in executed_steps
    assert 'sync' not in executed_steps
    assert 'sysroot' not in executed_steps

    # 3. With force=True: steps execute even if outputs exist
    executed_steps.clear()
    b.build_all(arch='arm64', force=True)
    assert 'clone' in executed_steps
    assert 'sync' in executed_steps
    assert 'sysroot' in executed_steps


def test_build_sysroot_applies_header_fixes(tmp_path, monkeypatch):
    conf_path = tmp_path / 'build.toml'
    flutter_dir = tmp_path / 'flutter'
    sysroot_dir = tmp_path / 'sysroot'
    package_yaml = tmp_path / 'package.yaml'

    flutter_dir.mkdir()
    sysroot_dir.mkdir()

    flutter_str = str(flutter_dir).replace('\\', '/')
    sysroot_str = str(sysroot_dir).replace('\\', '/')
    package_str = str(package_yaml).replace('\\', '/')

    conf_content = f"""
    [flutter]
    tag = "3.44.0"
    path = "{flutter_str}"

    [sysroot]
    path = "{sysroot_str}"

    [package]
    conf = "{package_str}"
    """
    conf_path.write_text(conf_content, encoding='utf-8')
    package_yaml.write_text("control:\n  Package: flutter\n  Version: 3.44.0\n", encoding='utf-8')

    b = Build(conf=str(conf_path))
    mock_sysroot_obj = MagicMock()
    mock_sysroot_obj.path = sysroot_dir
    monkeypatch.setattr(b, '_sysroot', mock_sysroot_obj)

    # Setup dummy headers for Fix #3 (c++) and Fix #4 (glib-typeof.h)
    cxx_dir = sysroot_dir / 'usr' / 'include' / 'c++'
    cxx_dir.mkdir(parents=True)
    (cxx_dir / 'v1').mkdir()

    glib_dir = sysroot_dir / 'usr' / 'include' / 'glib-2.0' / 'glib'
    glib_dir.mkdir(parents=True)
    glib_typeof = glib_dir / 'glib-typeof.h'
    glib_typeof.write_text('#include <type_traits>\n', encoding='utf-8')

    b.sysroot(arch='arm64')

    assert not cxx_dir.exists()
    assert (sysroot_dir / 'usr' / 'include' / 'c++.bak').is_dir()
    assert 'extern "C++"' in glib_typeof.read_text(encoding='utf-8')


def test_clone_tag_mismatch_defines_current_tag(tmp_path, monkeypatch):
    conf_path = tmp_path / 'build.toml'
    flutter_dir = tmp_path / 'flutter'
    package_yaml = tmp_path / 'package.yaml'
    flutter_dir.mkdir()
    package_yaml.write_text("control:\n  Package: flutter\n  Version: 3.44.0\n", encoding='utf-8')

    flutter_str = str(flutter_dir).replace('\\', '/')
    package_str = str(package_yaml).replace('\\', '/')

    conf_content = f"""
    [flutter]
    tag = "3.44.0"
    path = "{flutter_str}"
    [package]
    conf = "{package_str}"
    """
    conf_path.write_text(conf_content, encoding='utf-8')
    b = Build(conf=str(conf_path))

    status_calls = [
        {'exists': True, 'dirty': False, 'tag': '3.43.0', 'remote': b.repo, 'head': 'abc', 'peeled_sha': 'def'},
        {'exists': True, 'dirty': False, 'tag': '3.44.0', 'remote': b.repo, 'head': '123', 'peeled_sha': '123'},
    ]
    monkeypatch.setattr(b, 'workspace_status', lambda path: status_calls.pop(0) if status_calls else {'exists': True, 'dirty': False, 'tag': '3.44.0', 'remote': b.repo, 'head': '123', 'peeled_sha': '123'})

    mock_repo = MagicMock()
    mock_repo.git.fetch = MagicMock()
    mock_repo.git.checkout = MagicMock()

    import git
    monkeypatch.setattr(git, 'Repo', lambda path: mock_repo)
    monkeypatch.setattr(utils, 'flutter_tag', lambda path: '3.44.0')

    # Calling clone should successfully log current_tag without raising NameError
    b.clone(tag='3.44.0')
    mock_repo.git.checkout.assert_called_once_with('3.44.0')


def test_clone_dirty_checkout_fails_closed(tmp_path, monkeypatch):
    conf_path = tmp_path / 'build.toml'
    flutter_dir = tmp_path / 'flutter'
    package_yaml = tmp_path / 'package.yaml'
    flutter_dir.mkdir()
    package_yaml.write_text("control:\n  Package: flutter\n  Version: 3.44.0\n", encoding='utf-8')

    flutter_str = str(flutter_dir).replace('\\', '/')
    package_str = str(package_yaml).replace('\\', '/')

    conf_content = f"""
    [flutter]
    tag = "3.44.0"
    path = "{flutter_str}"
    [package]
    conf = "{package_str}"
    """
    conf_path.write_text(conf_content, encoding='utf-8')
    b = Build(conf=str(conf_path))

    monkeypatch.setattr(b, 'workspace_status', lambda path: {'exists': True, 'dirty': True, 'tag': '3.44.0'})
    with pytest.raises(RuntimeError, match="Dirty checkout"):
        b.clone(tag='3.44.0', force=False)


def test_build_all_sole_owner_avoids_dirty_checkout_sequence(tmp_path, monkeypatch):
    """Behavioral test: proving build_all running sole ownership pipeline clones before patching and never encounters Dirty checkout error."""
    conf_path = tmp_path / 'build.toml'
    flutter_dir = tmp_path / 'flutter'
    package_yaml = tmp_path / 'package.yaml'
    flutter_dir.mkdir()
    (flutter_dir / 'bin').mkdir()
    (flutter_dir / 'bin' / 'flutter').touch()
    package_yaml.write_text("control:\n  Package: flutter\n  Version: 3.44.0\n", encoding='utf-8')

    flutter_str = str(flutter_dir).replace('\\', '/')
    package_str = str(package_yaml).replace('\\', '/')

    conf_content = f"""
    [flutter]
    tag = "3.44.0"
    path = "{flutter_str}"
    [package]
    conf = "{package_str}"
    """
    conf_path.write_text(conf_content, encoding='utf-8')
    b = Build(conf=str(conf_path))
    b.patches = {'engine': {}, 'dart': {}, 'skia': {}}

    sequence_log = []

    monkeypatch.setattr(b, 'preflight', lambda: True)

    def mock_clone(**kwargs):
        sequence_log.append('clone')

    def mock_sync(**kwargs):
        sequence_log.append('sync')

    def mock_patch(**kwargs):
        sequence_log.append('patch')

    def mock_sysroot(**kwargs):
        sequence_log.append('sysroot')

    def mock_build(*args, **kwargs):
        sequence_log.append('build')

    def mock_debuild(*args, **kwargs):
        sequence_log.append('debuild')

    monkeypatch.setattr(b, 'clone', mock_clone)
    monkeypatch.setattr(b, 'sync', mock_sync)
    setattr(b, 'patch_engine', mock_patch)
    setattr(b, 'patch_dart', mock_patch)
    setattr(b, 'patch_skia', mock_patch)
    setattr(b, 'patch_flutter_sdk', mock_patch)
    monkeypatch.setattr(b, 'sysroot', mock_sysroot)
    monkeypatch.setattr(b, 'configure', mock_build)
    monkeypatch.setattr(b, 'build', mock_build)
    monkeypatch.setattr(b, 'build_dart', mock_build)
    monkeypatch.setattr(b, 'build_impellerc', mock_build)
    monkeypatch.setattr(b, 'build_const_finder', mock_build)
    monkeypatch.setattr(b, 'configure_android', mock_build)
    monkeypatch.setattr(b, 'build_android_gen_snapshot', mock_build)
    monkeypatch.setattr(b, 'debuild', mock_debuild)
    monkeypatch.setattr(b, 'is_sync_complete', lambda: False)

    b.build_all(arch='arm64')

    first_clone_idx = sequence_log.index('clone')
    first_patch_idx = sequence_log.index('patch')
    assert first_clone_idx < first_patch_idx, "clone must execute before patch"
    assert sequence_log.count('clone') == 1, "clone must execute exactly once during build_all"
    assert 'debuild' in sequence_log, "debuild must complete single-owner pipeline"
