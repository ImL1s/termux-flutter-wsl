#!/usr/bin/env python3

import os
import re
import io
import utils
import string
import base64
import requests
import tarfile
import zipfile
import hashlib
import tempfile
import subprocess
from git import Repo
from loguru import logger
from pathlib import Path



def explore_file(src: Path):
    assert src.exists()

    if src.is_dir():
        for root, dirs, files in os.walk(src):
            # Exclude .git directories to prevent git object bloat in package
            dirs[:] = [d for d in dirs if d != '.git']
            rel = Path(root).relative_to(src)
            for it in dirs:
                yield rel / it
            for it in files:
                yield rel / it


def explore_git(src: Path):
    assert src.is_dir()

    for it in Repo(src).tree().traverse():
        yield it.path
    git = src/'.git'
    for it in explore_file(git):
        yield '.git'/it


def emit(out, src, git):
    assert isinstance(src, (Path, bytes, list)), src

    if isdir := isinstance(src, list):
        yield {'out': out}
    if isinstance(src, bytes):
        yield {'out': out, 'src': src}
        return
    for src, it in explore(src, git):
        yield {
            'out': out/src.name/it if isdir else out/it,
            'src': src/it}


def safe_eval(expr, globals_dict, defines_dict=None):
    if not isinstance(expr, str):
        return expr
    context = {**globals_dict, **(defines_dict or {})}
    if expr.startswith("f'") and expr.endswith("'"):
        inner = expr[2:-1]
        def replace(match):
            var = match.group(1)
            if var in context:
                val = context[var]
                if isinstance(val, str) and (val.startswith("f'") or val.startswith("'") or val.startswith('"')):
                    return str(safe_eval(val, globals_dict, defines_dict))
                return str(val)
            return f'{{{var}}}'
        return re.sub(r'\{([^}]+)\}', replace, inner)
    elif expr.startswith("'") and expr.endswith("'"):
        return expr[1:-1]
    elif expr.startswith('"') and expr.endswith('"'):
        return expr[1:-1]
    elif expr.startswith('output.'):
        attr = expr.split('.', 1)[1]
        return getattr(context['output'], attr)
    else:
        val = context.get(expr, expr)
        if isinstance(val, str) and val != expr and (val.startswith("f'") or val.startswith("'") or val.startswith('"')):
            return safe_eval(val, globals_dict, defines_dict)
        return val



def explore(src, git=False):
    # Always use explore_file to prevent git repository object traversal into .deb
    explore_fn = explore_file

    if not isinstance(src, list):
        src = [src]
    for src in src:
        src = src.absolute()
        if not src.exists() and not src.is_symlink():
            raise FileNotFoundError(f'missing required resource: "{src}"')
        yield src, Path('.')
        for it in explore_fn(src):
            yield src, it



def reset(info):
    info.uid = 0
    info.gid = 0
    info.mtime = int(os.environ.get('SOURCE_DATE_EPOCH', 0))
    info.uname = 'root'
    info.gname = 'root'
    info.mode |= 0o200


def add_bin(tar, out, src, mod=None):
    assert tar, out and isinstance(src, bytes)

    # Create parent directories first
    add_dir(tar, out.parent)

    info = tarfile.TarInfo(str(out))
    info.mode = mod or 0o644
    info.size = len(src)
    reset(info)
    tar.addfile(info, io.BytesIO(src))


def add_file(tar, out, src, mod=None):
    assert tar, out and src.exists()

    # Create parent directories first
    add_dir(tar, out.parent)

    info = tar.gettarinfo(src, out)
    info.mode = mod or info.mode
    reset(info)

    with open(src, 'rb') as f:
        tar.addfile(info, f)


def add_dir(tar, out, mod=None):
    assert tar, out

    cache = getattr(tar, '__cache__', set())
    tar.__cache__ = cache

    if out.parent == Path('.') or out in cache:
        return

    add_dir(tar, out.parent)
    info = tarfile.TarInfo(f'{out}/')
    info.type = tarfile.DIRTYPE
    info.mode = mod or 0o755
    reset(info)
    tar.addfile(info)
    cache.add(out)


def tar(path, data):
    if not data:
        logger.warning('no work to do.')
        return
    if isinstance(data, dict):
        data = [data]
    assert hasattr(data, '__iter__'), f'bad data format: "{data}"'

    with tarfile.open(path, mode='w:xz', format=tarfile.GNU_FORMAT, dereference=True) as tar:
        for it in data:
            out = it.get('out')
            src = it.get('src')
            mod = it.get('mod')
            assert out, f'bad out field: "{out}"'
            out = Path(out)
            assert mod is None or isinstance(mod, int)

            if isinstance(src, bytes):
                add_bin(tar, out, src, mod)
            elif not src or src.is_dir():
                add_dir(tar, out, mod)
            elif src.exists():
                add_file(tar, out, src, mod)
            else:
                raise FileNotFoundError(src)


