#!/usr/bin/env python3

import os
import sys
import io
import re
import json
import time
import utils
import shutil
import hashlib
import pathlib
import asyncio
import aiohttp
import tempfile
import tarfile
import subprocess
import urllib.parse
from datetime import datetime, timezone
from loguru import logger

def _parse_deps(dep_str):
    if not dep_str:
        return []
    res = []
    for part in dep_str.split(','):
        item = part.split('|')[0].strip()
        item = re.sub(r'\(.*?\)', '', item).strip()
        item = item.split(':')[0].strip()
        if item and item not in res:
            res.append(item)
    return res



def compute_tree_hash(dir_path: pathlib.Path) -> str:
    """Compute deterministic SHA256 hash of a directory tree."""
    hasher = hashlib.sha256()
    dir_path = pathlib.Path(dir_path).resolve()
    if not dir_path.exists():
        return ""
    items = []
    for root, dirs, files in os.walk(dir_path):
        rel_root = pathlib.Path(root).relative_to(dir_path)
        for name in dirs:
            items.append(rel_root / name)
        for name in files:
            items.append(rel_root / name)

    items.sort(key=lambda p: p.as_posix())

    for rel_path in items:
        full_path = dir_path / rel_path
        posix_path = rel_path.as_posix()
        is_symlink = False
        try:
            st = os.lstat(full_path)
            import stat as stat_mod
            is_symlink = stat_mod.S_ISLNK(st.st_mode) or os.path.islink(full_path) or full_path.is_symlink()
            if is_symlink or stat_mod.S_ISDIR(st.st_mode) or (st.st_mode & 0o111 != 0):
                mode_str = "0755"
            else:
                mode_str = "0644"
        except Exception:
            mode_str = "0755"

        hasher.update(posix_path.encode('utf-8'))
        hasher.update(f'|mode:{mode_str}'.encode('utf-8'))
        if is_symlink:
            try:
                target = os.readlink(full_path).replace('\\', '/')
            except Exception:
                target = ""
            hasher.update(f'|symlink:{target}'.encode('utf-8'))
        elif full_path.is_file():
            hasher.update(b'|file:')
            try:
                with open(full_path, 'rb') as f:
                    while chunk := f.read(65536):
                        hasher.update(chunk)
            except OSError:
                pass
        elif full_path.is_dir():
            hasher.update(b'|dir:')

    return hasher.hexdigest()


def _is_file_uncommitted(file_path: pathlib.Path) -> bool:
    try:
        res = subprocess.run(
            ['git', 'status', '--porcelain', str(file_path)],
            capture_output=True, text=True, check=False
        )
        if res.returncode == 0:
            if res.stdout.strip():
                return True
            ls_res = subprocess.run(
                ['git', 'ls-files', '--error-unmatch', str(file_path)],
                capture_output=True, text=True, check=False
            )
            if ls_res.returncode != 0:
                return True
    except Exception:
        pass
    return False


async def _download(sess, url, sha256_expected, dst):
    path_str = urllib.parse.urlparse(url).path
    name = pathlib.Path(path_str).name
    dst_path = pathlib.Path(dst, name)
    try:
        sha256 = hashlib.sha256()
        async with sess.get(url) as resp:
            resp.raise_for_status()
            with open(dst_path, 'wb') as f:
                async for chunk in resp.content.iter_chunked(8192):
                    f.write(chunk)
                    sha256.update(chunk)
        digest = sha256.hexdigest()
        if sha256_expected and digest != sha256_expected:
            raise RuntimeError(f'✗ SHA256 mismatch for {name}: expected {sha256_expected}, got {digest}')
        return dst_path
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f'✗ 下載或驗證失敗 {name}: {e}')


async def _spawn(tasks):
    if not tasks:
        return []
    return list(await asyncio.gather(*tasks))


async def _download_packages(out, pkgs_info):
    timeout = aiohttp.ClientTimeout(total=500)
    conn = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(timeout=timeout, connector=conn) as sess:
        return await _spawn([
            _download(sess, pkg['url'], pkg.get('sha256'), out) for pkg in pkgs_info
        ])


