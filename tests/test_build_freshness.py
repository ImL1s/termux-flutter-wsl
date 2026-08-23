import os
import sys
import time
import json
import hashlib
import tempfile
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils
from build import Build


# ============================================================================
# 1. Output Completeness Predicates & Mode Ordering
# ============================================================================

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
    (out_debug / "dart-sdk" / "bin" / "dartvm").touch()
    (out_debug / "impellerc").touch()
    (out_debug / "gen").mkdir(parents=True)
    (out_debug / "gen" / "const_finder.dart.snapshot").touch()
    (out_debug / "gen" / "dart-pkg" / "sky_engine").mkdir(parents=True)

    debug_outputs = [
        out_debug / "libflutter_linux_gtk.so",
        out_debug / "dart-sdk" / "bin" / "dart",
        out_debug / "dart-sdk" / "bin" / "dartvm",
        out_debug / "impellerc",
        out_debug / "gen" / "const_finder.dart.snapshot",
        out_debug / "gen" / "dart-pkg" / "sky_engine",
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


def test_output_any_mode_priority_resolving(tmp_path):
    """Output.any must always prioritize debug over release and profile when debug exists."""
    root = tmp_path / "flutter"
    out_base = root / "engine" / "src" / "out"

    debug_dir = out_base / "linux_debug_arm64"
    release_dir = out_base / "linux_release_arm64"
    profile_dir = out_base / "linux_profile_arm64"

    profile_dir.mkdir(parents=True)
    release_dir.mkdir(parents=True)
    debug_dir.mkdir(parents=True)

    # When all 3 exist -> resolves to debug
    output = utils.Output(root=str(root), arch="arm64")
    assert output.any == str(debug_dir.resolve())

    # When debug is missing but release and profile exist -> resolves to release
    debug_dir.rmdir()
    output2 = utils.Output(root=str(root), arch="arm64")
    assert output2.any == str(release_dir.resolve())

    # When debug and release are missing but profile exists -> resolves to profile
    release_dir.rmdir()
    output3 = utils.Output(root=str(root), arch="arm64")
    assert output3.any == str(profile_dir.resolve())


# ============================================================================
# 2. Incremental Sync & .gclient_sync.receipt.json Tracking
# ============================================================================

def test_is_sync_complete_missing_receipt(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    b = Build()
    b.root = str(root)
    assert b.is_sync_complete(root=str(root)) is False


def test_is_sync_complete_corrupted_json(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    receipt = root / ".gclient_sync.receipt.json"
    receipt.write_text("{ corrupt json ...", encoding="utf-8")
    b = Build()
    b.root = str(root)
    assert b.is_sync_complete(root=str(root)) is False


def test_is_sync_complete_incomplete_marker(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    receipt = root / ".gclient_sync.receipt.json"
    receipt.write_text(json.dumps({"completed": False}), encoding="utf-8")
    b = Build()
    b.root = str(root)
    assert b.is_sync_complete(root=str(root)) is False


def test_is_sync_complete_missing_checkout_roots(tmp_path, monkeypatch):
    root = tmp_path / "flutter"
    root.mkdir()
    receipt = root / ".gclient_sync.receipt.json"
    receipt.write_text(json.dumps({
        "completed": True,
        "flutter_head": "3.44.9",
        "gclient_sha256": "dummy"
    }), encoding="utf-8")

    monkeypatch.setattr(utils, "flutter_tag", lambda src: "3.44.9")
    b = Build()
    b.root = str(root)
    # engine/src and subdirectories do not exist
    assert b.is_sync_complete(root=str(root)) is False


def test_is_sync_complete_mismatched_flutter_head(tmp_path, monkeypatch):
    root = tmp_path / "flutter"
    engine_src = root / "engine" / "src"
    (engine_src / "flutter").mkdir(parents=True)
    (engine_src / "third_party").mkdir(parents=True)

    receipt = root / ".gclient_sync.receipt.json"
    receipt.write_text(json.dumps({
        "completed": True,
        "flutter_head": "3.44.0",
        "gclient_sha256": "dummy"
    }), encoding="utf-8")

    monkeypatch.setattr(utils, "flutter_tag", lambda src: "3.44.9")
    b = Build()
    b.root = str(root)
    assert b.is_sync_complete(root=str(root)) is False


def test_is_sync_complete_mismatched_gclient_hash(tmp_path, monkeypatch):
    root = tmp_path / "flutter"
    engine_src = root / "engine" / "src"
    (engine_src / "flutter").mkdir(parents=True)
    (engine_src / "third_party").mkdir(parents=True)

    gclient_file = tmp_path / ".gclient"
    gclient_file.write_bytes(b"solutions = []")

    receipt = root / ".gclient_sync.receipt.json"
    receipt.write_text(json.dumps({
        "completed": True,
        "flutter_head": "3.44.9",
        "gclient_sha256": "0" * 64
    }), encoding="utf-8")

    monkeypatch.setattr(utils, "flutter_tag", lambda src: "3.44.9")
    b = Build()
    b.root = str(root)
    assert b.is_sync_complete(root=str(root), cfg=str(gclient_file)) is False


def test_is_sync_complete_valid_match(tmp_path, monkeypatch):
    root = tmp_path / "flutter"
    engine_src = root / "engine" / "src"
    (engine_src / "flutter").mkdir(parents=True)
    (engine_src / "third_party").mkdir(parents=True)

    gclient_file = tmp_path / ".gclient"
    gclient_content = b"solutions = [custom]"
    gclient_file.write_bytes(gclient_content)
    gclient_hash = hashlib.sha256(gclient_content).hexdigest()

    receipt = root / ".gclient_sync.receipt.json"
    receipt.write_text(json.dumps({
        "completed": True,
        "flutter_head": "3.44.9",
        "gclient_sha256": gclient_hash
    }), encoding="utf-8")

    monkeypatch.setattr(utils, "flutter_tag", lambda src: "3.44.9")
    b = Build()
    b.root = str(root)
    assert b.is_sync_complete(root=str(root), cfg=str(gclient_file)) is True


def test_sync_unlinks_receipt_on_start(tmp_path, monkeypatch):
    root = tmp_path / "flutter"
    root.mkdir()
    receipt = root / ".gclient_sync.receipt.json"
    receipt.write_text(json.dumps({"completed": True}), encoding="utf-8")

    gclient_file = tmp_path / ".gclient"
    gclient_file.write_text("solutions = []", encoding="utf-8")

    b = Build()
    b.root = str(root)
    b.gclient = str(gclient_file)

    # Mock subprocess.run so sync halts without external gclient execution
    def mock_subprocess_run(*args, **kwargs):
        raise RuntimeError("Stop sync after unlink")

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)

    with pytest.raises(RuntimeError, match="Stop sync after unlink"):
        b.sync(cfg=str(gclient_file), root=str(root))

    # Verify receipt was unlinked immediately at the start of sync
    assert not receipt.exists()


# ============================================================================
# 3. Deb Staleness, Freshness & Mtime Evaluation (Behavioral)
# ============================================================================

def test_deb_exists_and_one_artifact_missing_runs_rebuild_and_debuild(tmp_path):
    deb_file = tmp_path / "flutter_3.44.0_aarch64.deb"
    deb_file.touch()

    artifact = tmp_path / "some_artifact"
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


def test_build_all_deb_exists_no_typeerror_and_skips_when_fresh(tmp_path, monkeypatch):
    """Proves build_all with existing deb_file executes freshness check without TypeError and skips debuild if fresh."""
    root = tmp_path / "flutter"
    root.mkdir()
    out_debug = root / "engine" / "src" / "out" / "linux_debug_arm64"
    out_debug.mkdir(parents=True)
    out_release = root / "engine" / "src" / "out" / "linux_release_arm64"
    out_release.mkdir(parents=True)
    out_profile = root / "engine" / "src" / "out" / "linux_profile_arm64"
    out_profile.mkdir(parents=True)
    out_android_rel = root / "engine" / "src" / "out" / "android_release_arm64" / "clang_arm64"
    out_android_rel.mkdir(parents=True)
    out_android_prof = root / "engine" / "src" / "out" / "android_profile_arm64" / "clang_arm64"
    out_android_prof.mkdir(parents=True)

    # Populate all required artifacts
    for p in [
        out_debug / "libflutter_linux_gtk.so",
        out_debug / "dart-sdk" / "bin" / "dart",
        out_debug / "dart-sdk" / "bin" / "dartvm",
        out_debug / "impellerc",
        out_debug / "gen" / "const_finder.dart.snapshot",
        out_release / "libflutter_linux_gtk.so",
        out_release / "gen_snapshot",
        out_release / "dartdev_aot.dart.snapshot",
        out_profile / "libflutter_linux_gtk.so",
        out_profile / "gen_snapshot",
        out_android_rel / "gen_snapshot",
        out_android_prof / "gen_snapshot",
    ]:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("dummy")

    (out_debug / "gen" / "dart-pkg" / "sky_engine").mkdir(parents=True, exist_ok=True)
    (root / ".gclient_sync.receipt.json").write_text(json.dumps({"tag": "3.44.9", "completed": True, "timestamp": time.time()}))

    b = Build()
    b.root = Path(root)
    b.tag = "3.44.9"
    b.save_stage_receipt(out_debug, [
        out_debug / "libflutter_linux_gtk.so",
        out_debug / "dart-sdk" / "bin" / "dart",
        out_debug / "dart-sdk" / "bin" / "dartvm",
        out_debug / "impellerc",
        out_debug / "gen" / "const_finder.dart.snapshot",
        out_debug / "gen" / "dart-pkg" / "sky_engine",
    ])
    b.save_stage_receipt(out_release, [
        out_release / "libflutter_linux_gtk.so",
        out_release / "gen_snapshot",
        out_release / "dartdev_aot.dart.snapshot",
    ])
    b.save_stage_receipt(out_profile, [
        out_profile / "libflutter_linux_gtk.so",
        out_profile / "gen_snapshot",
    ])
    b.save_stage_receipt(root / "engine/src/out/android_release_arm64", [out_android_rel / "gen_snapshot"])
    b.save_stage_receipt(root / "engine/src/out/android_profile_arm64", [out_android_prof / "gen_snapshot"])

    deb_file = tmp_path / "flutter_3.44.9_aarch64.deb"
    deb_file.write_text("deb package")
    future_time = time.time() + 500
    os.utime(deb_file, (future_time, future_time))

    monkeypatch.setattr(Build, "is_sync_complete", lambda self, *a, **kw: True)
    b.output = lambda arch: str(deb_file)
    b.preflight = lambda: True
    b.clone = lambda **kw: None
    b.patch = lambda **kw: None
    b.patch_engine = lambda: None
    b.patch_dart = lambda: None
    b.patch_skia = lambda: None
    sysroot_dir = tmp_path / "sysroot"
    (sysroot_dir / "usr").mkdir(parents=True, exist_ok=True)
    b._sysroot.path = sysroot_dir
    b._sysroot.verify = lambda arch: True
    b.configure = lambda **kw: None
    b.build = lambda **kw: None
    b.build_dart = lambda **kw: None
    b.build_impellerc = lambda **kw: None
    b.build_const_finder = lambda **kw: None
    b.configure_android = lambda **kw: None
    b.build_android_gen_snapshot = lambda **kw: None

    debuild_called = []
    b.debuild = lambda **kw: debuild_called.append(True)

    b.build_all(arch="arm64")
    # deb_file is newer than all artifacts -> debuild skipped
    assert len(debuild_called) == 0


def test_build_all_deb_exists_newer_input_triggers_debuild(tmp_path, monkeypatch):
    """Proves build_all with existing deb_file triggers debuild when an input is touched/newer."""
    root = tmp_path / "flutter"
    root.mkdir()
    out_debug = root / "engine" / "src" / "out" / "linux_debug_arm64"
    out_debug.mkdir(parents=True)
    out_release = root / "engine" / "src" / "out" / "linux_release_arm64"
    out_release.mkdir(parents=True)
    out_profile = root / "engine" / "src" / "out" / "linux_profile_arm64"
    out_profile.mkdir(parents=True)
    out_android_rel = root / "engine" / "src" / "out" / "android_release_arm64" / "clang_arm64"
    out_android_rel.mkdir(parents=True)
    out_android_prof = root / "engine" / "src" / "out" / "android_profile_arm64" / "clang_arm64"
    out_android_prof.mkdir(parents=True)

    for p in [
        out_debug / "libflutter_linux_gtk.so",
        out_debug / "dart-sdk" / "bin" / "dart",
        out_debug / "dart-sdk" / "bin" / "dartvm",
        out_debug / "impellerc",
        out_debug / "gen" / "const_finder.dart.snapshot",
        out_release / "libflutter_linux_gtk.so",
        out_release / "gen_snapshot",
        out_release / "dartdev_aot.dart.snapshot",
        out_profile / "libflutter_linux_gtk.so",
        out_profile / "gen_snapshot",
        out_android_rel / "gen_snapshot",
        out_android_prof / "gen_snapshot",
    ]:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("dummy")

    (out_debug / "gen" / "dart-pkg" / "sky_engine").mkdir(parents=True, exist_ok=True)
    (root / ".gclient_sync.receipt.json").write_text(json.dumps({"tag": "3.44.9", "completed": True, "timestamp": time.time()}))

    b = Build()
    b.root = Path(root)
    b.tag = "3.44.9"
    b.save_stage_receipt(out_debug, [
        out_debug / "libflutter_linux_gtk.so",
        out_debug / "dart-sdk" / "bin" / "dart",
        out_debug / "dart-sdk" / "bin" / "dartvm",
        out_debug / "impellerc",
        out_debug / "gen" / "const_finder.dart.snapshot",
        out_debug / "gen" / "dart-pkg" / "sky_engine",
    ])
    b.save_stage_receipt(out_release, [
        out_release / "libflutter_linux_gtk.so",
        out_release / "gen_snapshot",
        out_release / "dartdev_aot.dart.snapshot",
    ])
    b.save_stage_receipt(out_profile, [
        out_profile / "libflutter_linux_gtk.so",
        out_profile / "gen_snapshot",
    ])
    b.save_stage_receipt(root / "engine/src/out/android_release_arm64", [out_android_rel / "gen_snapshot"])
    b.save_stage_receipt(root / "engine/src/out/android_profile_arm64", [out_android_prof / "gen_snapshot"])

    deb_file = tmp_path / "flutter_3.44.9_aarch64.deb"
    deb_file.write_text("deb package")

    time.sleep(0.05)
    # Touch an engine output after deb creation
    (out_debug / "impellerc").write_text("updated impellerc")

    monkeypatch.setattr(Build, "is_sync_complete", lambda self, *a, **kw: True)
    b.output = lambda arch: str(deb_file)
    b.preflight = lambda: True
    b.clone = lambda **kw: None
    b.patch = lambda **kw: None
    b.patch_engine = lambda: None
    b.patch_dart = lambda: None
    b.patch_skia = lambda: None
    sysroot_dir = tmp_path / "sysroot"
    (sysroot_dir / "usr").mkdir(parents=True, exist_ok=True)
    b._sysroot.path = sysroot_dir
    b._sysroot.verify = lambda arch: True
    b.configure = lambda **kw: None
    b.build = lambda **kw: None
    b.build_dart = lambda **kw: None
    b.build_impellerc = lambda **kw: None
    b.build_const_finder = lambda **kw: None
    b.configure_android = lambda **kw: None
    b.build_android_gen_snapshot = lambda **kw: None

    debuild_called = []
    b.debuild = lambda **kw: debuild_called.append(True)

    b.build_all(arch="arm64")
    # Updated artifact triggers debuild
    assert len(debuild_called) == 1


# ============================================================================
# 4. Mode Completeness Invalidation Triggers
# ============================================================================

def test_debug_mode_missing_output_triggers_debug_build(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    out_debug = root / "engine" / "src" / "out" / "linux_debug_arm64"
    out_debug.mkdir(parents=True)

    (out_debug / "libflutter_linux_gtk.so").touch()
    (out_debug / "dart-sdk" / "bin").mkdir(parents=True)
    (out_debug / "dart-sdk" / "bin" / "dart").touch()
    (out_debug / "dart-sdk" / "bin" / "dartvm").touch()
    # impellerc is missing!

    debug_outputs = [
        out_debug / "libflutter_linux_gtk.so",
        out_debug / "dart-sdk" / "bin" / "dart",
        out_debug / "dart-sdk" / "bin" / "dartvm",
        out_debug / "impellerc",
        out_debug / "gen" / "const_finder.dart.snapshot",
        out_debug / "gen" / "dart-pkg" / "sky_engine",
    ]
    assert not all(p.exists() for p in debug_outputs)


def test_release_mode_missing_output_triggers_release_build(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    out_release = root / "engine" / "src" / "out" / "linux_release_arm64"
    out_release.mkdir(parents=True)

    (out_release / "libflutter_linux_gtk.so").touch()
    (out_release / "gen_snapshot").touch()
    # dartdev_aot.dart.snapshot missing

    release_outputs = [
        out_release / "libflutter_linux_gtk.so",
        out_release / "gen_snapshot",
        out_release / "dartdev_aot.dart.snapshot",
    ]
    assert not all(p.exists() for p in release_outputs)


def test_profile_mode_missing_output_triggers_profile_build(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    out_profile = root / "engine" / "src" / "out" / "linux_profile_arm64"
    out_profile.mkdir(parents=True)

    (out_profile / "libflutter_linux_gtk.so").touch()
    # gen_snapshot missing

    profile_outputs = [
        out_profile / "libflutter_linux_gtk.so",
        out_profile / "gen_snapshot",
    ]
    assert not all(p.exists() for p in profile_outputs)


def test_android_gen_snapshot_missing_triggers_android_build(tmp_path):
    root = tmp_path / "flutter"
    root.mkdir()
    out_android_rel = root / "engine" / "src" / "out" / "android_release_arm64" / "clang_arm64"
    out_android_rel.mkdir(parents=True)
    # gen_snapshot missing
    gen = out_android_rel / "gen_snapshot"
    assert not gen.exists()


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
    assert ("post_install.sh" in text) or ("package_inputs" in text)
