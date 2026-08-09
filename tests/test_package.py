import os
import sys
import subprocess
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import package


def test_safe_eval():
    globals_dict = {
        'tag': '3.44.0',
        'arch': 'arm64',
        'distro': 'data/data/com.termux/files/usr/opt/flutter',
    }
    defines_dict = {
        'cache': "f'{distro}/bin/cache'",
    }
    
    assert package.safe_eval("f'{tag}'", globals_dict) == '3.44.0'
    assert package.safe_eval("'static_str'", globals_dict) == 'static_str'
    assert package.safe_eval('"double_quote"', globals_dict) == 'double_quote'
    assert package.safe_eval("f'{cache}/dart-sdk'", globals_dict, defines_dict) == 'data/data/com.termux/files/usr/opt/flutter/bin/cache/dart-sdk'


def test_package_control_header_validation(tmp_path):
    root = tmp_path / 'flutter'
    root.mkdir()

    valid_control = {
        'Package': 'flutter',
        'Version': '3.44.0',
        'Architecture': 'aarch64',
        'Maintainer': 'Termux Flutter WSL <termux-flutter-wsl@github.com>',
        'Description': 'Flutter SDK for Termux',
    }

    # Valid headers should initialize without error
    pkg = package.Package(root=root, arch='arm64', control=valid_control, resource={})
    assert pkg.control['Package'] == 'flutter'

    # Missing mandatory header (e.g. Description) should raise ValueError
    invalid_control = valid_control.copy()
    del invalid_control['Description']
    with pytest.raises(ValueError, match="Missing mandatory Debian control header: 'Description'"):
        package.Package(root=root, arch='arm64', control=invalid_control, resource={})

    # Empty mandatory header should raise ValueError
    empty_control = valid_control.copy()
    empty_control['Version'] = ''
    with pytest.raises(ValueError, match="Mandatory Debian control header 'Version' cannot be empty"):
        package.Package(root=root, arch='arm64', control=empty_control, resource={})


def test_package_duplicate_target_collision_detection(tmp_path, monkeypatch):
    root = tmp_path / 'flutter'
    root.mkdir()

    # Mock subprocess.run for 'ar' binary in test environment
    def mock_subprocess_run(cmd, **kwargs):
        if cmd[0] == 'ar':
            deb_target = Path(cmd[2])
            deb_target.write_bytes(b'dummy deb')
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, 'run', mock_subprocess_run)

    # Create dummy files
    src1 = root / 'file1.txt'
    src2 = root / 'file2.txt'
    src1.write_text('content 1')
    src2.write_text('content 2')

    control = {
        'Package': 'flutter',
        'Version': '3.44.0',
        'Architecture': 'aarch64',
        'Maintainer': 'Test <test@example.com>',
        'Description': 'Test package',
    }

    # Two distinct resource mapping rules mapping to the exact same target path in .deb
    duplicate_resource = {
        'rule1': {
            'source': str(src1),
            'output': 'opt/flutter/bin/common_file.txt',
        },
        'rule2': {
            'source': str(src2),
            'output': 'opt/flutter/bin/common_file.txt',
        }
    }

    pkg = package.Package(root=root, arch='arm64', control=control, resource=duplicate_resource)
    deb_output = tmp_path / 'test.deb'

    with pytest.raises(ValueError, match="Duplicate target output path collision detected"):
        pkg.debuild(output=deb_output)


def test_package_symlink_validation(tmp_path, monkeypatch):
    root = tmp_path / 'flutter'
    root.mkdir()

    control = {
        'Package': 'flutter',
        'Version': '3.44.0',
        'Architecture': 'aarch64',
        'Maintainer': 'Test <test@example.com>',
        'Description': 'Test package',
    }

    # Mock subprocess.run for 'ar' binary in test environment
    def mock_subprocess_run(cmd, **kwargs):
        if cmd[0] == 'ar':
            deb_target = Path(cmd[2])
            deb_target.write_bytes(b'dummy deb')
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, 'run', mock_subprocess_run)

    # Create a valid target file and symlink
    target_file = root / 'target.txt'
    target_file.write_text('real content')
    valid_link = root / 'valid_link.txt'

    if hasattr(os, 'symlink'):
        try:
            valid_link.symlink_to(target_file)
        except OSError:
            pytest.skip("Symlink creation not supported in current environment")

        resource = {
            'rule_symlink': {
                'source': str(valid_link),
                'output': 'opt/flutter/bin/valid_link.txt',
            }
        }
        pkg = package.Package(root=root, arch='arm64', control=control, resource=resource)
        deb_output = tmp_path / 'valid_symlink.deb'
        # Valid symlink should pass packaging without exception
        pkg.debuild(output=deb_output)
        assert deb_output.exists()

        # Create a broken symlink (points to non-existent file)
        broken_link = root / 'broken_link.txt'
        broken_link.symlink_to(root / 'non_existent_file.txt')

        broken_resource = {
            'rule_broken': {
                'source': str(broken_link),
                'output': 'opt/flutter/bin/broken_link.txt',
            }
        }
        pkg_broken = package.Package(root=root, arch='arm64', control=control, resource=broken_resource)
        deb_output_broken = tmp_path / 'broken_symlink.deb'
        with pytest.raises(ValueError, match="Invalid or broken symlink mapping"):
            pkg_broken.debuild(output=deb_output_broken)