async def _resolve_packages(sess, arch, sysroot_data):
    if not sysroot_data:
        return {}

    termux_arch = utils.termux_arch(arch)
    all_pkgs_db = {}
    target_pkgs = set()

    for group_name, group_info in sysroot_data.items():
        if not isinstance(group_info, dict):
            continue
        repo = group_info.get('repo')
        dist = group_info.get('dist')
        pkgs = group_info.get('pkgs', [])
        if not repo or not dist or not pkgs:
            continue
        target_pkgs.update(pkgs)

        bin_path = f'dists/{dist}/main/binary-{termux_arch}/Packages'
        url = urllib.parse.urljoin(repo, bin_path)

        async with sess.get(url) as resp:
            resp.raise_for_status()
            content = await resp.text()
            stanzas = [s.strip() for s in content.split('\n\n') if s.strip()]
            for stanza in stanzas:
                fields = {}
                current_key = None
                for line in stanza.split('\n'):
                    if line.startswith((' ', '\t')) and current_key:
                        fields[current_key] += ' ' + line.strip()
                    elif ':' in line:
                        k, v = line.split(':', 1)
                        current_key = k.strip().lower()
                        fields[current_key] = v.strip()
                pkg_name = fields.get('package')
                if pkg_name:
                    filename = fields.get('filename', '')
                    deps = _parse_deps(fields.get('depends')) + _parse_deps(fields.get('pre-depends'))
                    pkg_url = urllib.parse.urljoin(repo, filename)
                    all_pkgs_db[pkg_name] = {
                        'name': pkg_name,
                        'version': fields.get('version', ''),
                        'url': pkg_url,
                        'sha256': fields.get('sha256', ''),
                        'size': int(fields.get('size', 0)) if fields.get('size') else 0,
                        'archive_path': filename,
                        'repo': repo,
                        'dist': dist,
                        'deps': deps
                    }

    queue = list(target_pkgs)
    resolved = {}
    visited = set()

    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)

        if curr in all_pkgs_db:
            info = all_pkgs_db[curr]
            lock_pkg = {k: v for k, v in info.items() if k != 'deps'}
            resolved[curr] = lock_pkg
            for dep in info.get('deps', []):
                if dep not in visited:
                    queue.append(dep)
        else:
            if curr in target_pkgs:
                raise RuntimeError(f"Required top-level package '{curr}' not found in repositories.")
            else:
                logger.warning(f"Transitive dependency '{curr}' not found in index, skipping.")

    return dict(sorted(resolved.items()))


def _extract_deb_python(out_dir: pathlib.Path, deb_path: pathlib.Path):
    with open(deb_path, 'rb') as f:
        magic = f.read(8)
        if magic != b'!<arch>\n':
            raise ValueError(f"Not a valid deb archive: {deb_path}")
        data_bytes = None
        data_name = None
        while header := f.read(60):
            if len(header) < 60:
                break
            name = header[:16].decode('latin1').strip().rstrip('/')
            size = int(header[48:58].decode('latin1').strip())
            member_data = f.read(size)
            if size % 2 != 0:
                f.read(1)
            if name.startswith('data.tar'):
                data_bytes = member_data
                data_name = name
                break
        if data_bytes is None:
            raise ValueError(f"data.tar member not found in {deb_path}")

        mode = 'r:*'
        if data_name.endswith('.xz'):
            mode = 'r:xz'
        elif data_name.endswith('.gz'):
            mode = 'r:gz'
        elif data_name.endswith('.bz2'):
            mode = 'r:bz2'

        with tarfile.open(fileobj=io.BytesIO(data_bytes), mode=mode) as tar:
            tar.extractall(path=out_dir)


def _extract(out: pathlib.Path, deb: pathlib.Path):
    dpkg_bin = shutil.which('dpkg')
    if dpkg_bin:
        try:
            subprocess.run([dpkg_bin, '-x', str(deb), str(out)], check=True, stderr=subprocess.PIPE)
            logger.info(f'✓ 成功安裝 {deb.name}')
            return
        except Exception:
            pass
    _extract_deb_python(out, deb)
    logger.info(f'✓ 成功安裝 {deb.name}')


