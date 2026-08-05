#!/usr/bin/env python3

import os
import sys
import json
import utils
import shutil
import hashlib
import pathlib
import asyncio
import aiohttp
import tempfile
import itertools
import subprocess
import urllib.parse
from loguru import logger


async def _download(sess, url, sha256_expected, dst):
    path = urllib.parse.urlparse(url).path
    name = pathlib.Path(path).name
    path = pathlib.Path(dst, name)
    try:
        sha256 = hashlib.sha256()
        async with sess.get(url) as resp:
            resp.raise_for_status()
            with open(path, 'wb') as f:
                async for chunk in resp.content.iter_chunked(8192):
                    f.write(chunk)
                    sha256.update(chunk)
        if sha256_expected and sha256.hexdigest() != sha256_expected:
            raise RuntimeError(f'✗ SHA256 mismatch for {name}: expected {sha256_expected}, got {sha256.hexdigest()}')
        return path
    except Exception as e:
        raise RuntimeError(f'✗ 下载或驗證失敗 {name}: {e}')


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
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        return await _spawn([
            _download(sess, pkg['url'], pkg.get('sha256'), out) for pkg in pkgs_info
        ])


async def _resolve_packages(sess, arch, repo, dist, pkgs):
    if not repo or not pkgs:
        return {}

    bin = f'dists/{dist}/main/binary-{arch}/Packages'
    url = urllib.parse.urljoin(repo, bin)

    current = None
    package = {}

    async with sess.get(url) as resp:
        resp.raise_for_status()
        async for line in resp.content:
            line = line.decode('utf-8', errors='ignore').strip()

            if line.startswith('Package:'):
                current = line.split(':', 1)[1].strip()
                if current in pkgs:
                    package[current] = {'name': current, 'repo': repo, 'dist': dist}
            elif current in pkgs:
                if line.startswith('Version:'):
                    package[current]['version'] = line.split(':', 1)[1].strip()
                elif line.startswith('Filename:'):
                    urlpath = line.split(':', 1)[1].strip()
                    package[current]['url'] = urllib.parse.urljoin(repo, urlpath)
                elif line.startswith('SHA256:'):
                    package[current]['sha256'] = line.split(':', 1)[1].strip()

            if len(package) == len(pkgs) and all('url' in v and 'sha256' in v for v in package.values()):
                break

    remains = [it for it in pkgs if it not in package]
    if remains:
        raise FileNotFoundError(f'packages {remains} not found.')
    return package


def _extract(out, deb):
    subprocess.run(['dpkg', '-x', str(deb), str(out)], check=True, stderr=True)
    logger.info(f'✓ 成功安裝 {deb.name}')


@utils.record
class Sysroot:
    def __init__(self, path: str, **kwargs):
        self.path = pathlib.Path(path).expanduser().resolve()
        self.data = {}
        self.lock_file = pathlib.Path('sysroot.lock.json').resolve()

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
        """刷新 lock file (從 repo 解析最新版本)"""
        arch = utils.termux_arch(arch)
        if not self.data:
            logger.info('no work to do.')
            return

        async def _do_lock():
            timeout = aiohttp.ClientTimeout(total=500)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                tasks = [_resolve_packages(sess, arch, **it) for it in self.data.values()]
                results = await _spawn(tasks)

                locked_pkgs = {}
                for res in results:
                    locked_pkgs.update(res)

                lock_data = {}
                if self.lock_file.exists():
                    try:
                        with open(self.lock_file, 'r', encoding='utf-8') as f:
                            lock_data = json.load(f)
                    except:
                        pass

                lock_data[arch] = locked_pkgs
                with open(self.lock_file, 'w', encoding='utf-8') as f:
                    json.dump(lock_data, f, indent=2, sort_keys=True)
                logger.info(f'✓ Updated lock file for {arch} at {self.lock_file.name}')

        asyncio.run(_do_lock())

    def verify(self, arch: str = 'arm64'):
        """驗證現有 sysroot 是否存在並完整"""
        arch = utils.termux_arch(arch)
        if not self.path.exists() or not (self.path / 'usr').exists():
            logger.error('Sysroot not found or incomplete.')
            sys.exit(1)
        if not self.lock_file.exists():
            logger.error('Lock file not found.')
            sys.exit(1)
        with open(self.lock_file, 'r', encoding='utf-8') as f:
            lock_data = json.load(f)
        if arch not in lock_data:
            logger.error(f'Arch {arch} not found in lock file.')
            sys.exit(1)
        logger.info(f'✓ Sysroot for {arch} looks valid.')

    def build(self, arch: str = 'arm64', locked: bool = True):
        """建立 sysroot，預設使用 --locked"""
        arch = utils.termux_arch(arch)
        if not self.data:
            logger.info('no work to do.')
            return

        # Ensure lock file exists BEFORE entering async context
        # (lock() uses asyncio.run() which cannot be nested)
        if locked:
            if not self.lock_file.exists():
                logger.warning('Lock file not found, creating one...')
                self.lock(arch)
            else:
                with open(self.lock_file, 'r', encoding='utf-8') as f:
                    lock_data = json.load(f)
                if arch not in lock_data:
                    logger.warning(f'Arch {arch} not found in lock file, creating...')
                    self.lock(arch)

        async def _do_build():
            pkgs_info = []
            if locked:
                with open(self.lock_file, 'r', encoding='utf-8') as f:
                    lock_data = json.load(f)

                req_pkgs = set()
                for it in self.data.values():
                    req_pkgs.update(it['pkgs'])

                pkgs_info = [v for k, v in lock_data[arch].items() if k in req_pkgs]
            else:
                timeout = aiohttp.ClientTimeout(total=500)
                async with aiohttp.ClientSession(timeout=timeout) as sess:
                    results = await _spawn([_resolve_packages(sess, arch, **it) for it in self.data.values()])
                    for res in results:
                        pkgs_info.extend(res.values())

            # Staging build
            staging_out = self.path.parent / f"{self.path.name}.staging"
            if staging_out.exists():
                shutil.rmtree(staging_out)
            staging_out.mkdir(parents=True, exist_ok=True)

            try:
                with tempfile.TemporaryDirectory() as tmp:
                    debs = await _download_packages(tmp, pkgs_info)
                    for deb in debs:
                        _extract(staging_out, deb)

                # Configure sysroot
                usr = staging_out / 'usr'
                dst = 'data/data/com.termux/files/usr'

                assert (staging_out / dst).is_dir()

                try:
                    usr.symlink_to(dst, True)
                except FileExistsError:
                    if not usr.samefile(staging_out / dst):
                        raise

                pthread = staging_out / 'usr/lib/libpthread.a'
                if pthread.exists():
                    pthread.write_bytes(b'INPUT(-lc)')

                # Atomic replacement
                if self.path.exists():
                    shutil.rmtree(self.path)
                staging_out.rename(self.path)
                logger.info(f'✓ Atomic replacement to {self.path} successful.')
            except Exception as e:
                logger.error(f'Build failed: {e}')
                if staging_out.exists():
                    shutil.rmtree(staging_out)
                sys.exit(1)

        asyncio.run(_do_build())

    def __call__(self, arch: str):
        # Default alias used by build.py
        self.build(arch=arch, locked=True)

    def __str__(self):
        return str(self.path)


if __name__ == '__main__':
    import fire
    import tomllib

    with open('build.toml', 'rb') as f:
        src = tomllib.load(f)

    fire.Fire(Sysroot(**src['sysroot']))