def test_package_no_git_traversal(tmp_path):
    root = tmp_path / 'flutter'
    root.mkdir()
    (root / 'file.txt').write_text('data')

    # Create a mock .git directory with objects
    git_dir = root / '.git'
    git_dir.mkdir()
    (git_dir / 'config').write_text('[core]')

    control = {
        'Package': 'flutter',
        'Version': '3.44.0',
        'Architecture': 'aarch64',
        'Maintainer': 'Test <test@example.com>',
        'Description': 'Test package',
    }
    resource = {
        'flutter': {
            'source': str(root),
            'output': 'opt/flutter',
        }
    }

    pkg = package.Package(root=root, arch='arm64', control=control, resource=resource)
    outputs = [str(item['out']) for item in pkg.gen_resource('flutter')]
    
    # Verify .git directory files are NOT traversed or emitted into resources
    assert not any('.git' in path for path in outputs)


def test_package_real_archive_exclusion_fixture(tmp_path):
    """Build a real package archive fixture and verify giant build trees (.git, engine/src, out) are excluded."""
    root = tmp_path / 'flutter'
    root.mkdir()

    # Normal SDK files
    (root / 'bin').mkdir()
    (root / 'bin' / 'flutter').write_text('#!/bin/sh\necho flutter')
    (root / 'packages' / 'flutter' / 'lib').mkdir(parents=True)
    (root / 'packages' / 'flutter' / 'lib' / 'flutter.dart').write_text('// flutter lib')

    # Excluded giant build trees
    (root / 'engine' / 'src' / 'out' / 'linux_debug_arm64').mkdir(parents=True)
    (root / 'engine' / 'src' / 'BUILD.gn').write_text('# engine build')
    (root / 'engine' / 'src' / 'out' / 'linux_debug_arm64' / 'libflutter.so').write_bytes(b'so binary')
    (root / '.git').mkdir()
    (root / '.git' / 'config').write_text('[core]')

    # Intended explicit engine artifact
    (root / 'custom_bin').mkdir()
    (root / 'custom_bin' / 'dart').write_text('custom dart binary')

    control = {
        'Package': 'flutter',
        'Version': '3.44.0',
        'Architecture': 'aarch64',
        'Maintainer': 'Test <test@example.com>',
        'Description': 'Test package',
    }

    resource = {
        'flutter': {
            'source': str(root),
            'output': 'opt/flutter',
        },
        'dart_bin': {
            'source': str(root / 'custom_bin' / 'dart'),
            'output': 'opt/flutter/bin/cache/dart-sdk/bin/dart',
            'replace': True,
            'replace_scope': 'opt/flutter'
        }
    }

    pkg = package.Package(root=root, arch='arm64', control=control, resource=resource)
    outputs = [str(item['out']) for item in pkg.gen_resource('flutter')]

    # Assert outputs do NOT contain any excluded path components
    for path in outputs:
        assert '.git' not in path
        assert 'engine' not in path
        assert 'out' not in path

    # Debuild real tar archive (testing tarfile generation directly)
    tmp_data_tar = tmp_path / 'data.tar.xz'
    package.tar(tmp_data_tar, pkg.gen_resource(None))

    import tarfile
    with tarfile.open(tmp_data_tar, 'r:xz') as tar_ar:
        members = tar_ar.getnames()

    assert any('bin/flutter' in m for m in members)
    assert any('flutter.dart' in m for m in members)
    assert any('cache/dart-sdk/bin/dart' in m for m in members)

    assert not any('.git' in m for m in members)
    assert not any('engine/src' in m for m in members)
    assert not any('BUILD.gn' in m for m in members)
    assert not any('libflutter.so' in m for m in members)
