#!/usr/bin/env python3
"""Inspect native dependencies without redistributing executable content."""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('binary', type=Path)
args = parser.parse_args()
binary = args.binary.resolve()

def output(*command):
    return subprocess.check_output(command, text=True)

assert 'Mach-O 64-bit executable arm64' in output('/usr/bin/file', str(binary))
queue = [(binary, [])]
seen = set()
records = []
while queue:
    path, inherited = queue.pop(0)
    path = path.resolve()
    if path in seen:
        continue
    seen.add(path)
    description = output('/usr/bin/file', str(path)).strip()
    if 'arm64' not in description:
        raise SystemExit(f'No native ARM64 slice: {path}')
    commands = output('/usr/bin/otool', '-l', str(path))
    rpaths = re.findall(r'cmd LC_RPATH\n\s*cmdsize \d+\n\s*path (.+?) \(offset', commands)
    expand = lambda s: s.replace('@loader_path', str(path.parent)).replace('@executable_path', str(binary.parent))
    rpaths = [expand(r) for r in rpaths] + inherited
    for line in output('/usr/bin/otool', '-L', str(path)).splitlines()[1:]:
        dependency = line.strip().split(' (compatibility')[0]
        if dependency.startswith(('/usr/lib/', '/System/Library/')):
            records.append((str(path), dependency, 'system dyld cache'))
            continue
        if dependency.startswith('@rpath/'):
            candidates = [Path(r) / dependency[len('@rpath/'):] for r in rpaths]
        else:
            candidates = [Path(expand(dependency))]
        resolved = next((p.resolve() for p in candidates if p.exists()), None)
        if resolved is None:
            raise SystemExit(f'Unresolved dependency: {path.name}: {dependency}')
        if '/openmpi-4.' in str(resolved) or '/gcc@14/' in str(resolved):
            raise SystemExit(f'Unexpected old runtime: {resolved}')
        records.append((str(path), dependency, str(resolved)))
        queue.append((resolved, rpaths))
print('binary\t'+str(binary))
print('sha256\t'+hashlib.sha256(binary.read_bytes()).hexdigest())
print('native_images_checked\t'+str(len(seen)))
for row in records:
    print('\t'.join(row))
