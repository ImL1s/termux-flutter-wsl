import os
import time
from pathlib import Path
import pytest
from build import Build

def test_const_finder_snapshot_in_debug_outputs():
    """Verify build_all completeness predicate includes const_finder.dart.snapshot."""
    build_script = Path(__file__).parent.parent / "build.py"
    text = build_script.read_text(encoding="utf-8")
    assert "gen/const_finder.dart.snapshot" in text

def test_all_required_debug_outputs_present_skips(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    out_debug = root / "engine" / "src" / "out" / "linux_debug_arm64"
    out_debug.mkdir(parents=True)
    
    (out_debug / "libflutter_linux_gtk.so").touch()
    (out_debug / "dart-sdk" / "bin").mkdir(parents=True)
    (out_debug / "dart-sdk" / "bin" / "dart").touch()
    (out_debug / "impellerc").touch()
    (out_debug / "gen").mkdir(parents=True)
    (out_debug / "gen" / "const_finder.dart.snapshot").touch()

    debug_outputs = [
        out_debug / "libflutter_linux_gtk.so",
        out_debug / "dart-sdk" / "bin" / "dart",
        out_debug / "impellerc",
        out_debug / "gen" / "const_finder.dart.snapshot",
    ]
    assert all(p.exists() for p in debug_outputs)

def test_const_finder_missing_rebuilds_debug_tools(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    out_debug = root / "engine" / "src" / "out" / "linux_debug_arm64"
    out_debug.mkdir(parents=True)
    
    (out_debug / "libflutter_linux_gtk.so").touch()
    (out_debug / "dart-sdk" / "bin").mkdir(parents=True)
    (out_debug / "dart-sdk" / "bin" / "dart").touch()
    (out_debug / "impellerc").touch()
    # const_finder missing!

    debug_outputs = [
        out_debug / "libflutter_linux_gtk.so",
        out_debug / "dart-sdk" / "bin" / "dart",
        out_debug / "impellerc",
        out_debug / "gen" / "const_finder.dart.snapshot",
    ]
    assert not all(p.exists() for p in debug_outputs)

def test_deb_exists_and_one_artifact_missing_runs_rebuild_and_debuild(tmp_path):
    deb_file = tmp_path / "flutter_3.44.0_aarch64.deb"
    deb_file.touch()

    artifact = tmp_path / "some_artifact"
    # Artifact created AFTER deb_file
    time.sleep(0.05)
    artifact.touch()

    assert artifact.stat().st_mtime > deb_file.stat().st_mtime

def test_artifact_newer_than_deb_runs_debuild(tmp_path):
    deb_file = tmp_path / "test.deb"
    deb_file.write_text("old deb")
    
    time.sleep(0.05)
    engine_output = tmp_path / "gen_snapshot"
    engine_output.write_text("new snapshot")

    deb_mtime = deb_file.stat().st_mtime
    assert engine_output.stat().st_mtime > deb_mtime

def test_inputs_older_skips_debuild(tmp_path):
    engine_output = tmp_path / "gen_snapshot"
    engine_output.write_text("snapshot")

    time.sleep(0.05)
    deb_file = tmp_path / "test.deb"
    deb_file.write_text("deb package")

    deb_mtime = deb_file.stat().st_mtime
    assert not (engine_output.stat().st_mtime > deb_mtime)

def test_force_true_runs_debuild():
    build_script = Path(__file__).parent.parent / "build.py"
    text = build_script.read_text(encoding="utf-8")
    assert "if force or rebuilt_any_artifact[0] or deb_stale or not deb_file.exists():" in text

def test_missing_deb_runs_debuild(tmp_path):
    deb_file = tmp_path / "nonexistent.deb"
    assert not deb_file.exists()

def test_package_manifest_or_script_change_runs_debuild():
    build_script = Path(__file__).parent.parent / "build.py"
    text = build_script.read_text(encoding="utf-8")
    assert "package.yaml" in text
    assert "post_install.sh" in text
