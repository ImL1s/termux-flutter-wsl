#!/usr/bin/env python3

import os
import sys
import io
import git
import fire
import yaml
import utils
import shutil
import tarfile
import tomllib
import platform
import subprocess
from loguru import logger
from pathlib import Path
from sysroot import Sysroot
from package import Package


REQUIRED_DEB_ARTIFACTS = (
    'opt/flutter/bin/cache/dart-sdk/bin/dart',
    'opt/flutter/bin/cache/dart-sdk/bin/dartvm',
    'opt/flutter/bin/cache/dart-sdk/bin/dartaotruntime',
)


def _ar_members(path):
    with open(path, 'rb') as f:
        if f.read(8) != b'!<arch>\n':
            raise ValueError(f'bad deb archive: "{path}"')

        while header := f.read(60):
            if len(header) != 60:
                raise ValueError(f'truncated deb archive header: "{path}"')

            name = header[:16].decode('utf8').strip().rstrip('/')
            size = int(header[48:58].decode('utf8').strip())
            data = f.read(size)
            if len(data) != size:
                raise ValueError(f'truncated deb archive member: "{name}"')
            if size % 2:
                f.read(1)
            yield name, data


def validate_deb_artifacts(path):
    """Fail packaging if required Termux runtime binaries are missing."""
    data_member = None
    for name, data in _ar_members(path):
        if name.startswith('data.tar'):
            data_member = data
            break
    if data_member is None:
        raise ValueError(f'data archive not found in deb: "{path}"')

    found = {}
    with tarfile.open(fileobj=io.BytesIO(data_member), mode='r:*') as data_tar:
        for member in data_tar:
            if not member.isfile():
                continue
            name = member.name.lstrip('./')
            for suffix in REQUIRED_DEB_ARTIFACTS:
                if name.endswith(suffix):
                    found[suffix] = member

    missing = [it for it in REQUIRED_DEB_ARTIFACTS if it not in found]
    if missing:
        raise RuntimeError(
            'deb missing required Flutter runtime artifact(s): '
            + ', '.join(missing))

    non_executable = [
        it for it, member in found.items()
        if member.mode & 0o111 == 0
    ]
    if non_executable:
        raise RuntimeError(
            'deb runtime artifact(s) are not executable: '
            + ', '.join(non_executable))

    logger.info(
        '✓ Validated deb runtime artifacts: '
        + ', '.join(Path(it).name for it in REQUIRED_DEB_ARTIFACTS))


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override dict into base dict."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class GitProgress(git.RemoteProgress):
    def update(self, op_code, cur_count, max_count=None, message=''):
        logger.trace(f"cloning {cur_count}/{max_count} {message}")


