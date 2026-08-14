import os
import sys
import git
import inspect
from loguru import logger
from functools import wraps

__ARCH__ = dict(arm='arm', arm64='aarch64', x64='x86_64', x86='i686')
__MODE__ = ('debug', 'release', 'profile')

if os.environ.get('PREFIX') == '/data/data/com.termux/files/usr':
    __TERMUX__ = 'true'
else:
    __TERMUX__ = 'false'


def termux_arch(arch: str):
    if arch in __ARCH__:
        return __ARCH__[arch]
    if arch in __ARCH__.values():
        return arch

    raise ValueError(f'unknown arch: "{arch}"')


def target_output(root: str, arch: str, mode: str, opted: bool = True):
    root = os.path.abspath(os.path.expanduser(root))
    if opted:
        dest = f'linux_{mode}_{arch}'
    else:
        dest = f'linux_{mode}_unopt_{arch}'
    return os.path.join(root, 'engine', 'src', 'out', dest)


def flutter_tag(root: str):
    if not os.path.isdir(root):
        return None
    try:
        return git.Repo(root).git.describe('--tag', '--abbrev=0')
    except Exception:
        return None


def canonicalize_git_url(url: str | None) -> str:
    if not url:
        return ""
    u = str(url).strip()
    if u.startswith('git@') and ':' in u:
        host, path = u.split(':', 1)
        host = host.removeprefix('git@')
        u = f"https://{host}/{path}"
    return u.rstrip('/').removesuffix('.git')


class Output(object):
    """Target output directory path manager across build modes."""
    def __init__(self, root: str, arch: str):
        self.any = None
        for it in __MODE__:
            out = target_output(root, arch, it)
            self.__dict__[it] = out

        existing_modes = [it for it in __MODE__ if getattr(self, it, None) and os.path.isdir(getattr(self, it))]

        # Prioritize debug mode directory whenever available
        debug_out = getattr(self, 'debug', None)
        if debug_out and os.path.isdir(debug_out):
            self.any = debug_out
        else:
            # Fall back to first existing directory in __MODE__ order
            for it in __MODE__:
                out = getattr(self, it, None)
                if out and os.path.isdir(out):
                    self.any = out
                    break

        # If no build output directory exists on disk yet, default to debug path
        if not self.any:
            self.any = getattr(self, 'debug', None)

        if len(existing_modes) > 1:
            logger.warning(
                f"Multiple build mode directories found on disk ({', '.join(existing_modes)}). "
                f"Output.any defaulting to debug mode path: '{self.any}'"
            )


# TODO: see bin/internal/update_engine_version.sh
def engine_version(root: str):
    path = os.path.join(root, 'bin/internal/engine.version')
    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return "unknown"



def recordm(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if os.environ.get('NO_RECORD'):
            return func(*args, **kwargs)
        if args and inspect.isclass(type(args[0])):
            class_name = args[0].__class__.__name__
            logged_args = args[1:]
        else:
            class_name = ''
            logged_args = args

        method = func.__name__
        if class_name:
            method = f'{class_name}.{method}'

        logged_args = [str(it) for it in logged_args]
        for k, v in kwargs.items():
            logged_args.append(f'{k}={v}')
        logged_args = ', '.join(logged_args)

        logger.debug(f'{method}({logged_args})')
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.exception(e)
            raise
    return wrapper


def record(cls):
    for name, method in vars(cls).items():
        if callable(method) and not name.startswith('__'):
            setattr(cls, name, recordm(method))
    return cls


if __name__ == '__main__':
    import fire
    fire.Fire()