def _apply_sysroot_transformations(target_dir: pathlib.Path):
    """Apply deterministic C++ header rename and glib-typeof.h extern wrapper fixes before tree_hash calculation."""
    target_dir = pathlib.Path(target_dir)

    cxx_dir = target_dir / 'usr' / 'include' / 'c++'
    if cxx_dir.is_dir():
        cxx_bak = target_dir / 'usr' / 'include' / 'c++.bak'
        _safe_rmtree(cxx_bak)
        cxx_dir.rename(cxx_bak)

    glib_typeof = target_dir / 'usr' / 'include' / 'glib-2.0' / 'glib' / 'glib-typeof.h'
    if glib_typeof.exists():
        content = glib_typeof.read_text(encoding='utf-8')
        extern_wrapper = 'extern "C++" {\n#include <type_traits>\n}'
        if r'extern "C++" {\n#include <type_traits>\n}' in content:
            content = content.replace(r'extern "C++" {\n#include <type_traits>\n}', extern_wrapper)
            glib_typeof.write_text(content, encoding='utf-8')
        elif '<type_traits>' in content and 'extern "C++"' not in content:
            content = content.replace('#include <type_traits>', extern_wrapper)
            glib_typeof.write_text(content, encoding='utf-8')


def _normalize_pthread_shim(staging_root: pathlib.Path) -> pathlib.Path:
    """Deterministically normalize canonical data/data/com.termux/files/usr/lib/libpthread.a to b'INPUT(-lc)'."""
    staging_root = pathlib.Path(staging_root)
    dst_rel = 'data/data/com.termux/files/usr'
    termux_usr = staging_root / 'data' / 'data' / 'com.termux' / 'files' / 'usr'
    termux_usr_lib = termux_usr / 'lib'
    termux_usr_lib.mkdir(parents=True, exist_ok=True)

    usr = staging_root / 'usr'
    if usr.is_dir() and not usr.is_symlink():
        for root, dirs, files in os.walk(usr, topdown=False):
            rel_root = pathlib.Path(root).relative_to(usr)
            target_dir = termux_usr / rel_root
            target_dir.mkdir(parents=True, exist_ok=True)
            for f in files:
                src_file = pathlib.Path(root) / f
                dst_file = target_dir / f
                if dst_file.exists() or dst_file.is_symlink():
                    try:
                        dst_file.unlink()
                    except OSError:
                        pass
                if src_file.is_symlink():
                    link_target = os.readlink(src_file)
                    try:
                        dst_file.symlink_to(link_target)
                    except OSError:
                        shutil.move(str(src_file), str(dst_file))
                    try:
                        src_file.unlink()
                    except OSError:
                        pass
                else:
                    shutil.move(str(src_file), str(dst_file))
            for d in dirs:
                dir_path = pathlib.Path(root) / d
                if dir_path.is_symlink():
                    dst_symlink = target_dir / d
                    if dst_symlink.exists() or dst_symlink.is_symlink():
                        try:
                            dst_symlink.unlink()
                        except OSError:
                            pass
                    link_target = os.readlink(dir_path)
                    try:
                        dst_symlink.symlink_to(link_target)
                    except OSError:
                        pass
                    try:
                        dir_path.unlink()
                    except OSError:
                        pass
                else:
                    try:
                        dir_path.rmdir()
                    except OSError:
                        pass
        try:
            usr.rmdir()
        except OSError:
            shutil.rmtree(usr, ignore_errors=True)

    if (staging_root / dst_rel).is_dir():
        if not usr.is_symlink() and not usr.exists():
            try:
                usr.symlink_to(dst_rel, True)
            except (FileExistsError, OSError):
                pass
        elif usr.is_symlink():
            try:
                target = os.readlink(usr)
                if target.replace('\\', '/') != dst_rel:
                    usr.unlink()
                    usr.symlink_to(dst_rel, True)
            except OSError:
                pass

    pthread_canonical = termux_usr_lib / 'libpthread.a'
    if pthread_canonical.is_symlink() or pthread_canonical.is_dir():
        try:
            if pthread_canonical.is_dir():
                _safe_rmtree(pthread_canonical)
            else:
                pthread_canonical.unlink()
        except OSError:
            pass

    pthread_canonical.write_bytes(b'INPUT(-lc)')
    try:
        os.chmod(pthread_canonical, 0o644)
    except Exception:
        pass

    return pthread_canonical


