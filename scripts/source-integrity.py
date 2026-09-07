#!/usr/bin/env python3
"""A compact private fingerprint of build inputs, excluding licensed test data."""
import hashlib
from pathlib import Path

root = Path('/Applications/Academic/vasp.6.6.1')
paths = [root / 'makefile']
for directory in ('src', 'arch'):
    paths.extend(p for p in (root / directory).rglob('*') if p.is_file())
digest = hashlib.sha256()
size = 0
for path in sorted(paths):
    content = path.read_bytes()
    relative = str(path.relative_to(root)).encode()
    digest.update(relative + b'\0' + len(content).to_bytes(8, 'big') + content)
    size += len(content)
print('scope=src,arch,root makefile; private local record only')
print(f'files={len(paths)}\nbytes={size}\nsha256={digest.hexdigest()}')
