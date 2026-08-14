import os
import sys
import time
import json
import hashlib
import pytest
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import utils
import package
from build import Build


# ============================================================================
# 1. Stress Testing safe_eval: Dangerous Payloads, Builtins, and Recursion
# ============================================================================

def test_adv_safe_eval_dangerous_payloads_prevent_code_execution():
    """Verify safe_eval never executes arbitrary Python code, eval(), exec(), or imports."""
    globals_dict = {
        'tag': '3.44.0',
        'arch': 'arm64',
        'distro': 'data/data/com.termux/files/usr/opt/flutter',
    }
    defines_dict = {
        'cache': "f'{distro}/bin/cache'",
    }

    # Direct code execution attempts must return inert string without evaluation
    payloads = [
        "__import__('os').system('echo pwned')",
        "f'{__import__(\"os\").system(\"whoami\")}'",
        "f'{eval(\"1+1\")}'",
        "f'{exec(\"x=1\")}'",
        "f'{open(\"/etc/passwd\").read()}'",
        "f'{os.environ.get(\"PATH\")}'",
        "f'{__builtins__.__import__(\"os\").system(\"id\")}'",
        "f'{globals()}'",
        "f'{locals()}'",
        "f'{getattr(os, \"system\")(\"calc\")}'",
    ]

    for payload in payloads:
        res = package.safe_eval(payload, globals_dict, defines_dict)
        # Result must be a string and must NOT execute system commands
        assert isinstance(res, str)
        if payload.startswith("f'"):
            # Inside f-strings, unknown expressions are wrapped into literal braces
            assert "{" in res and "}" in res
        else:
            assert res == payload


def test_adv_safe_eval_output_attribute_access_and_rejection(tmp_path):
    """Verify safe_eval only permits whitelisted output attributes and rejects dunder/private."""
    root = tmp_path / "flutter"
    out_debug = root / "engine" / "src" / "out" / "linux_debug_arm64"
    out_debug.mkdir(parents=True)
    out_release = root / "engine" / "src" / "out" / "linux_release_arm64"
    out_release.mkdir(parents=True)
    out_profile = root / "engine" / "src" / "out" / "linux_profile_arm64"
    out_profile.mkdir(parents=True)

    output_obj = utils.Output(root=str(root), arch='arm64')
    globals_dict = {'output': output_obj}

    # Whitelisted attributes must resolve cleanly
    for attr in ['debug', 'release', 'profile', 'any']:
        res1 = package.safe_eval(f"output.{attr}", globals_dict)
        res2 = package.safe_eval(f"f'{{output.{attr}}}'", globals_dict)
        assert isinstance(res1, str) and res1.endswith(f"linux_{attr if attr != 'any' else 'debug'}_arm64")
        assert isinstance(res2, str) and res2.endswith(f"linux_{attr if attr != 'any' else 'debug'}_arm64")

    # Forbidden dunder and private attributes must raise ValueError
    forbidden = [
        '__class__', '__dict__', '__doc__', '__bases__',
        '__subclasses__', '__getattribute__', '__init__',
        '_secret', 'system', 'eval', 'exec', 'nonexistent_attr'
    ]

    for attr in forbidden:
        with pytest.raises(ValueError, match="Unauthorized or invalid output attribute"):
            package.safe_eval(f"output.{attr}", globals_dict)
        with pytest.raises(ValueError, match="Unauthorized or invalid output attribute"):
            package.safe_eval(f"f'{{output.{attr}}}'", globals_dict)


