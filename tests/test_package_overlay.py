import subprocess
from pathlib import Path
import pytest
from package import Package

@pytest.fixture(autouse=True)
def mock_ar_binary(monkeypatch):
    """Mock subprocess.run for 'ar' binary on systems without native 'ar' (e.g. Windows)."""
    orig_run = subprocess.run
    def mock_subprocess_run(cmd, **kwargs):
        if isinstance(cmd, (list, tuple)) and len(cmd) > 2 and cmd[0] == 'ar':
            deb_target = Path(cmd[2])
            deb_target.write_bytes(b'dummy deb archive content')
            return subprocess.CompletedProcess(cmd, 0)
        return orig_run(cmd, **kwargs)
    monkeypatch.setattr(subprocess, 'run', mock_subprocess_run)

def test_distinct_outputs_succeed(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    (root / "file1.txt").write_text("hello")
    (root / "file2.txt").write_text("world")
    
    resource = {
        "r1": {
            "source": str(root / "file1.txt"),
            "output": "$prefix/file1.txt",
        },
        "r2": {
            "source": str(root / "file2.txt"),
            "output": "$prefix/file2.txt",
        }
    }
    control = {
        "Package": "flutter",
        "Version": "3.44.2",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.2")
    deb_out = tmp_path / "out.deb"
    pkg.debuild(output=deb_out)
    assert deb_out.exists()

def test_undeclared_duplicate_targets_fail(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    (root / "f1.txt").write_text("v1")
    (root / "f2.txt").write_text("v2")

    resource = {
        "r1": {
            "source": str(root / "f1.txt"),
            "output": "$prefix/same.txt",
        },
        "r2": {
            "source": str(root / "f2.txt"),
            "output": "$prefix/same.txt",
        }
    }
    control = {
        "Package": "flutter",
        "Version": "3.44.2",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.2")
    deb_out = tmp_path / "out.deb"
    with pytest.raises(ValueError, match="Duplicate target output path collision detected"):
        pkg.debuild(output=deb_out)

def test_declared_dart_sdk_binary_overlay_succeeds(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    sdk_dir = root / "dart-sdk" / "bin"
    sdk_dir.mkdir(parents=True)
    (sdk_dir / "dart").write_text("original_dart")
    
    custom_dart = root / "custom_dart"
    custom_dart.write_text("overlay_dart")

    resource = {
        "dart_sdk": {
            "source": str(root / "dart-sdk"),
            "output": "$distro/bin/cache/dart-sdk",
        },
        "dart_bin": {
            "source": str(custom_dart),
            "output": "$distro/bin/cache/dart-sdk/bin/dart",
            "replace": True,
            "replace_scope": "$distro/bin/cache/dart-sdk",
            "mode": 0o755
        }
    }
    control = {
        "Package": "flutter",
        "Version": "3.44.2",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.2")
    deb_out = tmp_path / "out.deb"
    pkg.debuild(output=deb_out)
    assert deb_out.exists()

def test_declared_overlay_produces_single_final_target(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    sdk_dir = root / "dart-sdk" / "bin"
    sdk_dir.mkdir(parents=True)
    (sdk_dir / "dart").write_text("original_dart")
    
    custom_dart = root / "custom_dart"
    custom_dart.write_text("overlay_dart")

    resource = {
        "dart_sdk": {
            "source": str(root / "dart-sdk"),
            "output": "$distro/bin/cache/dart-sdk",
        },
        "dart_bin": {
            "source": str(custom_dart),
            "output": "$distro/bin/cache/dart-sdk/bin/dart",
            "replace": True,
            "replace_scope": "$distro/bin/cache/dart-sdk",
            "mode": 0o755
        }
    }
    control = {
        "Package": "flutter",
        "Version": "3.44.2",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.2")
    deb_out = tmp_path / "out.deb"
    pkg.debuild(output=deb_out)

    inv_file = deb_out.with_name(deb_out.name + ".inventory")
    assert inv_file.exists()
    lines = inv_file.read_text().splitlines()
    dart_lines = [l for l in lines if "bin/cache/dart-sdk/bin/dart" in l.replace("\\", "/")]
    assert len(dart_lines) == 1, f"Expected 1 inventory line for dart, got: {dart_lines}"

def test_inventory_contains_replacement_source_and_hash(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    sdk_dir = root / "dart-sdk" / "bin"
    sdk_dir.mkdir(parents=True)
    (sdk_dir / "dart").write_text("original_dart")
    
    custom_dart = root / "custom_dart"
    custom_dart.write_text("overlay_dart_special_content")

    resource = {
        "dart_sdk": {
            "source": str(root / "dart-sdk"),
            "output": "$distro/bin/cache/dart-sdk",
        },
        "dart_bin": {
            "source": str(custom_dart),
            "output": "$distro/bin/cache/dart-sdk/bin/dart",
            "replace": True,
            "replace_scope": "$distro/bin/cache/dart-sdk",
            "mode": 0o755
        }
    }
    control = {
        "Package": "flutter",
        "Version": "3.44.2",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.2")
    deb_out = tmp_path / "out.deb"
    pkg.debuild(output=deb_out)

    import hashlib
    expected_hash = hashlib.sha256(b"overlay_dart_special_content").hexdigest()

    inv_file = deb_out.with_name(deb_out.name + ".inventory")
    content = inv_file.read_text()
    assert expected_hash in content

def test_overlay_outside_scope_fails(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    (root / "f1.txt").write_text("orig")
    (root / "f2.txt").write_text("custom")

    resource = {
        "r1": {
            "source": str(root / "f1.txt"),
            "output": "$prefix/other_dir/target.txt",
        },
        "r2": {
            "source": str(root / "f2.txt"),
            "output": "$prefix/other_dir/target.txt",
            "replace": True,
            "replace_scope": "$distro/bin/cache/dart-sdk"
        }
    }
    control = {
        "Package": "flutter",
        "Version": "3.44.2",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.2")
    deb_out = tmp_path / "out.deb"
    with pytest.raises(ValueError, match="Overlay scope violation"):
        pkg.debuild(output=deb_out)

def test_hermetic_package_fixture_dart_sdk_overlay_debuild(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    (root / "bin").mkdir()
    (root / "bin" / "flutter").write_text("#!/bin/sh\necho flutter")

    sdk_dir = root / "dart-sdk" / "bin"
    sdk_dir.mkdir(parents=True)
    (sdk_dir / "dart").write_text("stock_dart_binary")
    (sdk_dir / "dartvm").write_text("stock_dartvm_binary")

    custom_dart = root / "debug_dart"
    custom_dart.write_text("custom_termux_dart_binary")

    resource = {
        "dart_sdk": {
            "source": str(root / "dart-sdk"),
            "output": "$distro/bin/cache/dart-sdk",
        },
        "dart_bin": {
            "source": str(custom_dart),
            "output": "$distro/bin/cache/dart-sdk/bin/dart",
            "replace": True,
            "replace_scope": "$distro/bin/cache/dart-sdk",
            "mode": 0o755
        },
        "dartvm_bin": {
            "source": str(custom_dart),
            "output": "$distro/bin/cache/dart-sdk/bin/dartvm",
            "replace": True,
            "replace_scope": "$distro/bin/cache/dart-sdk",
            "mode": 0o755
        }
    }
    control = {
        "Package": "flutter",
        "Version": "3.44.2",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.2")
    deb_out = tmp_path / "flutter_3.44.2_aarch64.deb"
    pkg.debuild(output=deb_out)
    assert deb_out.exists()