@utils.record
class Build:
    @utils.recordm
    def __init__(self, conf='build.toml'):
        path = Path(__file__).parent
        conf_path = path / conf

        # Explicitly add depot_tools to PATH
        depot_tools_path = path / 'depot_tools'
        if depot_tools_path.is_dir():
            os.environ['PATH'] = str(depot_tools_path) + os.pathsep + os.environ['PATH']
            logger.info(f"Added {depot_tools_path} to PATH")

        # 1. Load base configuration
        cfg = {}
        if conf_path.is_file():
            with open(conf_path, 'rb') as f:
                cfg = tomllib.load(f)

        # 2. Deep-merge local configuration override (build.local.toml)
        local_conf = conf_path.parent / 'build.local.toml'
        if local_conf.is_file():
            logger.info(f"Loading local configuration override from {local_conf}")
            with open(local_conf, 'rb') as f:
                local_cfg = tomllib.load(f)
            cfg = _deep_merge(cfg, local_cfg)

        # 3. Resolve NDK path (Env priority: NDK_PATH -> ANDROID_NDK -> ANDROID_NDK_HOME -> ANDROID_NDK_ROOT -> config)
        ndk = (
            os.environ.get('NDK_PATH')
            or os.environ.get('ANDROID_NDK')
            or os.environ.get('ANDROID_NDK_HOME')
            or os.environ.get('ANDROID_NDK_ROOT')
            or cfg.get('ndk', {}).get('path')
        )

        api = cfg.get('ndk', {}).get('api', 35)
        tag = cfg.get('flutter', {}).get('tag')
        release_tag = cfg.get('flutter', {}).get('release_tag', f'v{tag}-termux' if tag else None)
        dart_version = cfg.get('flutter', {}).get('dart_version', '3.12.0')
        sha256 = cfg.get('flutter', {}).get('sha256')
        asset_name = cfg.get('flutter', {}).get('asset_name', f'flutter_{tag}_aarch64.deb' if tag else None)
        repo = cfg.get('flutter', {}).get('repo')
        root = cfg.get('flutter', {}).get('path', './flutter')
        arch = cfg.get('build', {}).get('arch', ['arm64'])
        mode = cfg.get('build', {}).get('runtime', ['debug'])
        gclient = cfg.get('build', {}).get('gclient', './.gclient')

        # 4. Resolve build jobs (Env NINJA_JOBS / JOBS -> config -> dynamic cpu_count)
        env_jobs = os.environ.get('NINJA_JOBS') or os.environ.get('JOBS')
        if env_jobs and env_jobs.isdigit() and int(env_jobs) > 0:
            jobs = int(env_jobs)
        else:
            cfg_jobs = cfg.get('build', {}).get('jobs')
            if cfg_jobs and isinstance(cfg_jobs, int) and cfg_jobs > 0:
                jobs = cfg_jobs
            else:
                jobs = os.cpu_count() or 4

        sync_cfg = cfg.get('sync', {})
        sysroot = cfg.get('sysroot', {})
        syspath = sysroot.pop('path', './sysroot') if isinstance(sysroot, dict) and 'path' in sysroot else './sysroot'
        package = cfg.get('package', {}).get('conf', './package.yaml')
        release = cfg.get('package', {}).get('path', '.')
        patches = cfg.get('patch')

        if not tag:
            raise ValueError('require flutter tag in config')

        self.ndk = ndk
        self.tag = tag
        self.release_tag = release_tag
        self.dart_version = dart_version
        self.sha256 = sha256
        self.asset_name = asset_name
        self.api = api or 35
        self.conf = conf_path
        self.host = 'linux-x86_64'
        self.repo = repo or 'https://github.com/flutter/flutter'
        self.arch = arch if isinstance(arch, list) else [arch]
        self.mode = mode if isinstance(mode, list) else [mode]
        self._sysroot = Sysroot(path=path/syspath, **sysroot)
        self.root = path/root
        self.gclient = path/gclient
        self.release = path/release
        self.toolchain = Path(ndk, f'toolchains/llvm/prebuilt/{self.host}') if ndk else None
        self.jobs = jobs
        self.sync_cfg = sync_cfg

        if not self.release.parent.is_dir():
            raise ValueError(f'bad release path: "{release}"')

        with open(path/package, 'rb') as f:
            self.package = yaml.safe_load(f)

        if isinstance(patches, dict):
            self.patches = {}
            patch_base = path / patches.get('dir', './patches') / self.tag

            def patch(key):
                return lambda: self.patch(**self.patches[key])

            for k, v in patches.items():
                if k == 'dir' or not isinstance(v, dict):
                    continue
                self.patches[k] = {
                    'file': patch_base / v['file'],
                    'path': self.root / v['path']}
                self.__dict__[f'patch_{k}'] = patch(k)

    def config(self):
        info = (f'{k}\t: {v}' for k, v in self.__dict__.items() if k != 'package')
        logger.info('\n'+'\n'.join(info))

    def preflight(self) -> bool:
        """Run preflight environment and dependency checks for Flutter Termux build."""
        logger.info("=== Running Preflight Verification Checks ===")
        results = []

        # 1. Host OS Check
        system = platform.system()
        if system == 'Linux':
            results.append(('PASS', 'Host OS', f'Linux ({platform.release()})', None))
        else:
            results.append((
                'WARN' if system == 'Windows' else 'FAIL',
                'Host OS',
                f'{system} ({platform.release()})',
                'Flutter Engine cross-compilation requires Linux or WSL2.'
            ))

        # 2. Android NDK Check
        ndk_path = self.ndk
        if ndk_path and os.path.exists(ndk_path):
            toolchain_dir = Path(ndk_path) / 'toolchains' / 'llvm' / 'prebuilt' / self.host
            clang_bin = toolchain_dir / 'bin' / 'clang'
            if clang_bin.exists():
                results.append(('PASS', 'Android NDK', f'{ndk_path} (API {self.api} toolchain valid)', None))
            else:
                results.append((
                    'FAIL',
                    'Android NDK',
                    f'{ndk_path} exists but toolchain at {toolchain_dir} is invalid or missing clang',
                    'Ensure NDK r27d or compatible NDK is installed for host linux-x86_64.'
                ))
        else:
            results.append((
                'FAIL',
                'Android NDK',
                f'NDK path "{ndk_path}" not set or directory not found',
                'Export NDK_PATH=/path/to/ndk or set path = "/path/to/ndk" in build.local.toml.'
            ))

        # 3. Build Tools Check (git, ninja, gclient)
        missing_tools = []
        for tool in ['git', 'ninja']:
            if not shutil.which(tool):
                missing_tools.append(tool)
        gclient_found = bool(shutil.which('gclient')) or (Path(__file__).parent / 'depot_tools' / 'gclient').exists()
        if not gclient_found:
            missing_tools.append('gclient (depot_tools)')

        if not missing_tools:
            results.append(('PASS', 'Build Tools', 'git, ninja, gclient found', None))
        else:
            results.append((
                'FAIL',
                'Build Tools',
                f'Missing tool(s): {", ".join(missing_tools)}',
                'Install build dependencies and ensure depot_tools is installed/cloned.'
            ))

        # 4. Python Dependencies
        missing_pkgs = []
        for pkg_name in ['yaml', 'git', 'fire', 'loguru', 'aiohttp']:
            try:
                __import__(pkg_name)
            except ImportError:
                missing_pkgs.append(pkg_name)
        if not missing_pkgs:
            results.append(('PASS', 'Python Dependencies', 'all required packages installed', None))
        else:
            results.append((
                'FAIL',
                'Python Dependencies',
                f'Missing package(s): {", ".join(missing_pkgs)}',
                'Run: pip install pyyaml gitpython fire loguru aiohttp'
            ))

        # 5. Disk Space Check
        try:
            usage = shutil.disk_usage(Path(__file__).parent)
            free_gb = usage.free / (1024 ** 3)
            if free_gb >= 30.0:
                results.append(('PASS', 'Disk Space', f'{free_gb:.1f} GB free', None))
            elif free_gb >= 10.0:
                results.append((
                    'WARN',
                    'Disk Space',
                    f'{free_gb:.1f} GB free (30GB+ recommended for full engine sync)',
                    'Consider freeing up disk space.'
                ))
            else:
                results.append((
                    'FAIL',
                    'Disk Space',
                    f'{free_gb:.1f} GB free (<10GB critically low)',
                    'Free up at least 30-50GB space.'
                ))
        except Exception as e:
            results.append(('WARN', 'Disk Space', f'Unable to check: {e}', None))

        # Output Summary
        passes = sum(1 for status, *_ in results if status == 'PASS')
        warns = sum(1 for status, *_ in results if status == 'WARN')
        fails = sum(1 for status, *_ in results if status == 'FAIL')

        logger.info("============================================================")
        logger.info("              Preflight Check Results                       ")
        logger.info("============================================================")
        for status, name, msg, suggestion in results:
            if status == 'PASS':
                logger.info(f"[PASS] {name}: {msg}")
            elif status == 'WARN':
                logger.warning(f"[WARN] {name}: {msg}")
                if suggestion:
                    logger.warning(f"  -> Suggestion: {suggestion}")
            else:
                logger.error(f"[FAIL] {name}: {msg}")
                if suggestion:
                    logger.error(f"  -> Suggestion: {suggestion}")
        logger.info("============================================================")

        if fails == 0:
            logger.success(f"Preflight verification PASSED ({passes} pass, {warns} warn)")
            return True
        else:
            logger.error(f"Preflight verification FAILED ({fails} fail, {warns} warn, {passes} pass)")
            return False

    def clone(self, *, url: str = None, tag: str = None, out: str = None):
        url = url or self.repo
        out_path = Path(out or self.root)
        tag = tag or self.tag
        progress = GitProgress()

        if out_path.is_dir():
            current_tag = utils.flutter_tag(str(out_path))
            if current_tag == tag:
                logger.info(f'flutter exists at {out_path} with tag {tag}, skipping clone.')
                return

            # Attempt checkout of target tag inside existing repository
            try:
                repo = git.Repo(out_path)
                logger.info(f'Existing flutter checkout tag "{current_tag}" != target "{tag}". Attempting git checkout {tag}...')
                repo.git.fetch('origin', '--tags')
                repo.git.checkout(tag)
                if utils.flutter_tag(str(out_path)) == tag:
                    logger.success(f'Successfully checked out tag {tag} in {out_path}.')
                    return
            except Exception as e:
                logger.warning(f'Failed to checkout tag {tag} in existing directory {out_path}: {e}')

            # Backup existing directory if checkout failed or invalid repo
            backup_path = out_path.parent / f'{out_path.name}.old'
            if backup_path.exists():
                logger.info(f'Removing existing backup directory {backup_path}...')
                if backup_path.is_dir():
                    shutil.rmtree(backup_path)
                else:
                    backup_path.unlink()

            logger.info(f'Moving existing directory {out_path} to {backup_path}...')
            os.rename(out_path, backup_path)

        logger.info(f'Cloning flutter {tag} from {url} to {out_path}...')
        try:
            git.Repo.clone_from(
                url=url,
                to_path=str(out_path),
                progress=progress,
                branch=tag)
            logger.success(f'Successfully cloned flutter {tag} to {out_path}')
        except git.exc.GitCommandError as e:
            raise RuntimeError(f'Failed to clone flutter repo:\n' + '\n'.join(progress.error_lines)) from e

    def sync(self, *, cfg: str = None, root: str = None):
        cfg = cfg or self.gclient
        src = root or self.root

        shutil.copy(cfg, os.path.join(src, '.gclient'))
        cmd = ['gclient', 'sync', '-DR', '--no-history']
        subprocess.run(cmd, cwd=src, check=True)

        # Fix #5: package_config.json language version too old
        # 1. Replace prebuilt dart-sdk with matching version from build.toml
        engine_src_dir = Path(src) / 'engine' / 'src'
        engine_checkout_dir = engine_src_dir / 'flutter'
        if not engine_checkout_dir.exists():
            engine_checkout_dir = engine_src_dir

        dart_dir = engine_checkout_dir / 'third_party' / 'dart'
        dart_sdk_dir = dart_dir / 'tools' / 'sdks' / 'dart-sdk'
        if dart_sdk_dir.exists():
            import urllib.request
            import zipfile
            import tempfile
            
            version_file = dart_sdk_dir / 'version'
            if version_file.exists() and version_file.read_text().strip() == self.dart_version:
                logger.info(f'Dart SDK already replaced with {self.dart_version}')
            else:
                logger.info(f'Replacing prebuilt dart-sdk with {self.dart_version}...')
                url = f'https://storage.googleapis.com/dart-archive/channels/stable/release/{self.dart_version}/sdk/dartsdk-linux-x64-release.zip'
                with tempfile.TemporaryDirectory() as tmp_dir:
                    zip_path = Path(tmp_dir) / 'dartsdk.zip'
                    urllib.request.urlretrieve(url, zip_path)
                    
                    shutil.rmtree(dart_sdk_dir)
                    with zipfile.ZipFile(zip_path, 'r') as zf:
                        zf.extractall(dart_sdk_dir.parent)
                    for bin_path in (dart_sdk_dir / 'bin').iterdir():
                        if bin_path.is_file():
                            bin_path.chmod(bin_path.stat().st_mode | 0o111)
                
                logger.success(f'Fixed #5: Replaced prebuilt dart-sdk with version {self.dart_version}')

        # 2. Run dart pub get for package_config.json files used by GN actions.
        dart_bin = dart_sdk_dir / 'bin' / 'dart'
        if dart_bin.exists():
            for pub_dir in (dart_dir, engine_checkout_dir):
                if not (pub_dir / 'pubspec.yaml').exists():
                    continue
                logger.info(f'Running dart pub get in {pub_dir} ...')
                subprocess.run([str(dart_bin), 'pub', 'get'], cwd=pub_dir, check=True)
            logger.success('Fixed #5: Finished dart pub get')

    def patch(self, *, file, path):
        repo = git.Repo(path)
        repo.git.apply([file])

    def sysroot(self, arch: str = 'arm64'):
        """Assemble Termux sysroot and apply fixes."""
        self._sysroot(arch=arch)
        
        sysroot_path = Path(self._sysroot.path)
        
        # Fix #3: Remove c++/v1 headers from sysroot (avoid libcxx conflict)
        cxx_dir = sysroot_path / 'usr' / 'include' / 'c++'
        if cxx_dir.is_dir():
            cxx_bak = sysroot_path / 'usr' / 'include' / 'c++.bak'
            if cxx_bak.exists():
                shutil.rmtree(cxx_bak)
            os.rename(cxx_dir, cxx_bak)
            logger.success("Fixed #3: Renamed sysroot c++ headers to c++.bak")

        # Fix #4: Patch glib-typeof.h to wrap <type_traits> with extern "C++"
        glib_typeof = sysroot_path / 'usr' / 'include' / 'glib-2.0' / 'glib' / 'glib-typeof.h'
        if glib_typeof.exists():
            content = glib_typeof.read_text(encoding='utf-8')
            extern_type_traits = 'extern "C++" {\n#include <type_traits>\n}'
            literal_newline_wrapper = r'extern "C++" {\n#include <type_traits>\n}'
            if literal_newline_wrapper in content:
                content = content.replace(literal_newline_wrapper, extern_type_traits)
                glib_typeof.write_text(content, encoding='utf-8')
                logger.success("Fixed #4: Repaired glib-typeof.h extern C++ wrapper newlines")
            elif '<type_traits>' in content and 'extern "C++"' not in content:
                content = content.replace(
                    '#include <type_traits>',
                    extern_type_traits
                )
                glib_typeof.write_text(content, encoding='utf-8')
                logger.success("Fixed #4: Patched glib-typeof.h with extern C++ wrapper")

    def _validate_ndk(self, toolchain=None):
        tc = toolchain or self.toolchain
        if not self.ndk or not tc or not Path(tc).is_dir():
            raise ValueError(
                f"Android NDK path is not set or toolchain path is invalid (ndk='{self.ndk}', toolchain='{tc}'). "
                "Set environment variable NDK_PATH, ANDROID_NDK, ANDROID_NDK_HOME, or ANDROID_NDK_ROOT, "
                "or specify path = '/path/to/ndk' in build.local.toml."
            )

    def configure(
        self,
        arch: str,
        mode: str,
        api: int = 26,
        root: str = None,
        sysroot: str = None,
        toolchain: str = None,
    ):
        self._validate_ndk(toolchain)
        root = root or self.root
        sysroot = os.path.abspath(sysroot or self._sysroot.path)
        toolchain = os.path.abspath(toolchain or self.toolchain)
        cmd = [
            'python3',
            'engine/src/flutter/tools/gn',
            '--linux',
            '--linux-cpu', arch,
            '--enable-fontconfig',
            '--no-goma',
            '--no-backtrace',
            '--clang',
            '--lto',
            '--no-enable-unittests',
            '--no-build-embedder-examples',
            '--no-prebuilt-dart-sdk',
            '--target-toolchain', toolchain,
            '--runtime-mode', mode,
            '--no-build-glfw-shell',
            '--gn-args', 'symbol_level=0',
            '--gn-args', 'use_default_linux_sysroot=false',
            '--gn-args', 'arm_use_neon=false',
            '--gn-args', 'arm_optionally_use_neon=true',
            '--gn-args', 'dart_include_wasm_opt=false',
            '--gn-args', 'dart_platform_sdk=false',
            '--gn-args', 'is_desktop_linux=false',
            '--gn-args', 'use_default_linux_sysroot=false',
            '--gn-args', 'dart_support_perfetto=false',
            '--gn-args', 'skia_use_perfetto=false',
            '--gn-args', f'custom_sysroot="{sysroot}"',
            '--gn-args', 'is_termux=true',
            '--gn-args', f'is_termux_host={utils.__TERMUX__}',
            '--gn-args', f'termux_ndk_path="{toolchain}"',
            # '--gn-args', f'termux_api_level={api}',
        ]
        subprocess.run(cmd, cwd=root, check=True)

    def build(self, arch: str, mode: str, root: str = None, jobs: int = None):
        root = root or self.root
        jobs = jobs or self.jobs
        cmd = [
            'ninja', '-C', utils.target_output(root, arch, mode),
            'flutter',
            # Build libflutter_linux_gtk.so for flutter build linux
            'flutter/shell/platform/linux:flutter_gtk',
            # disable zip_archives
            # 'flutter/build/archives:artifacts',
            # 'flutter/build/archives:dart_sdk_archive',
            # 'flutter/build/archives:flutter_patched_sdk',
            # 'flutter/tools/font_subset',
        ]
        if jobs:
            cmd.append(f'-j{jobs}')
        subprocess.run(cmd, check=True)

    def build_dart(self, arch: str, mode: str, root: str = None, jobs: int = None):
        """Build dart binary for Termux.

        IMPORTANT: `ninja flutter` does NOT compile the dart binary!
        This method compiles the dart binary separately and copies it to dart-sdk/bin/.

        The dart binary is required for flutter build apk to work on Termux.
        """
        root = root or self.root
        jobs = jobs or self.jobs
        out_dir = utils.target_output(root, arch, mode)

        # Build dart binary and dartaotruntime_product
        cmd = [
            'ninja', '-C', out_dir,
            'exe.unstripped/dart',
            'dartaotruntime_product',
        ]
        if jobs:
            cmd.append(f'-j{jobs}')

        logger.info(f'Building dart binary for {arch}...')
        subprocess.run(cmd, check=True)

        def copy_runtime_binary(src, dst, label):
            if not os.path.exists(src):
                logger.warning(f'{label} binary not found at {src}')
                return
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst) and os.path.samefile(src, dst):
                logger.info(f'{label} already available at {dst}')
                return
            shutil.copy(src, dst)
            logger.info(f'{label} binary copied to {dst}')

        # Copy dart to dart-sdk/bin/ and dartvm.
        #
        # Dart 3.10+ Flutter wrappers may re-exec dartvm next to dart. On
        # Termux both entries point at the same JIT-capable VM binary.
        dart_src = os.path.join(out_dir, 'exe.unstripped', 'dart')
        dart_dst = os.path.join(out_dir, 'dart-sdk', 'bin', 'dart')
        dartvm_dst = os.path.join(out_dir, 'dart-sdk', 'bin', 'dartvm')

        copy_runtime_binary(dart_src, dart_dst, 'dart')
        copy_runtime_binary(dart_src, dartvm_dst, 'dartvm')

        # Copy dartaotruntime_product to dart-sdk/bin/dartaotruntime
        aotruntime_src = os.path.join(out_dir, 'dartaotruntime_product')
        aotruntime_dst = os.path.join(out_dir, 'dart-sdk', 'bin', 'dartaotruntime')

        copy_runtime_binary(aotruntime_src, aotruntime_dst, 'dartaotruntime')

    def build_impellerc(self, arch: str, mode: str, root: str = None, jobs: int = None):
        """Build impellerc shader compiler for Termux.

        Required for flutter build apk --release to compile shaders.
        """
        root = root or self.root
        jobs = jobs or self.jobs
        out_dir = utils.target_output(root, arch, mode)

        cmd = [
            'ninja', '-C', out_dir,
            'flutter/impeller/compiler:impellerc',
        ]
        if jobs:
            cmd.append(f'-j{jobs}')

        logger.info(f'Building impellerc for {arch}...')
        subprocess.run(cmd, check=True)

        # Verify impellerc was built
        impellerc_path = os.path.join(out_dir, 'impellerc')
        if os.path.exists(impellerc_path):
            logger.info(f'impellerc built at {impellerc_path}')
        else:
            logger.warning(f'impellerc not found at {impellerc_path}')

    def build_const_finder(self, arch: str, mode: str, root: str = None, jobs: int = None):
        """Build const_finder.dart.snapshot for icon tree shaking.

        Without this, users need --no-tree-shake-icons flag.
        """
        root = root or self.root
        jobs = jobs or self.jobs
        out_dir = utils.target_output(root, arch, mode)

        cmd = [
            'ninja', '-C', out_dir,
            'flutter/tools/const_finder:const_finder',
        ]
        if jobs:
            cmd.append(f'-j{jobs}')

        logger.info(f'Building const_finder for {arch}...')
        subprocess.run(cmd, check=True)

        # Verify and copy to artifacts
        snapshot_src = os.path.join(out_dir, 'gen', 'const_finder.dart.snapshot')
        snapshot_dst = os.path.join(out_dir, 'const_finder.dart.snapshot')

        if os.path.exists(snapshot_src):
            shutil.copy(snapshot_src, snapshot_dst)
            logger.info(f'const_finder.dart.snapshot built at {snapshot_dst}')
        else:
            logger.warning(f'const_finder.dart.snapshot not found at {snapshot_src}')

    def configure_android(
        self,
        arch: str = 'arm64',
        mode: str = 'release',
        root: str = None,
        sysroot: str = None,
        toolchain: str = None,
    ):
        """Configure GN for Android target with Termux cross-host.

        This builds gen_snapshot that:
        - Runs on ARM64 Termux (cross-compiled from x86-64)
        - Produces Android ARM64 AOT code
        """
        self._validate_ndk(toolchain)
        root = root or self.root
        sysroot = os.path.abspath(sysroot or self._sysroot.path)
        toolchain = os.path.abspath(toolchain or self.toolchain)
        toolchain_path = Path(toolchain)
        ndk_root = toolchain_path.parents[3]
        clang_rt_dir = toolchain_path / 'lib' / 'clang'
        clang_rt_versions = [
            p.name for p in clang_rt_dir.iterdir()
            if p.is_dir() and p.name.split('.')[0].isdigit()
        ] if clang_rt_dir.is_dir() else []
        clang_rt_version = max(
            clang_rt_versions,
            key=lambda it: tuple(int(part) for part in it.split('.') if part.isdigit()),
            default='19')

        # Output directory for Android build
        out_dir = f'android_{mode}_{arch}'

        cmd = [
            'python3',
            'engine/src/flutter/tools/gn',
            '--android',
            '--android-cpu', arch,
            '--runtime-mode', mode,
            '--no-goma',
            '--no-backtrace',
            '--clang',
            '--lto',
            '--no-enable-unittests',
            '--no-build-embedder-examples',
            '--no-prebuilt-dart-sdk',
            # Note: no --target-toolchain for Android (uses default)
            # Termux cross-host settings
            '--gn-args', 'termux_cross_host=true',
            '--gn-args', f'android_ndk_root="{ndk_root}"',
            '--gn-args', f'android_clang_rt_version="{clang_rt_version}"',
            '--gn-args', f'termux_ndk_path="{toolchain}"',
            '--gn-args', f'target_sysroot="{sysroot}"',
            '--gn-args', 'symbol_level=0',
            '--gn-args', 'use_default_linux_sysroot=false',
        ]
        logger.info(f'Configuring Android gen_snapshot build: {out_dir}')
        subprocess.run(cmd, cwd=root, check=True)
        return out_dir

    def build_android_gen_snapshot(
        self,
        arch: str = 'arm64',
        mode: str = 'release',
        root: str = None,
        jobs: int = None,
    ):
        """Build gen_snapshot for Android target.

        This produces gen_snapshot that can be run on Termux
        and generates Android ARM64 AOT code.
        """
        root = root or self.root
        jobs = jobs or self.jobs
        out_dir = f'android_{mode}_{arch}'
        out_path = os.path.join(root, 'engine', 'src', 'out', out_dir)

        cmd = [
            'ninja', '-C', out_path,
            'flutter/third_party/dart/runtime/bin:gen_snapshot',
        ]
        if jobs:
            cmd.append(f'-j{jobs}')

        logger.info(f'Building Android gen_snapshot: {out_dir}')
        subprocess.run(cmd, check=True)

        # Find and copy gen_snapshot to the location expected by package.yaml
        # package.yaml expects: android_release_arm64/clang_arm64/gen_snapshot
        possible_paths = [
            os.path.join(out_path, 'exe.stripped', 'gen_snapshot'),
            os.path.join(out_path, 'gen_snapshot'),
            os.path.join(out_path, 'clang_x64', 'exe.stripped', 'gen_snapshot'),
            os.path.join(out_path, 'clang_x64', 'gen_snapshot'),
        ]

        gen_snapshot_src = None
        for path in possible_paths:
            if os.path.exists(path):
                gen_snapshot_src = path
                break

        if gen_snapshot_src:
            # Copy to the location expected by package.yaml
            target_dir = os.path.join(out_path, 'clang_arm64')
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, 'gen_snapshot')
            shutil.copy(gen_snapshot_src, target_path)
            logger.info(f'✓ gen_snapshot copied to {target_path}')
            return target_path

        logger.warning('gen_snapshot not found at expected paths')
        return None

    def sync_wsl(self):
        """Sync files from Windows to WSL before debuild.

        This prevents the common issue of editing files on Windows
        but building in WSL with stale copies.
        """
        import platform
        import posixpath

        if not self.sync_cfg:
            logger.debug('No sync config, skipping')
            return

        windows_root = self.sync_cfg.get('windows_root')
        wsl_root = self.sync_cfg.get('wsl_root')
        paths = self.sync_cfg.get('paths', [])

        if not windows_root or not wsl_root:
            logger.warning('sync config incomplete, skipping')
            return

        # Convert Windows path to WSL mount path
        wsl_mount = '/mnt/' + windows_root[0].lower() + windows_root[2:].replace('\\', '/')

        # Detect if running in WSL (Linux) or Windows
        is_wsl = platform.system() == 'Linux'

        for p in paths:
            src = f"{wsl_mount}/{p}"
            dst = f"{wsl_root}/{p}"
            # Ensure dst parent directory exists
            dst_dir = posixpath.dirname(dst)
            if is_wsl:
                subprocess.run(['bash', '-c', f'mkdir -p "{dst_dir}"'], check=False)
            else:
                subprocess.run(['wsl', '-e', 'bash', '-c', f'mkdir -p "{dst_dir}"'], check=False)
                
            if '.' in p.split('/')[-1] and not src.endswith('/'):
                 # It's a file
                 cmd = f"cp -a {src} {dst}"
            else:
                 # It's a directory
                 cmd = f"cp -a {src}/. {dst}/"
            logger.info(f'Syncing: {p}')
            if is_wsl:
                # Running in WSL, execute directly
                subprocess.run(['bash', '-c', cmd], check=False)
            else:
                # Running in Windows, use wsl command
                subprocess.run(['wsl', '-e', 'bash', '-c', cmd], check=False)

        logger.success('Sync completed')

    def debuild(self, arch: str, output: str = None, root: str = None, **conf):
        # Sync files from Windows to WSL before building
        self.sync_wsl()

        conf = conf or self.package
        # root is Flutter SDK root (flutter/), set from [flutter].path in build.toml
        root = root or self.root
        output = output or self.output(arch)

        pkg = Package(root=root, arch=arch, **conf)
        pkg.debuild(output=output)
        validate_deb_artifacts(output)

    def output(self, arch: str):
        if self.release.is_dir():
            name = f'flutter_{self.tag}_{utils.termux_arch(arch)}.deb'
            return self.release/name
        else:
            return self.release

    def build_all(self, arch: str = 'arm64', jobs: int = None):
        """One-command build for complete Flutter Termux package.

        This builds everything needed for both:
        - flutter run -d linux (Linux target)
        - flutter build apk --release --target-platform android-arm64

        Note: Only android-arm64 gen_snapshot is built. Users must use
        --target-platform android-arm64 when building APKs.

        Technical limitation analysis (2025-12-28):
        ============================================
        We tested compiling gen_snapshot for android-arm and android-x64:

        1. android-arm64: ✅ Works
           - Host=ARM64, Target=ARM64, same architecture

        2. android-arm (32-bit): ❌ Fails
           - BoringSSL has shift overflow errors (e.g., `r0 << 63` on 32-bit type)
           - The GN build system compiles host tool dependencies for target arch
           - Would require extensive patches to BoringSSL and build system

        3. android-x64: ❌ Fails
           - ARM64 sysroot headers incompatible with x64 compilation
           - Cross-architecture compilation fundamentally not supported

        Root cause: Flutter Engine's GN build system assumes host and target
        are compatible architectures. It doesn't properly separate host toolchain
        (ARM64) from target compilation (ARM32/x64).

        Usage:
            python3 build.py build_all --arch=arm64
        """
        logger.info('=== Starting complete Flutter Termux build ===')

        # Step 1: Build Linux debug (for flutter run -d linux --debug)
        logger.info('[1/12] Configuring Linux debug...')
        self.configure(arch=arch, mode='debug')

        logger.info('[2/12] Building Flutter engine + dart...')
        self.build(arch=arch, mode='debug', jobs=jobs)
        self.build_dart(arch=arch, mode='debug', jobs=jobs)

        # Step 3: Build impellerc (for shader compilation)
        logger.info('[3/12] Building impellerc...')
        self.build_impellerc(arch=arch, mode='debug', jobs=jobs)

        # Step 4: Build const_finder (for icon tree shaking)
        logger.info('[4/12] Building const_finder...')
        self.build_const_finder(arch=arch, mode='debug', jobs=jobs)

        # Step 5: Build Linux release (for flutter build linux)
        logger.info('[5/12] Configuring Linux release...')
        self.configure(arch=arch, mode='release')

        logger.info('[6/12] Building Flutter engine (release)...')
        self.build(arch=arch, mode='release', jobs=jobs)

        # Step 7: Build Linux profile (for flutter run -d linux --profile)
        logger.info('[7/12] Configuring Linux profile...')
        self.configure(arch=arch, mode='profile')

        logger.info('[8/12] Building Flutter engine (profile)...')
        self.build(arch=arch, mode='profile', jobs=jobs)

        # Step 9: Build Android gen_snapshot (only arm64 supported)
        # Due to Dart VM cross-compilation limitations, we can only build
        # gen_snapshot for android-arm64. android-arm and android-x64 require
        # patching the Dart VM signal handler code.
        logger.info('[9/12] Building Android gen_snapshot release (arm64 only)...')
        self.configure_android(arch='arm64', mode='release')
        self.build_android_gen_snapshot(arch='arm64', mode='release', jobs=jobs)

        # Step 10: Build Android gen_snapshot profile mode
        logger.info('[10/12] Building Android gen_snapshot profile (arm64 only)...')
        self.configure_android(arch='arm64', mode='profile')
        self.build_android_gen_snapshot(arch='arm64', mode='profile', jobs=jobs)

        # Step 11: Package deb
        logger.info('[11/12] Packaging deb...')
        self.debuild(arch=arch, output=self.output(arch))

        logger.info('[12/12] Build complete!')
        logger.info(f'Output: {self.output(arch)}')
        logger.info('Note: Users must use --target-platform android-arm64 when building APKs')

    # TODO: check gclient and ninja existence
    def __call__(self):
        self.config()
        self.clone()
        self.sync()

        for arch in self.arch:
            self.sysroot(arch=arch)
            for mode in self.mode:
                self.configure(arch=arch, mode=mode)
                self.build(arch=arch, mode=mode)
            self.debuild(arch=arch, output=self.output(arch))


if __name__ == '__main__':
    logger.remove()
    logger.add(
        sys.stdout,
        diagnose=False,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <9}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>")
        )
    fire.Fire(Build())