def test_adv_safe_eval_recursion_cycles_and_depth_limits():
    """Verify safe_eval detects cyclic dependencies and enforces strict recursion depth limit."""
    # Direct self cycle
    with pytest.raises(ValueError, match="Recursion depth limit exceeded"):
        package.safe_eval("f'{a}'", {}, {'a': "f'{a}'"})

    # 2-node cycle
    with pytest.raises(ValueError, match="Recursion depth limit exceeded"):
        package.safe_eval("f'{a}'", {}, {'a': "f'{b}'", 'b': "f'{a}'"})

    # 4-node cycle
    cyclic_defines = {
        'a': "f'{b}'",
        'b': "f'{c}'",
        'c': "f'{d}'",
        'd': "f'{a}'",
    }
    with pytest.raises(ValueError, match="Recursion depth limit exceeded"):
        package.safe_eval("f'{a}'", {}, cyclic_defines)

    # 10-level non-cyclic nested definitions (within max_depth=10)
    valid_chain = {f"v{i}": f"f'{{v{i+1}}}'" for i in range(1, 9)}
    valid_chain['v9'] = "'terminal_value'"
    res = package.safe_eval("f'{v1}'", {}, valid_chain)
    assert res == 'terminal_value'

    # 12-level non-cyclic nested definitions (exceeds max_depth=10)
    deep_chain = {f"k{i}": f"f'{{k{i+1}}}'" for i in range(1, 15)}
    deep_chain['k15'] = "'terminal_value'"
    with pytest.raises(ValueError, match="Recursion depth limit exceeded"):
        package.safe_eval("f'{k1}'", {}, deep_chain)


def test_adv_safe_eval_non_string_types_and_edge_cases():
    """Verify safe_eval handles non-string types, malformed quotes, and special characters."""
    # Non-string types return unchanged
    assert package.safe_eval(42, {}) == 42
    assert package.safe_eval(3.14159, {}) == 3.14159
    assert package.safe_eval(True, {}) is True
    assert package.safe_eval(False, {}) is False
    assert package.safe_eval(None, {}) is None
    assert package.safe_eval([1, 2, 3], {}) == [1, 2, 3]
    assert package.safe_eval({'k': 'v'}, {}) == {'k': 'v'}
    assert package.safe_eval(b'bytes_data', {}) == b'bytes_data'

    # Empty strings
    assert package.safe_eval("", {}) == ""
    assert package.safe_eval("f''", {}) == ""
    assert package.safe_eval("''", {}) == ""
    assert package.safe_eval('""', {}) == ""

    # Unmatched / malformed quotes
    assert package.safe_eval("f'unterminated", {}) == "f'unterminated"
    assert package.safe_eval("'single_quote_only", {}) == "'single_quote_only"
    assert package.safe_eval('"double_quote_only', {}) == '"double_quote_only'

    # Whitespace inside braces
    globals_dict = {'tag': '3.44.0'}
    assert package.safe_eval("f'{  tag  }'", globals_dict) == '3.44.0'


# ============================================================================
# 2. Stress Testing explore_file: Exact Directory & Artifact Filtering
# ============================================================================

