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
        "Version": "3.44.9",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.9")
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
        "Version": "3.44.9",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.9")
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
        "Version": "3.44.9",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.9")
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
        "Version": "3.44.9",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.9")
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
        "Version": "3.44.9",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.9")
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
        "Version": "3.44.9",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.9")
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
        "Version": "3.44.9",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(root=root, arch="arm64", control=control, resource=resource, tag="3.44.9")
    deb_out = tmp_path / "flutter_3.44.9_aarch64.deb"
    pkg.debuild(output=deb_out)
    assert deb_out.exists()


def test_hermetic_package_fixture_version_json_overlay_debuild(tmp_path):
    """Regression test for P2: version_json and canonical_manifest correctly overlay source tree cache files."""
    root = tmp_path / "flutter"
    root.mkdir()
    (root / "bin" / "cache").mkdir(parents=True)
    (root / "bin" / "flutter").write_text("#!/bin/sh\necho flutter")
    (root / "bin" / "cache" / "flutter.version.json").write_text('{"frameworkVersion": "stale_version"}')

    resource = {
        "flutter_tree": {
            "source": str(root),
            "output": "$distro",
        },
        "version_json": {
            "source": '{\n  "frameworkVersion": "$tag",\n  "channel": "stable"\n}',
            "output": "$distro/bin/cache/flutter.version.json",
            "binary": True,
            "replace": True,
            "replace_scope": "$distro/bin/cache",
            "mode": 0o644
        },
        "canonical_manifest": {
            "source": '{\n  "flutter_version": "$tag"\n}',
            "output": [
                "$distro/bin/cache/canonical_manifest.json",
                "$prefix/share/flutter/manifest.json"
            ],
            "binary": True,
            "replace": True,
            "replace_scope": "$prefix",
            "mode": 0o644
        }
    }
    control = {
        "Package": "flutter",
        "Version": "3.44.9",
        "Architecture": "arm64",
        "Maintainer": "test",
        "Description": "test"
    }
    pkg = Package(
        root=root,
        arch="arm64",
        control=control,
        resource=resource,
        tag="3.44.9",
        framework_revision="6b182d2c7585eba26d4edce0f97630effd256c33",
        framework_commit_date="2026-08-05 17:04:07 +0000",
        devtools_version="2.42.0",
        dart_version="3.12.2"
    )
    deb_out = tmp_path / "flutter_3.44.9_aarch64.deb"
    pkg.debuild(output=deb_out)
    assert deb_out.exists()