def base64_md5_file(path):
    md5 = hashlib.md5()
    with open(path, 'rb') as f:
        while s := f.read(8192):
            md5.update(s)
    return base64.b64encode(md5.digest()).decode('utf8')


def download(url, out):
    assert url, out

    with requests.get(url, allow_redirects=True, stream=True) as resp:
        if resp.status_code != 200:
            return None
        if hash := resp.headers.get('x-goog-hash'):
            hash = dict([it.strip().split('=', 1) for it in hash.split(',')])
        if (dst := Path(out)) and dst.is_dir():
            dst = dst/url.split('?')[0].split('/')[-1]
        if dst.is_file() and (md5 := base64_md5_file(dst)):
            if md5 == hash.get('md5'):
                return dst
        resp = requests.get(url)
        # TODO: check md5
        with open(dst, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                f.write(chunk)
        return dst


class Output(utils.Output):
    pass



@utils.record
class Package(object):
    def __init__(self, root, arch, control, resource, define=None, tag=None, release_tag=None, **kwargs):
        root = Path(root).resolve()
        assert root.is_dir(), f'bad flutter root path: "{root}"'
        self.globals = {
            'tag': tag or utils.flutter_tag(root),
            'release_tag': release_tag or tag or utils.flutter_tag(root),
            'root': root,
            'arch': arch,
            'output': Output(root, arch),
            'version': utils.engine_version(root),
            'architecture': utils.termux_arch(arch),
        }
        self.defines = {
            k: safe_eval(v, self.globals) for k, v in (define or {}).items()
        }
        self.control = control
        self.resource = resource
        self.validate_control_headers()
        self.__dict__.update(self.globals)
        self.__dict__.update(self.defines)

    def validate_control_headers(self):

        mandatory = ('Package', 'Version', 'Architecture', 'Maintainer', 'Description')
        if not isinstance(self.control, dict):
            raise ValueError('Debian control header section must be a dictionary')
        for header in mandatory:
            if header not in self.control:
                raise ValueError(f"Missing mandatory Debian control header: '{header}'")
            val = self.control[header]
            if not val or not str(val).strip():
                raise ValueError(f"Mandatory Debian control header '{header}' cannot be empty")

    def __format__(self, s, **extra):

        return string.Template(s).safe_substitute(
            **self.globals,
            **self.defines,
            **extra)

    def gen_control(self):
        bin = io.BytesIO()
        for k, v in self.control.items():
            bin.write(self.__format__(f'{k}: {v}\n').encode('utf8'))
        return {'out': 'control', 'src': bin.getvalue()}

    def gen_resource(self, name=None):
        if isinstance(name, str):
            yield from self.gen_resource_internal(name)
        elif isinstance(name, list):
            for it in name:
                yield from self.gen_resource_internal(it)
        elif not name:
            for it in self.resource.keys():
                yield from self.gen_resource_internal(it)
        else:
            raise ValueError(f'bad name: "{name}"')

    def gen_resource_internal(self, name=None):
        if not (data := self.resource.get(name)):
            raise ValueError(f'unknown resource name: "{name}"')

        git = data.get('git', False)
        src = data.get('source', [])
        out = data.get('output')
        bin = data.get('binary', False)
        mod = data.get('mode')
        dep = data.get('define', {})
        replace = data.get('replace', False)
        replace_scope = data.get('replace_scope', None)
        ext = {}

        for k, v in dep.items():
            dep[k] = safe_eval(v, self.globals, self.defines)

        # expect None, str, int
        if isinstance(mod, str):
            mod = int(mod, 8)
        if isinstance(mod, int):
            ext['mod'] = mod
        elif mod is not None:
            raise ValueError(f'bad mode type: "{type(mod)}"')
        # expect str, list
        if isinstance(out, str):
            out = [out]
        if isinstance(out, list):
            out = (Path(self.__format__(it, **dep)) for it in out)
        else:
            raise ValueError(f'bad output type: "{type(out)}"')
        # expect None, str, list
        if isinstance(src, str):
            src = self.__format__(src, **dep)
            src = src.encode('utf8') if bin else Path(src)
        if isinstance(src, list) and not bin:
            src = [Path(self.__format__(it, **dep)) for it in src]
        elif not isinstance(src, (bytes, Path)):
            raise ValueError(f'bad source type: "{type(src)}"')

        ext['rule'] = name
        ext['replace'] = replace
        if replace_scope:
            ext['replace_scope'] = self.__format__(replace_scope, **dep)

        for out in out:
            for it in emit(out, src, git):
                yield it | ext

    def test_resource(self, name=None):
        if isinstance(name, str):
            yield self.test_resource_internal(name)
        elif isinstance(name, list):
            for it in name:
                yield self.test_resource_internal(it)
        elif not name:
            for it in self.resource.keys():
                yield self.test_resource_internal(it)
        else:
            raise ValueError(f'bad name: "{name}"')

    def test_resource_internal(self, name):
        if not (data := self.resource.get(name)):
            raise ValueError(f'unknown resource name: "{name}"')

        if not (test := data.get('test', {})):
            return None
        deps = data.get('define', {}).items()
        deps = {k: safe_eval(v, self.globals, self.defines) for k, v in deps}
        file = self.__format__(test['file'], **deps)
        path = self.__format__(test['path'], **deps)
        if not (dest := download(file, Path('~/storage/downloads/1DMP/General').expanduser())):
            logger.warning(f'test file not found: "{file}"')

        data = {it['out'] for it in self.gen_resource(name)}
        with zipfile.ZipFile(dest) as f:
            for it in f.namelist():
                if not it.endswith('.md') and Path(path, it) not in data:
                    logger.error(f'missing file: {path}/{it}')
                    return False
        return True

    def debuild(self, output, section=None):
        output = Path(output or '.').expanduser().resolve()
        if not output.parent.is_dir() or output.is_dir():
            raise ValueError(f'bad output path: "{output}"')

        with tempfile.TemporaryDirectory() as tmp:
            info = Path(tmp, 'debian-binary')
            ctrl = Path(tmp, 'control.tar.xz')
            data = Path(tmp, 'data.tar.xz')

            with open(info, 'wb+') as f:
                f.write(b'2.0\n')
            inventory = []
            seen_outputs = {}

            def track_resources():
                for it in self.gen_resource(section):
                    src = it.get('src')
                    out = it.get('out')
                    mod = it.get('mod')
                    rule = it.get('rule', 'unknown')
                    replace = it.get('replace', False)
                    replace_scope = it.get('replace_scope', None)

                    out_str = str(out)
                    src_str = str(src)

                    # 1. Target path collision & overlay detection
                    if out_str in seen_outputs:
                        prev = seen_outputs[out_str]
                        if not replace:
                            raise ValueError(
                                f"Duplicate target output path collision detected in package: '{out_str}'. "
                                f"Rule '{rule}' (source: '{src_str}') collides with earlier rule '{prev['rule']}' (source: '{prev['src']}'). "
                                f"If intentional, declare 'replace: true' on resource '{rule}'."
                            )
                        if replace_scope:
                            scope_path = str(Path(replace_scope))
                            if not out_str.startswith(scope_path):
                                raise ValueError(
                                    f"Overlay scope violation for resource '{rule}': target path '{out_str}' "
                                    f"is outside declared replace_scope '{scope_path}'"
                                )
                        logger.info(f"Overlaying '{out_str}': rule '{rule}' replaces earlier entry from rule '{prev['rule']}'")

                    # 2. Symlink validation
                    if isinstance(src, Path):
                        try:
                            target = os.readlink(src)
                            target_path = Path(target)
                            if not target_path.is_absolute():
                                target_path = src.parent / target_path
                            if not target_path.exists():
                                raise ValueError(f"Invalid or broken symlink mapping: '{src}' points to '{target}' which does not exist")
                        except OSError:
                            pass

                    if isinstance(src, bytes):
                        size = len(src)
                        sha = hashlib.sha256(src).hexdigest()
                    elif not src or src.is_dir():
                        size = 0
                        sha = "-"
                    elif src.exists():
                        size = src.stat().st_size
                        with open(src, 'rb') as f:
                            sha = hashlib.file_digest(f, 'sha256').hexdigest()
                    else:
                        size = 0
                        sha = "-"

                    seen_outputs[out_str] = {
                        'rule': rule,
                        'src': src_str,
                        'item': it,
                        'inv': f"{out}\t{sha}\t{size}\t{mod if mod else '-'}"
                    }

                for out_str, data_info in seen_outputs.items():
                    inventory.append(data_info['inv'])
                    yield data_info['item']



            tar(ctrl, self.gen_control())
            tar(data, track_resources())

            tmp_deb = Path(tmp, output.name)
            subprocess.run(
                    ['ar', 'rc', tmp_deb, info, ctrl, data],
                    check=True,
                    stderr=True,
                    stdout=True)

            os.rename(tmp_deb, output)


            inv_path = output.with_name(output.name + '.inventory')
            with open(inv_path, 'w', encoding='utf-8') as f:
                f.write("Path\tSHA256\tSize\tMode\n")
                f.write("\n".join(inventory))

        logger.info(f'✓ 构建完成 {output}')


if __name__ == '__main__':
    import fire
    import yaml

    with open('package.yaml', 'rb') as f:
        src = yaml.safe_load(f)
    pkg = Package(root='flutter', arch='arm64', **src)
    fire.Fire(pkg)
