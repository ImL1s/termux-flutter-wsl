import os
import sys
import yaml
import pytest
import unittest.mock
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils
import package
from build import Build, windows_to_wsl_path, wsl_to_windows_path, validate_wsl_mount


def test_adv_duplicate_target_collision(tmp_path, monkeypatch):
    root = tmp_path / 'flutter'
    root.mkdir()

    def mock_ar(cmd, **kwargs):
        if cmd[0] == 'ar':
            Path(cmd[2]).write_bytes(b'dummy deb')
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, 'run', mock_ar)

    f1 = root / 'a.txt'
    f2 = root / 'b.txt'
    f1.write_text('a')
    f2.write_text('b')

    control = {
        'Package': 'flutter',
        'Version': '3.44.0',
        'Architecture': 'aarch64',
        'Maintainer': 'Test <test@example.com>',
        'Description': 'Test package',
    }

    resource = {
        'r1': {'source': str(f1), 'output': 'opt/flutter/bin/conflict.txt'},
        'r2': {'source': str(f2), 'output': 'opt/flutter/bin/conflict.txt'},
    }

    pkg = package.Package(root=root, arch='arm64', control=control, resource=resource)
    out_deb = tmp_path / 'test.deb'

    with pytest.raises(ValueError, match="Duplicate target output path collision detected"):
        pkg.debuild(output=out_deb)


def test_adv_broken_symlink_validation(tmp_path, monkeypatch):
    root = tmp_path / 'flutter'
    root.mkdir()

    def mock_ar(cmd, **kwargs):
        if cmd[0] == 'ar':
            Path(cmd[2]).write_bytes(b'dummy deb')
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, 'run', mock_ar)

    control = {
        'Package': 'flutter',
        'Version': '3.44.0',
        'Architecture': 'aarch64',
        'Maintainer': 'Test <test@example.com>',
        'Description': 'Test package',
    }

    broken_link = root / 'broken.lnk'
    try:
        broken_link.symlink_to(root / 'does_not_exist.txt')
    except OSError:
        pytest.skip("Symlink creation not supported")

    resource = {
        'rule': {'source': str(broken_link), 'output': 'opt/flutter/bin/broken.lnk'}
    }

    pkg = package.Package(root=root, arch='arm64', control=control, resource=resource)
    out_deb = tmp_path / 'broken.deb'

    with pytest.raises(ValueError, match="Invalid or broken symlink mapping"):
        pkg.debuild(output=out_deb)


def test_adv_missing_control_headers(tmp_path):
    root = tmp_path / 'flutter'
    root.mkdir()

    base_control = {
        'Package': 'flutter',
        'Version': '3.44.0',
        'Architecture': 'aarch64',
        'Maintainer': 'Test <test@example.com>',
        'Description': 'Test package',
    }

    # Non-dict control
    with pytest.raises(ValueError, match="Debian control header section must be a dictionary"):
        package.Package(root=root, arch='arm64', control="not a dict", resource={})

    # Missing each mandatory header
    for field in ('Package', 'Version', 'Architecture', 'Maintainer', 'Description'):
        ctrl = base_control.copy()
        del ctrl[field]
        with pytest.raises(ValueError, match=f"Missing mandatory Debian control header: '{field}'"):
            package.Package(root=root, arch='arm64', control=ctrl, resource={})

    # Empty string for mandatory header
    for field in ('Package', 'Version', 'Architecture', 'Maintainer', 'Description'):
        ctrl = base_control.copy()
        ctrl[field] = "   "
        with pytest.raises(ValueError, match=f"Mandatory Debian control header '{field}' cannot be empty"):
            package.Package(root=root, arch='arm64', control=ctrl, resource={})


def test_adv_wsl_mount_validation():
    # Valid mount paths - mock os.path.exists for non-WSL Linux CI
    with unittest.mock.patch('os.path.exists', return_value=True):
        validate_wsl_mount('/mnt/c/Users/test')
        validate_wsl_mount('/mnt/d/Project/path')

    # Invalid mount paths
    invalid_paths = [
        '/mnt/invalid_mount/foo',
        '/mnt/',
        '/mnt/123/foo',
        '/mnt/cd/foo',
    ]
    for p in invalid_paths:
        with pytest.raises(ValueError, match="Unsupported WSL mount configuration"):
            validate_wsl_mount(p)


def test_adv_mode_ordering_debug_priority(tmp_path, monkeypatch):
    root = tmp_path / 'flutter'
    root.mkdir()

    # Even if __MODE__ order is changed to put release first...
    monkeypatch.setattr(utils, '__MODE__', ('release', 'debug', 'profile'))

    debug_dir = Path(utils.target_output(root, 'arm64', 'debug'))
    release_dir = Path(utils.target_output(root, 'arm64', 'release'))
    debug_dir.mkdir(parents=True, exist_ok=True)
    release_dir.mkdir(parents=True, exist_ok=True)

    out = utils.Output(root, 'arm64')
    # Output.any MUST still prioritize debug mode!
    assert os.path.normpath(out.any) == os.path.normpath(str(debug_dir.resolve()))