def _safe_rmtree(path: pathlib.Path):
    path = pathlib.Path(path)
    if not path.exists() and not path.is_symlink():
        return
    usr = path / 'usr'
    if usr.is_symlink():
        try:
            usr.unlink()
        except Exception:
            pass
    for _ in range(3):
        try:
            def _on_error(func, p, exc):
                try:
                    os.chmod(p, 0o777)
                    func(p)
                except Exception:
                    pass
            shutil.rmtree(path, onerror=_on_error)
            if not path.exists():
                return
        except Exception:
            import time
            time.sleep(0.2)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


@utils.record
class Sysroot:
    def __init__(self, path: str, **kwargs):
        self.path = pathlib.Path(path).expanduser().resolve()
        self.data = {}
        self.lock_file = (pathlib.Path(__file__).parent / 'sysroot.lock.json').resolve()

        if not self.path.exists():
            self.path.mkdir(parents=True, exist_ok=True)
        assert self.path.is_dir(), f'bad sysroot path: "{path}"'

        for k, v in kwargs.items():
            if isinstance(v, dict):
                self.__include__(k, **v)
        self._recover_orphaned_backups()

    def _recover_orphaned_backups(self):
        """Recover from abrupt process termination if an orphaned backup exists and active sysroot is missing or corrupt."""
        parent = self.path.parent
        if not parent.exists():
            return
        backups = sorted(parent.glob(f"{self.path.name}.bak.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not backups:
            return

        needs_recovery = not self.path.exists()
        if self.path.exists():
            try:
                if self.lock_file.exists():
                    self.verify()
            except Exception:
                needs_recovery = True

        if needs_recovery and backups:
            latest_bak = backups[0]
            logger.warning(f'Orphaned backup detected at {latest_bak}. Restoring to active sysroot {self.path}...')
            try:
                _safe_rmtree(self.path)
                latest_bak.rename(self.path)
                logger.success(f'Successfully restored orphaned backup {latest_bak} to {self.path}')
            except Exception as e:
                logger.error(f'Failed to restore orphaned backup {latest_bak}: {e}')

    def __include__(self, name, repo, dist, pkgs):
        assert name and repo and dist and pkgs
        self.data[name] = {'repo': repo, 'dist': dist, 'pkgs': pkgs}

    def lock(self, arch: str = 'arm64'):
        """刷新 lock file (從 repo 解析最新版本並計算 tree_hash)"""
        arch_name = utils.termux_arch(arch)
        if not self.data:
            logger.info('no work to do.')
            return

        async def _do_lock():
            timeout = aiohttp.ClientTimeout(total=500)
            conn = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
            async with aiohttp.ClientSession(timeout=timeout, connector=conn) as sess:
                locked_pkgs = await _resolve_packages(sess, arch, self.data)

                # Assemble in temporary staging to compute exact tree_hash
                with tempfile.TemporaryDirectory() as tmp_debs, tempfile.TemporaryDirectory() as tmp_staging:
                    debs = await _spawn([
                        _download(sess, pkg['url'], pkg.get('sha256'), tmp_debs)
                        for pkg in locked_pkgs.values()
                    ])
                    staging_tmp = pathlib.Path(tmp_staging)
                    for deb in debs:
                        _extract(staging_tmp, deb)

                    _normalize_pthread_shim(staging_tmp)
                    _apply_sysroot_transformations(staging_tmp)
                    tree_hash = compute_tree_hash(staging_tmp)

                lock_data = {}
                if self.lock_file.exists():
                    try:
                        with open(self.lock_file, 'r', encoding='utf-8') as f:
                            lock_data = json.load(f)
                    except Exception:
                        pass

                created_at = datetime.now(timezone.utc).isoformat()
                entry = {
                    'arch': arch,
                    'created_at': created_at,
                    'tree_hash': tree_hash,
                    'packages': locked_pkgs
                }
                lock_data[arch] = entry
                if arch != arch_name:
                    lock_data[arch_name] = entry
                with open(self.lock_file, 'w', encoding='utf-8') as f:
                    json.dump(lock_data, f, indent=2, sort_keys=True)
                logger.info(f'✓ Updated lock file for {arch} ({arch_name}) at {self.lock_file.name} (tree_hash: {tree_hash})')


        asyncio.run(_do_lock())

    def verify(self, arch: str = 'arm64') -> bool:
        """驗證現有 sysroot 是否存在並完整"""
        arch_name = utils.termux_arch(arch)
        if not self.path.exists() or not ((self.path / 'usr').exists() or (self.path / 'usr').is_symlink()):
            logger.error('Sysroot not found or incomplete.')
            raise ValueError('Sysroot not found or incomplete.')
        if not self.lock_file.exists():
            logger.error('Lock file not found.')
            raise ValueError('Lock file not found.')
        try:
            with open(self.lock_file, 'r', encoding='utf-8') as f:
                lock_data = json.load(f)
        except Exception as e:
            logger.error(f'Lock file invalid or unparseable: {e}')
            raise ValueError(f'Lock file invalid or unparseable: {e}')

        if not isinstance(lock_data, dict):
            logger.error('Lock file root element must be a dictionary.')
            raise ValueError('Lock file root element must be a dictionary.')

        if arch not in lock_data and arch_name not in lock_data:
            logger.error(f'Arch {arch} ({arch_name}) not found in lock file.')
            raise ValueError(f'Arch {arch} ({arch_name}) not found in lock file.')

        entry = lock_data.get(arch) if arch in lock_data else lock_data.get(arch_name)
        if not isinstance(entry, dict):
            logger.error(f'Lock entry for {arch} is malformed (not a dictionary).')
            raise ValueError(f'Lock entry for {arch} is malformed (not a dictionary).')

        packages = entry.get('packages')
        if packages is None or not isinstance(packages, (dict, list)):
            logger.error(f'Lock entry packages field for {arch} is missing or malformed.')
            raise ValueError(f'Lock entry packages field for {arch} is missing or malformed.')

        expected_hash = entry.get('tree_hash')
        if not expected_hash or not isinstance(expected_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_hash):
            logger.error(f'Lock entry tree_hash for {arch} is missing, empty, or malformed: {expected_hash!r}')
            raise ValueError(f'Lock entry tree_hash for {arch} is missing, empty, or malformed: {expected_hash!r}')

        actual_hash = compute_tree_hash(self.path)
        if actual_hash != expected_hash:
            logger.error(f'Sysroot tree hash mismatch for {arch}: actual={actual_hash} != expected={expected_hash}')
            raise ValueError(f'Sysroot tree hash mismatch for {arch}: actual={actual_hash} != expected={expected_hash}')

        logger.info(f'✓ Sysroot for {arch} looks valid (tree_hash verified: {actual_hash}).')
        return True

    def build(self, arch: str = 'arm64', locked: bool = True):
        """建立 sysroot，預設 shadow 啟用 --locked"""
        arch_name = utils.termux_arch(arch)
        if not self.data:
            logger.info('no work to do.')
            return

        expected_tree_hash = None
        pkgs_info = []

        if locked:
            if not self.lock_file.exists():
                raise RuntimeError(f'Lock file {self.lock_file.name} not found.')
            if _is_file_uncommitted(self.lock_file):
                raise RuntimeError(f'Lock file {self.lock_file.name} is uncommitted or untracked in git.')

            try:
                with open(self.lock_file, 'r', encoding='utf-8') as f:
                    lock_data = json.load(f)
            except Exception as e:
                raise RuntimeError(f'Lock file {self.lock_file.name} invalid or unparseable: {e}')

            if not isinstance(lock_data, dict):
                raise RuntimeError(f'Lock file {self.lock_file.name} root element must be a dictionary.')

            arch_entry = lock_data.get(arch) or lock_data.get(arch_name)
            if not arch_entry or not isinstance(arch_entry, dict):
                raise RuntimeError(f'Arch {arch} ({arch_name}) entry missing or lock file incomplete in {self.lock_file.name}.')

            pkgs_dict = arch_entry.get('packages')
            if not isinstance(pkgs_dict, (dict, list)) or not pkgs_dict:
                raise RuntimeError(f'Arch {arch} packages field missing or malformed in lock file {self.lock_file.name}.')

            expected_tree_hash = arch_entry.get('tree_hash')
            if not expected_tree_hash or not isinstance(expected_tree_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_tree_hash):
                raise RuntimeError(f'Arch {arch} tree_hash missing, empty, or malformed ({expected_tree_hash!r}) in lock file {self.lock_file.name}.')

            pkgs_info = list(pkgs_dict.values()) if isinstance(pkgs_dict, dict) else pkgs_dict
            for pkg in pkgs_info:
                pkg_name = pkg.get('name') if isinstance(pkg, dict) else 'unknown'
                pkg_sha = pkg.get('sha256') if isinstance(pkg, dict) else None
                if not pkg_sha or not isinstance(pkg_sha, str) or not re.fullmatch(r'[0-9a-f]{64}', pkg_sha):
                    raise RuntimeError(f"Package '{pkg_name}' has invalid or missing sha256 in lock file.")

        async def _do_build():
            nonlocal pkgs_info, expected_tree_hash
            if not locked:
                timeout = aiohttp.ClientTimeout(total=500)
                conn = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
                async with aiohttp.ClientSession(timeout=timeout, connector=conn) as sess:
                    resolved = await _resolve_packages(sess, arch, self.data)
                    pkgs_info = list(resolved.values())

            # Staging build
            staging_out = self.path.parent / f"{self.path.name}.staging"
            _safe_rmtree(staging_out)
            staging_out.mkdir(parents=True, exist_ok=True)

            try:
                with tempfile.TemporaryDirectory() as tmp:
                    debs = await _download_packages(tmp, pkgs_info)
                    for deb in debs:
                        _extract(staging_out, deb)

                _normalize_pthread_shim(staging_out)
                _apply_sysroot_transformations(staging_out)

                # Validate tree_hash if locked
                actual_tree_hash = compute_tree_hash(staging_out)
                if locked:
                    if not expected_tree_hash or actual_tree_hash != expected_tree_hash:
                        raise RuntimeError(
                            f'Sysroot tree_hash mismatch: expected {expected_tree_hash}, got {actual_tree_hash}'
                        )

                # Safe activation with rollback backup
                timestamp = int(time.time())
                backup_path = self.path.parent / f"{self.path.name}.bak.{timestamp}"

                has_active = self.path.exists()
                if has_active:
                    _safe_rmtree(backup_path)
                    self.path.rename(backup_path)

                try:
                    staging_out.rename(self.path)
                    logger.info(f'✓ Atomic activation to {self.path} successful.')
                    if has_active and backup_path.exists():
                        _safe_rmtree(backup_path)
                except Exception as act_err:
                    logger.error(f'Activation failed: {act_err}')
                    if has_active and backup_path.exists():
                        try:
                            _safe_rmtree(self.path)
                            backup_path.rename(self.path)
                            logger.info(f'Restored active sysroot from backup {backup_path}')
                        except Exception as restore_err:
                            logger.error(f'Failed to restore backup {backup_path}: {restore_err}')
                    raise
            except Exception as e:
                logger.error(f'Build failed: {e}')
                logger.error(f'Staging directory preserved at {staging_out} for debugging')
                raise

        asyncio.run(_do_build())

    def __call__(self, arch: str = 'arm64', locked: bool = True):
        self.build(arch=arch, locked=locked)

    def __str__(self):
        return str(self.path)


if __name__ == '__main__':
    import fire
    import tomllib

    with open('build.toml', 'rb') as f:
        src = tomllib.load(f)

    fire.Fire(Sysroot(**src['sysroot']))