def test_adv_explore_file_nested_cache_and_directory_filtering(tmp_path):
    """Stress test explore_file ensuring exact exclusion of hidden caches and preservation of bin/cache."""
    root = tmp_path / "flutter"
    root.mkdir()

    # 1. Normal Flutter SDK directory tree & bin/cache
    (root / "bin").mkdir()
    (root / "bin" / "flutter").write_text("#!/bin/sh\necho flutter")
    (root / "bin" / "cache").mkdir()
    (root / "bin" / "cache" / "dart-sdk" / "bin").mkdir(parents=True)
    (root / "bin" / "cache" / "dart-sdk" / "bin" / "dart").write_text("dart")
    (root / "bin" / "cache" / "artifacts" / "material_fonts").mkdir(parents=True)
    (root / "bin" / "cache" / "artifacts" / "material_fonts" / "Roboto.ttf").write_text("font")
    (root / "bin" / "cache" / "pkg" / "sky_engine" / "lib").mkdir(parents=True)
    (root / "bin" / "cache" / "pkg" / "sky_engine" / "lib" / "ui.dart").write_text("dart ui")
    (root / "packages" / "flutter" / "lib").mkdir(parents=True)
    (root / "packages" / "flutter" / "lib" / "flutter.dart").write_text("// flutter")
    (root / "packages" / "cache_metadata.json").write_text("{}")

    # 2. Hidden directories & caches that MUST be excluded anywhere in the tree
    (root / ".cache").mkdir()
    (root / ".cache" / "leak1.tmp").write_text("tmp")
    (root / "packages" / "flutter_tools" / ".cache").mkdir(parents=True)
    (root / "packages" / "flutter_tools" / ".cache" / "leak2.tmp").write_text("tmp")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "mod.cpython-311.pyc").write_text("pyc")
    (root / "packages" / "flutter_tools" / "__pycache__").mkdir(parents=True)
    (root / "packages" / "flutter_tools" / "__pycache__" / "tool.cpython-311.pyc").write_text("pyc")
    (root / ".pytest_cache").mkdir()
    (root / "packages" / "flutter_tools" / ".pytest_cache").mkdir(parents=True)
    (root / ".gradle").mkdir()
    (root / "packages" / "flutter_tools" / ".gradle").mkdir(parents=True)
    (root / ".idea").mkdir()
    (root / ".vscode").mkdir()
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]")
    (root / "engine" / "src" / "out" / "linux_debug_arm64").mkdir(parents=True)
    (root / "engine" / "src" / "BUILD.gn").write_text("gn")
    (root / "depot_tools").mkdir()
    (root / "staging").mkdir()
    (root / "out").mkdir()
    (root / ".build").mkdir()

    # 3. File suffixes that MUST be excluded
    (root / "packages" / "bad.pyc").write_text("pyc")
    (root / "packages" / "bad.pyo").write_text("pyo")
    (root / "packages" / "bad.swp").write_text("swp")
    (root / "packages" / ".DS_Store").write_text("ds_store")
    (root / "bin" / ".DS_Store").write_text("ds_store")

    # Explore root
    discovered = [p.as_posix() for p in package.explore_file(root)]

    # Assert bin/cache items ARE included
    assert "bin/flutter" in discovered
    assert "bin/cache" in discovered
    assert "bin/cache/dart-sdk/bin/dart" in discovered
    assert "bin/cache/artifacts/material_fonts/Roboto.ttf" in discovered
    assert "bin/cache/pkg/sky_engine/lib/ui.dart" in discovered
    assert "packages/flutter/lib/flutter.dart" in discovered
    assert "packages/cache_metadata.json" in discovered

    # Assert prohibited items are NOT in discovered
    for item in discovered:
        parts = item.split('/')
        assert '.cache' not in parts, f"Found .cache in {item}"
        assert '__pycache__' not in parts, f"Found __pycache__ in {item}"
        assert '.pytest_cache' not in parts, f"Found .pytest_cache in {item}"
        assert '.gradle' not in parts, f"Found .gradle in {item}"
        assert '.idea' not in parts, f"Found .idea in {item}"
        assert '.vscode' not in parts, f"Found .vscode in {item}"
        assert '.git' not in parts, f"Found .git in {item}"
        assert 'engine' not in parts, f"Found engine in {item}"
        assert 'depot_tools' not in parts, f"Found depot_tools in {item}"
        assert 'staging' not in parts, f"Found staging in {item}"
        assert 'out' not in parts, f"Found out in {item}"
        assert '.build' not in parts, f"Found .build in {item}"
        assert not item.endswith(('.pyc', '.pyo', '.swp')), f"Found bytecode/swap in {item}"
        assert not item.endswith('.DS_Store'), f"Found .DS_Store in {item}"