def test_adv_step_skipping_build_all(tmp_path, monkeypatch):
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
    package_yaml.write_text("control:\n  Package: flutter\n  Version: 3.44.0\n  Architecture: aarch64\n  Maintainer: T\n  Description: D\n", encoding='utf-8')

    b = Build(conf=str(conf_path))

    monkeypatch.setattr(b, 'preflight', lambda: True)
    monkeypatch.setattr(b, 'debuild', lambda **kwargs: None)

    steps_called = []
    for step_name in ('clone', 'sync', 'configure', 'build', 'build_dart', 'build_impellerc',
                       'build_const_finder', 'configure_android', 'build_android_gen_snapshot'):
        def make_mock(name):
            return lambda **kwargs: steps_called.append(name)
        monkeypatch.setattr(b, step_name, make_mock(step_name))

    def mock_sysroot(**kwargs): steps_called.append('sysroot')
    monkeypatch.setattr(b, 'sysroot', mock_sysroot)

    # 1. Run without any pre-existing artifacts: steps should be called
    b.build_all(arch='arm64', force=False)
    assert 'clone' in steps_called
    assert 'sync' in steps_called
    assert 'sysroot' in steps_called

    # 2. Populate output artifacts
    (flutter_dir / 'bin').mkdir(exist_ok=True)
    (flutter_dir / 'bin' / 'flutter').write_text('dummy')
    (flutter_dir / '.gclient').write_text('dummy')
    dart_ver = flutter_dir / 'engine' / 'src' / 'third_party' / 'dart' / 'tools' / 'sdks' / 'dart-sdk'
    dart_ver.mkdir(parents=True, exist_ok=True)
    (dart_ver / 'version').write_text('3.12.1')
    (sysroot_dir / 'usr').mkdir(exist_ok=True)

    out_debug = Path(utils.target_output(str(flutter_dir), 'arm64', 'debug'))
    out_debug.mkdir(parents=True, exist_ok=True)
    (out_debug / 'libflutter_linux_gtk.so').write_text('dummy')
    (out_debug / 'dart-sdk' / 'bin').mkdir(parents=True, exist_ok=True)
    (out_debug / 'dart-sdk' / 'bin' / 'dart').write_text('dummy')
    (out_debug / 'impellerc').write_text('dummy')

    out_release = Path(utils.target_output(str(flutter_dir), 'arm64', 'release'))
    out_release.mkdir(parents=True, exist_ok=True)
    (out_release / 'libflutter_linux_gtk.so').write_text('dummy')
    (out_release / 'gen_snapshot').write_text('dummy')

    out_profile = Path(utils.target_output(str(flutter_dir), 'arm64', 'profile'))
    out_profile.mkdir(parents=True, exist_ok=True)
    (out_profile / 'libflutter_linux_gtk.so').write_text('dummy')
    (out_profile / 'gen_snapshot').write_text('dummy')

    android_rel = flutter_dir / 'engine' / 'src' / 'out' / 'android_release_arm64' / 'clang_arm64'
    android_rel.mkdir(parents=True, exist_ok=True)
    (android_rel / 'gen_snapshot').write_text('dummy')

    android_prof = flutter_dir / 'engine' / 'src' / 'out' / 'android_profile_arm64' / 'clang_arm64'
    android_prof.mkdir(parents=True, exist_ok=True)
    (android_prof / 'gen_snapshot').write_text('dummy')

    monkeypatch.setattr(b._sysroot, 'verify', lambda arch: True)

    steps_called.clear()
    b.build_all(arch='arm64', force=False)
    # clone is invoked to validate workspace status; sync and sysroot are skipped when outputs/lock are valid
    assert 'clone' in steps_called
    assert 'sync' not in steps_called
    assert 'sysroot' not in steps_called

    # 3. Force rebuild
    steps_called.clear()
    b.build_all(arch='arm64', force=True)
    assert 'clone' in steps_called
    assert 'sync' in steps_called
    assert 'sysroot' in steps_called


def test_adv_package_yaml_no_git_true():
    yaml_path = Path(__file__).resolve().parent.parent / 'package.yaml'
    assert yaml_path.exists()
    content = yaml_path.read_text(encoding='utf-8')
    data = yaml.safe_load(content)

    git_true_found = False
    for res_name, res_config in data.get('resource', {}).items():
        if isinstance(res_config, dict) and res_config.get('git') is True:
            git_true_found = True
            break

    # R6 requirement: package.yaml must NOT use git: true
    assert not git_true_found, "package.yaml contains 'git: true' under resource definitions (R6 violation)"
