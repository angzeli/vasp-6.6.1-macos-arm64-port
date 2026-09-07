#!/usr/bin/env python3
"""Fail closed on tracked licensed/build/runtime material before a local commit."""
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parent.parent
paths=subprocess.check_output(['git','-C',str(root),'ls-files','-z']).decode().split('\0')
allowed_roots={'config','scripts','docs','provenance','validation','tests'}
allowed_suffixes={'.md','.txt','.tsv','.sh','.py'}
for name in filter(None,paths):
    path=Path(name)
    allowed=name in {'.gitignore','README.md','VALIDATION_REPORT.md'}
    allowed |= name=='config/makefile.include.macos-arm64'
    allowed |= path.parts[0] in allowed_roots and path.suffix in allowed_suffixes
    if not allowed or path.name.startswith(('POTCAR','vasp_std','vasp_gam','vasp_ncl')):
        raise SystemExit('Disallowed tracked path: '+name)
    contents=subprocess.check_output(['git','-C',str(root),'show',':'+name])
    if b'\0' in contents or len(contents)>200_000:
        raise SystemExit('Binary or unexpectedly large tracked file: '+name)
for name in ['private/example.F','private/POTCAR','macos-arm64/build/std/main.F','macos-arm64/bin/vasp_std',
             'build/example.o', 'bin/vasp_std', 'private-source.tar.gz']:
    subprocess.run(['git','-C',str(root),'check-ignore','-q',name],check=True)
print('Tracked files are limited to independent tooling/docs/metadata; private exclusions pass.')