def test_adv_explore_file_deterministic_ordering(tmp_path):
    """Verify explore_file yields directories and files in deterministic lexicographical order."""
    root = tmp_path / "order_test"
    root.mkdir()

    # Create entries out of alphabetical order
    (root / "z_dir").mkdir()
    (root / "a_dir").mkdir()
    (root / "m_dir").mkdir()
    (root / "z_file.txt").write_text("z")
    (root / "a_file.txt").write_text("a")
    (root / "m_file.txt").write_text("m")

    (root / "a_dir" / "sub_z.txt").write_text("sz")
    (root / "a_dir" / "sub_a.txt").write_text("sa")

    res1 = [p.as_posix() for p in package.explore_file(root)]
    res2 = [p.as_posix() for p in package.explore_file(root)]

    assert res1 == res2
    # Check top-level directory sort: a_dir, m_dir, z_dir
    dir_positions = [res1.index("a_dir"), res1.index("m_dir"), res1.index("z_dir")]
    assert dir_positions == sorted(dir_positions)
    # Check file sort
    file_positions = [res1.index("a_file.txt"), res1.index("m_file.txt"), res1.index("z_file.txt")]
    assert file_positions == sorted(file_positions)


# ============================================================================
# 3. Stress Testing Path Traversal Rejection
# ============================================================================

def test_adv_validate_target_path_traversal_attacks():
    """Verify validate_target_path strictly rejects all path traversal and absolute path attacks."""
    malicious_paths = [
        "../../etc/shadow",
        "../etc/passwd",
        "/etc/passwd",
        "/usr/bin/sudo",
        "opt/../../root",
        "opt/flutter/../../../etc/shadow",
        "foo/bar/../../../../bad",
        "..",
        "./../bad",
        "a/b/../../..",
        "C:\\Windows\\System32\\cmd.exe",
        "D:/data/com.termux/files",
        "//server/share/file",
        "\\\\server\\share\\file",
        "opt/flutter/bin/../../../../etc/shadow",
        "..\\..\\etc\\shadow",
        "opt\\..\\..\\root",
        "/",
        "//",
        "///root",
    ]

    for mal_path in malicious_paths:
        with pytest.raises(ValueError, match="(Path traversal detected|Absolute target path not allowed)"):
            package.validate_target_path(mal_path)

    # Valid relative paths must pass and normalize
    valid_paths = [
        ("opt/flutter", Path("opt/flutter")),
        ("opt/flutter/bin/dart", Path("opt/flutter/bin/dart")),
        ("opt/flutter/bin/cache/dart-sdk/bin/dart", Path("opt/flutter/bin/cache/dart-sdk/bin/dart")),
        ("data/data/com.termux/files/usr/bin/flutter", Path("data/data/com.termux/files/usr/bin/flutter")),
        ("a/b/../c", Path("a/c")),
    ]

    for raw, expected in valid_paths:
        assert package.validate_target_path(raw) == expected


def test_adv_package_debuild_malicious_manifest_rejection(tmp_path):
    """Verify Package.debuild rejects malicious output manifests with directory traversal."""
    root = tmp_path / "flutter"
    root.mkdir()
    (root / "payload.sh").write_text("#!/bin/sh\necho malicious")

    control = {
        'Package': 'flutter',
        'Version': '3.44.0',
        'Architecture': 'aarch64',
        'Maintainer': 'Test <test@example.com>',
        'Description': 'Test package',
    }

    # Manifest attempting path traversal into /etc/cron.d
    traversal_resource = {
        'exploit': {
            'source': str(root / "payload.sh"),
            'output': '../../etc/cron.d/backdoor'
        }
    }

    pkg = package.Package(root=root, arch='arm64', control=control, resource=traversal_resource)
    with pytest.raises(ValueError, match="Path traversal detected"):
        pkg.debuild(output=tmp_path / "out.deb")


# ============================================================================
# 4. Stress Testing build_all Mtime Staleness & Concatenation Freshness
# ============================================================================

