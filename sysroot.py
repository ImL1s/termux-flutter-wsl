#!/usr/bin/env python3

import os
import sys
import io
import re
import json
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
        try:
            st = os.lstat(full_path)
            mode_str = oct(st.st_mode & 0o777)
        except Exception:
            mode_str = "0755"

        hasher.update(posix_path.encode('utf-8'))
        hasher.update(f'|mode:{mode_str}'.encode('utf-8'))
        if full_path.is_symlink():
            target = os.readlink(full_path)
            hasher.update(f'|symlink:{target}'.encode('utf-8'))
        elif full_path.is_file():
            hasher.update(b'|file:')
            with open(full_path, 'rb') as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
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
    tasks = [asyncio.create_task(t) for t in tasks]
    done, pending = await asyncio.wait(
        tasks,
        return_when=asyncio.FIRST_EXCEPTION)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    return [r.result() for r in done]


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
                with tempfile.TemporaryDirectory() as tmp_debs:
                    debs = await _spawn([
                        _download(sess, pkg['url'], pkg.get('sha256'), tmp_debs)
                        for pkg in locked_pkgs.values()
                    ])
                    staging_tmp = self.path.parent / f"{self.path.name}.lock_staging"
                    _safe_rmtree(staging_tmp)
                    staging_tmp.mkdir(parents=True, exist_ok=True)
                    try:
                        for deb in debs:
                            _extract(staging_tmp, deb)

                        usr = staging_tmp / 'usr'
                        dst = 'data/data/com.termux/files/usr'
                        if (staging_tmp / dst).is_dir():
                            try:
                                usr.symlink_to(dst, True)
                            except FileExistsError:
                                if not usr.samefile(staging_tmp / dst):
                                    raise

                        pthread = staging_tmp / 'usr/lib/libpthread.a'
                        if pthread.exists():
                            pthread.write_bytes(b'INPUT(-lc)')

                        tree_hash = compute_tree_hash(staging_tmp)
                    finally:
                        _safe_rmtree(staging_tmp)

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

    def verify(self, arch: str = 'arm64'):
        """驗證現有 sysroot 是否存在並完整"""
        arch_name = utils.termux_arch(arch)
        if not self.path.exists() or not (self.path / 'usr').exists():
            logger.error('Sysroot not found or incomplete.')
            sys.exit(1)
        if not self.lock_file.exists():
            logger.error('Lock file not found.')
            sys.exit(1)
        with open(self.lock_file, 'r', encoding='utf-8') as f:
            lock_data = json.load(f)
        if arch not in lock_data and arch_name not in lock_data:
            logger.error(f'Arch {arch} not found in lock file.')
            sys.exit(1)
        logger.info(f'✓ Sysroot for {arch} looks valid.')

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

            with open(self.lock_file, 'r', encoding='utf-8') as f:
                lock_data = json.load(f)

            arch_entry = lock_data.get(arch) or lock_data.get(arch_name)
            if not arch_entry or not isinstance(arch_entry, dict) or 'packages' not in arch_entry:
                raise RuntimeError(f'Arch {arch} missing or lock file incomplete in {self.lock_file.name}.')

            pkgs_dict = arch_entry['packages']
            expected_tree_hash = arch_entry.get('tree_hash')
            pkgs_info = list(pkgs_dict.values())

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

                # Configure sysroot
                usr = staging_out / 'usr'
                dst = 'data/data/com.termux/files/usr'

                if not (staging_out / dst).is_dir():
                    raise RuntimeError(f'Sysroot structure missing directory: {dst}')

                try:
                    usr.symlink_to(dst, True)
                except FileExistsError:
                    if not usr.samefile(staging_out / dst):
                        raise

                pthread = staging_out / 'usr/lib/libpthread.a'
                if pthread.exists():
                    pthread.write_bytes(b'INPUT(-lc)')

                # Validate tree_hash if locked
                actual_tree_hash = compute_tree_hash(staging_out)
                if locked and expected_tree_hash:
                    if actual_tree_hash != expected_tree_hash:
                        raise RuntimeError(
                            f'Sysroot tree_hash mismatch: expected {expected_tree_hash}, got {actual_tree_hash}'
                        )

                # Atomic replacement
                _safe_rmtree(self.path)
                staging_out.rename(self.path)
                logger.info(f'✓ Atomic replacement to {self.path} successful.')
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
