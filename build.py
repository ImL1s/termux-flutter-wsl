#!/usr/bin/env python3

import os
import re
import sys
import io
import git
import fire
import yaml
import time
import json
import utils
import shutil
import tarfile
import tomllib
import platform
import posixpath
import subprocess
from loguru import logger
from pathlib import Path
from sysroot import Sysroot
from package import Package


def windows_to_wsl_path(win_path: str) -> str:
    """Convert Windows path (e.g. C:\\foo\\bar) to WSL mount path (/mnt/c/foo/bar)."""
    if not win_path:
        return win_path

    if platform.system() == 'Linux':
        try:
            res = subprocess.run(
                ['wslpath', '-u', str(win_path)],
                capture_output=True,
                text=True,
                check=False
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except FileNotFoundError:
            pass

    clean_path = str(win_path).replace('\\', '/')
    match = re.match(r'^([a-zA-Z]):[/\\]?(.*)', clean_path)
    if match:
        drive = match.group(1).lower()
        rest = match.group(2)
        return f'/mnt/{drive}/{rest}' if rest else f'/mnt/{drive}'

    if clean_path.startswith('/mnt/'):
        return clean_path

    return clean_path


def wsl_to_windows_path(wsl_path: str) -> str:
    """Convert WSL path (e.g. /mnt/c/foo/bar) to Windows path (C:\\foo\\bar)."""
    if not wsl_path:
        return wsl_path

    if platform.system() == 'Linux':
        try:
            res = subprocess.run(
                ['wslpath', '-w', str(wsl_path)],
                capture_output=True,
                text=True,
                check=False
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except FileNotFoundError:
            pass

    clean_path = str(wsl_path).replace('\\', '/')
    match = re.match(r'^/mnt/([a-zA-Z])(?:/(.*))?$', clean_path)
    if match:
        drive = match.group(1).upper()
        rest = match.group(2) or ''
        win_rest = rest.replace('/', '\\')
        return f'{drive}:\\{win_rest}' if win_rest else f'{drive}:\\'

    if re.match(r'^[a-zA-Z]:', clean_path):
        return str(wsl_path).replace('/', '\\')

    return clean_path


def validate_wsl_mount(path: str) -> None:
    """Validate WSL mount point configuration and existence.

    Raises ValueError with a clear error message on unsupported mount configurations.
    """
    clean_path = str(path).replace('\\', '/')
    if clean_path.startswith('/mnt/'):
        parts = clean_path.split('/')
        if len(parts) < 3 or not parts[2] or len(parts[2]) != 1 or not parts[2].isalpha():
            raise ValueError(
                f"Unsupported WSL mount configuration for path: '{path}'. "
                f"WSL drive mounts must follow /mnt/<drive_letter>/ format (e.g. /mnt/c, /mnt/d)."
            )
        mount_point = f"/mnt/{parts[2]}"
        if platform.system() == 'Linux' and not os.path.exists(mount_point):
            raise ValueError(
                f"WSL mount directory '{mount_point}' does not exist or is not mounted. "
                f"Check your WSL automount configuration."
            )


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
            or ('/opt/android-ndk-r27d' if os.path.exists('/opt/android-ndk-r27d') else None)
        )

        api = cfg.get('ndk', {}).get('api', 35)
        tag = cfg.get('flutter', {}).get('tag')
        release_tag = cfg.get('flutter', {}).get('release_tag', f'v{tag}-termux' if tag else None)
        dart_version = cfg.get('flutter', {}).get('dart_version', '3.12.1')
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
        
        gclient_path = shutil.which('gclient')
        if not gclient_path:
            candidate_dirs = [
                Path(__file__).parent / 'depot_tools',
                Path.home() / 'depot_tools',
                Path('/opt/depot_tools'),
            ]
            runner_temp = os.environ.get('RUNNER_TEMP')
            if runner_temp:
                candidate_dirs.append(Path(runner_temp) / 'depot_tools')
            for cand in candidate_dirs:
                if (cand / 'gclient').exists():
                    os.environ["PATH"] = f"{cand}:{os.environ.get('PATH', '')}"
                    gclient_path = str(cand / 'gclient')
                    break
        
        if not gclient_path:
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

    def workspace_status(self, path: str = None) -> dict:
        """Return status of the flutter workspace."""
        path = path or self.root
        if not os.path.exists(path):
            return {'exists': False}

        try:
            repo = git.Repo(path)

            git_dir = Path(repo.git_dir)
            in_progress = any((git_dir / flag).exists() for flag in (
                'rebase-apply', 'rebase-merge', 'MERGE_HEAD',
                'BISECT_LOG', 'CHERRY_PICK_HEAD', 'REVERT_HEAD'
            ))
            if in_progress:
                return {'exists': True, 'dirty': True, 'error': 'In-progress git operation detected'}

            if 'origin' not in repo.remotes:
                return {'exists': True, 'dirty': True, 'error': 'Missing origin remote'}

            origin_url = repo.remotes.origin.url
            if not origin_url:
                return {'exists': True, 'dirty': True, 'error': 'Empty origin remote URL'}

            is_dirty = repo.is_dirty(untracked_files=True)
            try:
                active_branch = repo.active_branch.name
            except TypeError:
                active_branch = None

            head_sha = repo.head.commit.hexsha
            peeled_sha = None
            tag = self.tag
            if tag:
                try:
                    peeled_sha = repo.git.rev_parse(f'refs/tags/{tag}^{{commit}}').strip()
                except Exception:
                    try:
                        peeled_sha = repo.git.rev_list('-n', '1', tag).strip()
                    except Exception:
                        pass

            return {
                'exists': True,
                'dirty': is_dirty,
                'tag': utils.flutter_tag(str(path)),
                'branch': active_branch,
                'head': head_sha,
                'peeled_sha': peeled_sha,
                'remote': origin_url,
            }
        except Exception as e:
            return {'exists': True, 'dirty': False, 'tag': utils.flutter_tag(str(path)), 'error': str(e)}

    def classify_workspace_patch_state(self, path: str = None) -> dict:
        """
        Fail-closed patch-state classifier for a repository at `path`.
        Determines exact tracked diff against configured peeled tag commit.
        Requires every configured patch to classify as preimage or exact postimage.
        Rejects extra tracked, staged, or untracked changes.
        """
        import hashlib
        path_obj = Path(path or self.root).resolve()
        if not path_obj.exists():
            return {'valid': False, 'state': 'invalid', 'reason': 'Path does not exist', 'patch_digest': ''}

        try:
            repo = git.Repo(path_obj)
        except Exception as e:
            return {'valid': False, 'state': 'invalid', 'reason': f'Not a git repo: {e}', 'patch_digest': ''}

        relevant_patches = []
        if hasattr(self, 'patches') and isinstance(self.patches, dict):
            for k, v in self.patches.items():
                if isinstance(v, dict) and 'file' in v and 'path' in v:
                    patch_file = Path(v['file']).resolve()
                    patch_target = Path(v['path']).resolve()
                    if patch_target == path_obj or path_obj in patch_target.parents:
                        relevant_patches.append((k, patch_file, patch_target))

        hasher = hashlib.sha256()
        for k, p_file, _ in sorted(relevant_patches, key=lambda x: str(x[1])):
            if p_file.exists():
                hasher.update(p_file.read_bytes())
        patch_digest = hasher.hexdigest()

        applied_patches = []
        unapplied_patches = []

        for k, p_file, p_target in relevant_patches:
            if not p_file.exists():
                return {
                    'valid': False,
                    'state': 'invalid',
                    'reason': f'Patch file {p_file} missing',
                    'patch_digest': patch_digest
                }

            if not p_target.exists():
                unapplied_patches.append((k, p_file, p_target))
                continue

            try:
                target_repo = git.Repo(p_target, search_parent_directories=True) if p_target != path_obj else repo
            except Exception as e:
                return {
                    'valid': False,
                    'state': 'invalid',
                    'reason': f'Not a git repo at patch target {p_target}: {e}',
                    'patch_digest': patch_digest
                }

            is_postimage = False
            try:
                target_repo.git.apply(['--reverse', '--check', str(p_file)])
                is_postimage = True
            except git.GitCommandError:
                pass

            is_preimage = False
            try:
                target_repo.git.apply(['--check', str(p_file)])
                is_preimage = True
            except git.GitCommandError:
                pass

            if is_postimage and not is_preimage:
                applied_patches.append((k, p_file, p_target, target_repo))
            elif is_preimage and not is_postimage:
                unapplied_patches.append((k, p_file, p_target))
            elif is_preimage and is_postimage:
                unapplied_patches.append((k, p_file, p_target))
            else:
                return {
                    'valid': False,
                    'state': 'invalid',
                    'reason': f'Patch {k} ({p_file.name}) is in unknown/partial state',
                    'patch_digest': patch_digest
                }

        all_repos = {repo}
        for _, _, p_target in relevant_patches:
            if p_target.exists():
                try:
                    all_repos.add(git.Repo(p_target, search_parent_directories=True))
                except Exception:
                    pass

        def _is_repo_dirty(r: git.Repo) -> bool:
            if r.is_dirty(untracked_files=False):
                return True
            ignored_prefixes = ('.gclient', '.gclient_sync', 'build/config/termux', 'build/toolchain/termux')
            ignored_suffixes = ('.receipt.json',)
            untracked = [
                f for f in r.untracked_files
                if not (f.startswith(ignored_prefixes) or f.endswith(ignored_suffixes))
            ]
            return len(untracked) > 0

        if not applied_patches:
            dirty_repo = next((r for r in all_repos if _is_repo_dirty(r)), None)
            if dirty_repo:
                return {
                    'valid': False,
                    'state': 'invalid',
                    'reason': f'Repo {dirty_repo.working_dir} is dirty but no configured patches are applied',
                    'patch_digest': patch_digest
                }
            return {
                'valid': True,
                'state': 'clean',
                'reason': 'Repo is clean (preimage state)',
                'applied_patches': [],
                'unapplied_patches': [k for k, _, _ in unapplied_patches],
                'patch_digest': patch_digest
            }

        reversed_successfully = []
        try:
            for k, p_file, p_target, target_repo in reversed(applied_patches):
                target_repo.git.apply(['--reverse', str(p_file)])
                reversed_successfully.append((k, p_file, p_target, target_repo))

            dirty_repo = next((r for r in all_repos if _is_repo_dirty(r)), None)
            if dirty_repo:
                return {
                    'valid': False,
                    'state': 'invalid',
                    'reason': f'Repo {dirty_repo.working_dir} contains extra modifications beyond configured applied patches',
                    'patch_digest': patch_digest
                }
            return {
                'valid': True,
                'state': 'patched',
                'reason': 'Repo contains exactly the configured applied patches',
                'applied_patches': [k for k, _, _ in [item[:3] for item in applied_patches]],
                'unapplied_patches': [k for k, _, _ in unapplied_patches],
                'patch_digest': patch_digest
            }
        except Exception as e:
            return {
                'valid': False,
                'state': 'invalid',
                'reason': f'Failed during patch classification reversal check: {e}',
                'patch_digest': patch_digest
            }
        finally:
            for k, p_file, p_target, target_repo in reversed(reversed_successfully):
                try:
                    target_repo.git.apply([str(p_file)])
                except Exception as restore_err:
                    logger.error(f'Failed to re-apply patch {k} during restoration: {restore_err}')

    def clone(self, *, url: str = None, tag: str = None, out: str = None, force: bool = False):
        url = url or self.repo
        out_path = Path(out or self.root)
        tag = tag or self.tag
        progress = GitProgress()

        if out_path.is_dir():
            status = self.workspace_status(str(out_path))

            def urls_match(u1, u2):
                if not u1 or not u2:
                    return False
                return utils.canonicalize_git_url(u1) == utils.canonicalize_git_url(u2)

            remote_ok = urls_match(status.get('remote'), url)
            has_structure = (out_path / 'bin' / 'flutter').exists()
            head_matches_peeled = (
                status.get('peeled_sha') is not None
                and status.get('head') == status.get('peeled_sha')
            )

            patch_status = self.classify_workspace_patch_state(str(out_path))

            if (
                status.get('exists')
                and status.get('tag') == tag
                and 'error' not in status
                and remote_ok
                and has_structure
                and head_matches_peeled
                and patch_status.get('valid')
            ):
                logger.info(f'flutter exists at {out_path} with valid tag {tag} (HEAD={status.get("head")[:8]}, patch_state={patch_status.get("state")}), skipping clone.')
                evidence_file = out_path.parent / 'build_evidence.json'
                try:
                    ev_data = {}
                    if evidence_file.exists():
                        ev_data = json.loads(evidence_file.read_text(encoding='utf-8'))
                    ev_data['accepted_patch_set_digest'] = patch_status.get('patch_digest', '')
                    ev_data['patch_state'] = patch_status.get('state', '')
                    evidence_file.write_text(json.dumps(ev_data, indent=2), encoding='utf-8')
                except Exception as e:
                    logger.warning(f'Failed to record patch evidence: {e}')
                return

            if not patch_status.get('valid') and not force:
                logger.error(f'Checkout at {out_path} fails patch state classification: {patch_status.get("reason")}. Use --force to override.')
                raise RuntimeError(f'Dirty checkout at {out_path}: {patch_status.get("reason")}')

            current_tag = status.get('tag')
            if 'error' not in status and remote_ok:
                try:
                    repo = git.Repo(out_path)
                    logger.info(f'Existing flutter checkout HEAD ({status.get("head", "")[:8]}) does not match tag {tag} peeled commit ({status.get("peeled_sha", "")[:8]}). Attempting git checkout {tag}...')
                    repo.git.fetch('origin', '--tags')
                    repo.git.checkout(tag)
                    new_status = self.workspace_status(str(out_path))
                    if (
                        new_status.get('tag') == tag
                        and not new_status.get('dirty')
                        and new_status.get('head') == new_status.get('peeled_sha')
                    ):
                        logger.success(f'Successfully checked out tag {tag} in {out_path}.')
                        return
                except Exception as e:
                    logger.warning(f'Failed to checkout tag {tag} in existing directory {out_path}: {e}')

        staging_path = out_path.parent / f'{out_path.name}.staging'
        if staging_path.exists():
            shutil.rmtree(staging_path)

        logger.info(f'Cloning flutter {tag} from {url} to {staging_path}...')
        try:
            git.Repo.clone_from(
                url=url,
                to_path=str(staging_path),
                progress=progress,
                branch=tag)
        except git.exc.GitCommandError as e:
            if staging_path.exists():
                shutil.rmtree(staging_path)
            raise RuntimeError(f'Failed to clone flutter repo:\n' + '\n'.join(progress.error_lines)) from e

        if utils.flutter_tag(str(staging_path)) != tag:
            if staging_path.exists():
                shutil.rmtree(staging_path)
            raise RuntimeError(f'Staging checkout does not match tag {tag}')

        if out_path.is_dir():
            import time
            timestamp = int(time.time())
            backup_path = out_path.parent / f'{out_path.name}.backup.{timestamp}'
            logger.info(f'Moving existing directory {out_path} to {backup_path}...')
            os.rename(out_path, backup_path)

        logger.info(f'Moving staging directory {staging_path} to {out_path}...')
        os.rename(staging_path, out_path)
        logger.success(f'Successfully cloned flutter {tag} to {out_path}')

    def _sync_receipt_path(self, root: str = None) -> Path:
        src = Path(root or self.root)
        return src / '.gclient_sync.receipt.json'

    def is_sync_complete(self, root: str = None, cfg: str = None) -> bool:
        src = Path(root or self.root)
        cfg_path = Path(cfg or self.gclient)
        receipt_path = self._sync_receipt_path(src)

        if not receipt_path.exists():
            return False

        try:
            data = json.loads(receipt_path.read_text(encoding='utf-8'))
            if not data.get('completed', False):
                return False

            # Required checkout roots
            engine_src = src / 'engine' / 'src'
            if not (engine_src.exists() and (engine_src / 'flutter').exists() and (engine_src / 'third_party').exists()):
                return False

            # Bound to Flutter HEAD
            cur_flutter_head = utils.flutter_tag(str(src))
            if data.get('flutter_head') != cur_flutter_head:
                return False

            # Bound to gclient config SHA-256
            if cfg_path.exists():
                import hashlib
                cfg_sha = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
                if data.get('gclient_sha256') != cfg_sha:
                    return False

            return True
        except Exception:
            return False

    def sync(self, *, cfg: str = None, root: str = None):
        cfg = cfg or self.gclient
        src = root or self.root
        src_path = Path(src)

        receipt_path = self._sync_receipt_path(src_path)
        if receipt_path.exists():
            try:
                receipt_path.unlink()
            except Exception:
                pass

        cfg_path = Path(cfg)
        if not cfg_path.exists():
            default_gclient = '''solutions = [
  {
    "managed": False,
    "name": ".",
    "url": "https://github.com/flutter/flutter",
    "deps_file": "DEPS",
    "safesync_url": "",
    "custom_deps": {
      "engine/src/fuchsia/sdk/linux": None,
      "engine/src/third_party/google_fonts_for_unit_tests": None,
      "engine/src/flutter/third_party/java/openjdk": None,
    },
    "custom_vars" : {
      "setup_githooks" : False,
      "use_cipd_goma" : False,
      "download_emsdk" : False,
      "download_dart_sdk" : False,
      "download_linux_deps" : False,
      "download_fuchsia_sdk" : False,
      "download_android_deps" : False,
      "download_windows_deps" : False,
      "download_fuchsia_deps" : False,
    },
    "custom_hooks" : []
  }
]
'''
            cfg_path.write_text(default_gclient, encoding='utf-8')

        shutil.copy(cfg_path, os.path.join(src, '.gclient'))
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
                sha256_url = f'{url}.sha256sum'
                with tempfile.TemporaryDirectory() as tmp_dir:
                    zip_path = Path(tmp_dir) / 'dartsdk.zip'

                    import urllib.request
                    # Fetch expected checksum
                    try:
                        with urllib.request.urlopen(sha256_url) as response:
                            expected_sha256 = response.read().decode('utf-8').split()[0].strip()
                    except Exception as e:
                        raise RuntimeError(f'Failed to fetch dart-sdk checksum: {e}')

                    urllib.request.urlretrieve(url, zip_path)

                    import hashlib
                    sha256 = hashlib.sha256()
                    with open(zip_path, 'rb') as f:
                        for chunk in iter(lambda: f.read(8192), b''):
                            sha256.update(chunk)
                    if sha256.hexdigest() != expected_sha256:
                        raise RuntimeError(f'SHA256 mismatch for dart-sdk: expected {expected_sha256}, got {sha256.hexdigest()}')

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

        import hashlib
        cfg_path = Path(cfg)
        cfg_sha = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.exists() else ''
        receipt_data = {
            'flutter_head': utils.flutter_tag(str(src)),
            'gclient_sha256': cfg_sha,
            'timestamp': int(time.time()),
            'completed': True
        }
        receipt_path.write_text(json.dumps(receipt_data, indent=2), encoding='utf-8')
        logger.success('Sync receipt saved successfully.')

    def patch(self, *, file, path):
        repo = git.Repo(path)
        # Classify patch state: {postimage, preimage, unknown}
        # 1. Check if patch is already applied (reverse succeeds)
        try:
            repo.git.apply(['--reverse', '--check', file])
            logger.info(f'  Patch {Path(file).name} already applied (postimage), skipping.')
            return
        except git.GitCommandError:
            pass  # Not in postimage state

        # 2. Check if patch can be applied cleanly (preimage)
        try:
            repo.git.apply(['--check', file])
        except git.GitCommandError as e:
            raise RuntimeError(
                f'Patch {Path(file).name} cannot be applied and is not already applied. '
                f'Source tree is in unknown state. Error: {e}'
            )

        # 3. Apply the patch
        repo.git.apply([file])

    def sysroot(self, arch: str = 'arm64', locked: bool = True):
        """Assemble Termux sysroot and apply fixes."""
        self._sysroot(arch=arch, locked=locked)
        from sysroot import _apply_sysroot_transformations
        _apply_sysroot_transformations(self._sysroot.path)

    def sysroot_lock(self, arch: str = 'arm64'):
        """Generate or refresh sysroot.lock.json."""
        self._sysroot.lock(arch=arch)

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

        # Build dart binary, dartvm, and dartaotruntime_product
        cmd = [
            'ninja', '-C', out_dir,
            'exe.unstripped/dart',
            'exe.unstripped/dartvm',
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

        # Copy dart and dartvm to dart-sdk/bin/.
        #
        # Dart 3.10+ Flutter wrappers re-exec dartvm next to dart.
        # dart_src is the CLI frontend driver; dartvm_src is the actual VM engine.
        dart_src = os.path.join(out_dir, 'exe.unstripped', 'dart')
        dartvm_src = os.path.join(out_dir, 'exe.unstripped', 'dartvm')
        if not os.path.exists(dartvm_src):
            dartvm_src = os.path.join(out_dir, 'dartvm')
        dart_dst = os.path.join(out_dir, 'dart-sdk', 'bin', 'dart')
        dartvm_dst = os.path.join(out_dir, 'dart-sdk', 'bin', 'dartvm')

        copy_runtime_binary(dart_src, dart_dst, 'dart')
        copy_runtime_binary(dartvm_src, dartvm_dst, 'dartvm')

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
        if not self.sync_cfg:
            logger.debug('No sync config, skipping')
            return

        windows_root = self.sync_cfg.get('windows_root')
        wsl_root = self.sync_cfg.get('wsl_root')
        paths = self.sync_cfg.get('paths', [])

        if not windows_root or not wsl_root:
            logger.warning('sync config incomplete, skipping')
            return

        # Convert Windows path to WSL mount path using windows_to_wsl_path and validate
        wsl_mount = windows_to_wsl_path(windows_root)
        validate_wsl_mount(wsl_mount)

        # Detect if running in WSL (Linux) or Windows
        is_wsl = platform.system() == 'Linux'

        if is_wsl:
            if not os.path.exists(wsl_mount):
                raise RuntimeError(f"Sync source directory {wsl_mount} does not exist in WSL.")
        else:
            if not os.path.exists(windows_root):
                raise RuntimeError(f"Sync source directory {windows_root} does not exist.")

        for p in paths:
            src = f"{wsl_mount}/{p}"
            dst = f"{wsl_root}/{p}"
            # Ensure dst parent directory exists
            dst_dir = posixpath.dirname(dst)
            if is_wsl:
                subprocess.run(['bash', '-c', f'mkdir -p "{dst_dir}"'], check=True)
            else:
                subprocess.run(['wsl', '-e', 'bash', '-c', f'mkdir -p "{dst_dir}"'], check=True)

            # Fix Issue #30: proper filesystem directory check instead of dot in filename heuristic
            src_check = src if is_wsl else os.path.join(windows_root, p.replace('/', '\\'))
            if os.path.isdir(src_check):
                cmd = f"rsync -a --delete '{src}/' '{dst}/'"
            else:
                cmd = f"rsync -a '{src}' '{dst}'"

            logger.info(f'Syncing: {p}')
            if is_wsl:
                # Running in WSL, execute directly
                subprocess.run(['bash', '-c', cmd], check=True)
            else:
                # Running in Windows, use wsl command
                subprocess.run(['wsl', '-e', 'bash', '-c', cmd], check=True)

        logger.success('Sync completed')

    def debuild(self, arch: str, output: str = None, root: str = None, **conf):
        # Sync files from Windows to WSL before building
        self.sync_wsl()

        conf = conf or self.package
        # root is Flutter SDK root (flutter/), set from [flutter].path in build.toml
        root = root or self.root
        output = output or self.output(arch)

        pkg = Package(root=root, arch=arch, tag=self.tag, release_tag=self.release_tag, **conf)
        pkg.debuild(output=output)
        validate_deb_artifacts(output)

    def output(self, arch: str):
        if self.release.is_dir():
            name = f'flutter_{self.tag}_{utils.termux_arch(arch)}.deb'
            return self.release/name
        else:
            return self.release

    def build_all(self, arch: str = 'arm64', jobs: int = None, force: bool = False):
        """One-command build for complete Flutter Termux package.

        This builds everything needed for both:
        - flutter run -d linux (Linux target)
        - flutter build apk --release --target-platform android-arm64

        Note: Only android-arm64 gen_snapshot is built. Users must use
        --target-platform android-arm64 when building APKs.

        Usage:
            python3 build.py build_all --arch=arm64 [--force]
        """
        import time
        start_time = time.time()
        logger.info('=== Starting complete Flutter Termux build ===')

        rebuilt_any_artifact = [False]

        def run_step(step, total, name, func, **kwargs):
            logger.info(f'[{step}/{total}] {name}...')
            t0 = time.time()
            func(**kwargs)
            logger.info(f'✓ {name} completed in {time.time() - t0:.1f}s')

        def run_step_conditional(step, total, name, outputs, func, **kwargs):
            if not force and outputs:
                all_exist = True
                for out_item in outputs:
                    if not Path(out_item).exists():
                        all_exist = False
                        break
                if all_exist:
                    logger.info(f'[{step}/{total}] {name} output already exists, skipping (use --force to rebuild).')
                    return
            rebuilt_any_artifact[0] = True
            run_step(step, total, name, func, **kwargs)

        total = 14

        # Step 1: preflight
        logger.info(f'[1/{total}] preflight...')
        t0 = time.time()
        if not self.preflight():
            raise RuntimeError("Preflight checks failed")
        logger.info(f'✓ preflight completed in {time.time() - t0:.1f}s')

        # Step 2: clone
        run_step(2, total, 'clone', self.clone, force=force)

        # Step 3: sync
        if force or not self.is_sync_complete():
            rebuilt_any_artifact[0] = True
            run_step(3, total, 'sync', self.sync)
        else:
            logger.info(f'[3/{total}] sync output already complete (receipt verified), skipping.')

        # Step 4: patch (uses reverse-check classification)
        logger.info(f'[4/{total}] patch...')
        t0 = time.time()
        if hasattr(self, 'patches') and isinstance(self.patches, dict):
            for k in self.patches:
                logger.info(f'  -> Patching {k}')
                getattr(self, f'patch_{k}')()
        logger.info(f'✓ patch completed in {time.time() - t0:.1f}s')

        # Step 5: sysroot (must run locked verification before skipping)
        usr_dir = Path(self._sysroot.path) / 'usr'
        sysroot_valid = False
        if not force and usr_dir.is_dir():
            try:
                sysroot_valid = self._sysroot.verify(arch=arch)
            except Exception as e:
                logger.info(f"Sysroot verification failed: {e}. Rebuilding sysroot...")
                sysroot_valid = False

        if not force and sysroot_valid:
            logger.info(f'[5/{total}] sysroot verified with lock file, skipping (use --force to rebuild).')
        else:
            rebuilt_any_artifact[0] = True
            run_step(5, total, 'sysroot', self.sysroot, arch=arch)

        # Step 6: configure and build debug + dart + impellerc + const_finder
        out_debug = utils.target_output(str(self.root), arch, 'debug')
        debug_outputs = [
            Path(out_debug) / 'libflutter_linux_gtk.so',
            Path(out_debug) / 'dart-sdk/bin/dart',
            Path(out_debug) / 'dart-sdk/bin/dartvm',
            Path(out_debug) / 'impellerc',
            Path(out_debug) / 'gen/const_finder.dart.snapshot',
            Path(out_debug) / 'gen/dart-pkg/sky_engine',
        ]
        if not force and all(p.exists() for p in debug_outputs):
            logger.info(f'[6/{total}] debug tools output already exists, skipping (use --force to rebuild).')
        else:
            rebuilt_any_artifact[0] = True
            logger.info(f'[6/{total}] configure and build debug tools...')
            t0 = time.time()
            self.configure(arch=arch, mode='debug')
            self.build(arch=arch, mode='debug', jobs=jobs)
            self.build_dart(arch=arch, mode='debug', jobs=jobs)
            self.build_impellerc(arch=arch, mode='debug', jobs=jobs)
            self.build_const_finder(arch=arch, mode='debug', jobs=jobs)
            logger.info(f'✓ debug tools completed in {time.time() - t0:.1f}s')

        # Step 7: configure release
        out_release = utils.target_output(str(self.root), arch, 'release')
        release_outputs = [
            Path(out_release) / 'libflutter_linux_gtk.so',
            Path(out_release) / 'gen_snapshot',
            Path(out_release) / 'dartdev_aot.dart.snapshot',
        ]
        if not force and all(p.exists() for p in release_outputs):
            logger.info(f'[7/{total}] configure release skipped (output exists).')
        else:
            run_step(7, total, 'configure release', self.configure, arch=arch, mode='release')

        # Step 8: build release
        if not force and all(p.exists() for p in release_outputs):
            logger.info(f'[8/{total}] build release output already exists, skipping (use --force to rebuild).')
        else:
            rebuilt_any_artifact[0] = True
            run_step(8, total, 'build release', self.build, arch=arch, mode='release', jobs=jobs)

        # Step 9: configure profile
        out_profile = utils.target_output(str(self.root), arch, 'profile')
        profile_outputs = [
            Path(out_profile) / 'libflutter_linux_gtk.so',
            Path(out_profile) / 'gen_snapshot',
        ]
        if not force and all(p.exists() for p in profile_outputs):
            logger.info(f'[9/{total}] configure profile skipped (output exists).')
        else:
            run_step(9, total, 'configure profile', self.configure, arch=arch, mode='profile')

        # Step 10: build profile
        if not force and all(p.exists() for p in profile_outputs):
            logger.info(f'[10/{total}] build profile output already exists, skipping (use --force to rebuild).')
        else:
            rebuilt_any_artifact[0] = True
            run_step(10, total, 'build profile', self.build, arch=arch, mode='profile', jobs=jobs)

        # Step 11: configure and build android gen_snapshot release
        android_rel_gen = self.root / 'engine/src/out/android_release_arm64/clang_arm64/gen_snapshot'
        if not force and android_rel_gen.exists():
            logger.info(f'[11/{total}] android gen_snapshot release output already exists, skipping (use --force to rebuild).')
        else:
            rebuilt_any_artifact[0] = True
            logger.info(f'[11/{total}] configure and build android gen_snapshot release...')
            t0 = time.time()
            self.configure_android(arch='arm64', mode='release')
            self.build_android_gen_snapshot(arch='arm64', mode='release', jobs=jobs)
            logger.info(f'✓ android gen_snapshot release completed in {time.time() - t0:.1f}s')

        # Step 12: configure and build android gen_snapshot profile
        android_prof_gen1 = self.root / 'engine/src/out/android_profile_arm64/exe.stripped/gen_snapshot'
        android_prof_gen2 = self.root / 'engine/src/out/android_profile_arm64/clang_arm64/gen_snapshot'
        android_prof_gen = android_prof_gen1 if android_prof_gen1.exists() else android_prof_gen2
        if not force and android_prof_gen.exists():
            logger.info(f'[12/{total}] android gen_snapshot profile output already exists, skipping (use --force to rebuild).')
        else:
            rebuilt_any_artifact[0] = True
            logger.info(f'[12/{total}] configure and build android gen_snapshot profile...')
            t0 = time.time()
            self.configure_android(arch='arm64', mode='profile')
            self.build_android_gen_snapshot(arch='arm64', mode='profile', jobs=jobs)
            logger.info(f'✓ android gen_snapshot profile completed in {time.time() - t0:.1f}s')

        # Step 13 & 14: debuild
        deb_file = Path(self.output(arch))
        deb_stale = False

        repo_base = Path(__file__).parent
        package_inputs = {
            repo_base / 'package.yaml',
            repo_base / 'build.toml',
            repo_base / 'package.py',
            repo_base / 'build.py',
            repo_base / 'install_flutter_complete.sh',
        }

        # Dynamically extract all repo-relative script/file sources from package.yaml
        if isinstance(self.package, dict) and 'resource' in self.package:
            for res_name, res_def in self.package['resource'].items():
                if isinstance(res_def, dict) and 'source' in res_def:
                    src_val = res_def['source']
                    src_lines = [src_val] if isinstance(src_val, str) else (src_val if isinstance(src_val, list) else [])
                    for line in src_lines:
                        if isinstance(line, str) and '$root/../' in line:
                            rel_path = line.split('$root/../', 1)[1]
                            package_inputs.add(repo_base / rel_path)

        if deb_file.exists():
            deb_mtime = deb_file.stat().st_mtime
            all_tracked_inputs = debug_outputs + release_outputs + profile_outputs + [android_rel_gen, android_prof_gen] + list(package_inputs)
            for artifact in all_tracked_inputs:
                if artifact.exists() and artifact.stat().st_mtime > deb_mtime:
                    deb_stale = True
                    logger.info(f'Detected newer input artifact or configuration ({artifact}), triggering debuild.')
                    break

        if force or rebuilt_any_artifact[0] or deb_stale or not deb_file.exists():
            run_step(14, total, 'debuild', self.debuild, arch=arch, output=self.output(arch))
        else:
            logger.info(f'[14/{total}] debuild output already up-to-date, skipping (use --force to rebuild).')



        logger.info(f'=== Build complete in {time.time() - start_time:.1f}s ===')
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
