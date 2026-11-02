#!/usr/bin/env python3
"""Single reader for pinned toolchain versions: tracked defaults, then host-local overrides.

config/toolchain-defaults.txt records the original port toolchain. The ignored
private/toolchain.env may override any of its keys for the current host only.
`toolchain.py --shell` prints quoted exports for scripts/environment.sh.
"""
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = ROOT / 'config/toolchain-defaults.txt'
LOCAL = ROOT / 'private/toolchain.env'
VERSION = re.compile(r'[0-9][0-9A-Za-z._-]*')


def read(path, allowed=None):
    values = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not sep or not key.startswith('PORT_') or not VERSION.fullmatch(value):
            raise ValueError(f'{path}:{number}: expected PORT_NAME=VERSION')
        if allowed is not None and key not in allowed:
            raise ValueError(f'{path}:{number}: unknown toolchain key {key}')
        values[key] = value
    return values


def load(root=None):
    """Return (versions, source) where source names the file that set any override."""
    defaults = DEFAULTS if root is None else Path(root) / 'config/toolchain-defaults.txt'
    local = LOCAL if root is None else Path(root) / 'private/toolchain.env'
    values = read(defaults)
    if not local.exists():
        return values, 'config/toolchain-defaults.txt'
    values.update(read(local, allowed=set(values)))
    return values, 'private/toolchain.env'


def main(argv):
    values, source = load()
    if argv[1:] == ['--shell']:
        for key, value in values.items():
            print(f'export {key}={shlex.quote(value)}')
        print(f'export PORT_TOOLCHAIN_SOURCE={shlex.quote(source)}')
        return 0
    for key, value in values.items():
        print(f'{key}={value}')
    print(f'# source: {source}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except ValueError as error:
        print(f'toolchain: {error}', file=sys.stderr)
        sys.exit(2)