def test_adv_build_all_mtime_staleness_comprehensive(tmp_path, monkeypatch):
    """Verify build_all staleness logic across all tracked inputs without TypeError."""
    monkeypatch.setattr(Build, "is_sync_complete", lambda self, *a, **kw: True)
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

    # Populate all engine outputs
    all_artifacts = [
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
    ]

    for p in all_artifacts:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("content")

    (out_debug / "gen" / "dart-pkg" / "sky_engine").mkdir(parents=True, exist_ok=True)
    (root / ".gclient_sync.receipt.json").write_text(json.dumps({"tag": "3.44.2", "completed": True, "timestamp": time.time()}))

    deb_file = tmp_path / "flutter_3.44.2_aarch64.deb"

    def create_build_instance():
        b = Build()
        b.root = Path(root)
        b.tag = "3.44.2"
        b.output = lambda arch: str(deb_file)
        b.preflight = lambda: True
        b.clone = lambda **kw: None
        b.sync = lambda **kw: None
        b.patch = lambda **kw: None
        b.patch_engine = lambda: None
        b.patch_dart = lambda: None
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
        return b

    # Scenario 1: deb_file is brand new, newer than all artifacts -> skips debuild
    deb_file.write_text("deb package")
    future_time = time.time() + 500
    os.utime(deb_file, (future_time, future_time))

    b = create_build_instance()
    debuild_calls = []
    b.debuild = lambda **kw: debuild_calls.append(True)
    b.build_all(arch="arm64")
    assert len(debuild_calls) == 0, "Expected debuild to be skipped when deb is fresh"

    # Scenario 2: Touch debug tool (impellerc) -> triggers debuild
    (out_debug / "impellerc").write_text("new impellerc")
    impeller_time = time.time() + 600
    os.utime(out_debug / "impellerc", (impeller_time, impeller_time))
    b = create_build_instance()
    debuild_calls = []
    b.debuild = lambda **kw: debuild_calls.append(True)
    b.build_all(arch="arm64")
    assert len(debuild_calls) == 1, "Expected debuild to trigger when debug artifact updated"

    # Scenario 3: Update deb -> skipped; Touch release output (gen_snapshot) -> triggers debuild
    deb_file.write_text("deb package updated")
    deb_time = time.time() + 700
    os.utime(deb_file, (deb_time, deb_time))
    (out_release / "gen_snapshot").write_text("new gen_snapshot")
    gen_time = time.time() + 800
    os.utime(out_release / "gen_snapshot", (gen_time, gen_time))
    b = create_build_instance()
    debuild_calls = []
    b.debuild = lambda **kw: debuild_calls.append(True)
    b.build_all(arch="arm64")
    assert len(debuild_calls) == 1, "Expected debuild to trigger when release artifact updated"

    # Scenario 4: Update deb -> skipped; Touch build.toml -> triggers debuild
    deb_file.write_text("deb package updated again")
    deb_time2 = time.time() + 900
    os.utime(deb_file, (deb_time2, deb_time2))
    b = create_build_instance()
    debuild_calls = []
    b.debuild = lambda **kw: debuild_calls.append(True)
    # Temporarily touch build.toml in repo
    build_toml_path = REPO_ROOT / "build.toml"
    orig_toml_mtime = build_toml_path.stat().st_mtime
    try:
        os.utime(build_toml_path, (time.time() + 1000, time.time() + 1000))
        b.build_all(arch="arm64")
        assert len(debuild_calls) == 1, "Expected debuild to trigger when build.toml updated"
    finally:
        os.utime(build_toml_path, (orig_toml_mtime, orig_toml_mtime))


def test_adv_build_all_package_inputs_set_concatenation_no_typeerror(tmp_path, monkeypatch):
    """Regression test for Issue #50: verify list(package_inputs) concatenation prevents TypeError."""
    monkeypatch.setattr(Build, "is_sync_complete", lambda self, *a, **kw: True)
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
    (root / ".gclient_sync.receipt.json").write_text(json.dumps({"tag": "3.44.2", "completed": True, "timestamp": time.time()}))

    deb_file = tmp_path / "flutter_3.44.2_aarch64.deb"
    deb_file.write_text("deb package")

    b = Build()
    b.root = Path(root)
    b.tag = "3.44.2"
    b.output = lambda arch: str(deb_file)
    b.preflight = lambda: True
    b.clone = lambda **kw: None
    b.sync = lambda **kw: None
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
    b.debuild = lambda **kw: None

    # Must complete without TypeError: can only concatenate list (not "set") to list
    b.build_all(arch="arm64")
