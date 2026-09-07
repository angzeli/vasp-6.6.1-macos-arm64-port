#!/usr/bin/env python3
"""Check ordered optional eigenvalues against the requested reciprocal line path."""
import argparse
import math
from pathlib import Path
import re

parser=argparse.ArgumentParser()
parser.add_argument('directory',type=Path)
directory=parser.parse_args().directory
lines=(directory/'KPOINTS_OPT').read_text().splitlines()
samples=int(lines[1])
assert samples>=2 and lines[2].strip().lower().startswith('l')
assert lines[3].strip().lower().startswith('r'), 'Only reciprocal line-mode paths are checked'
endpoints=[list(map(float,line.split()[:3])) for line in lines[4:] if line.strip()]
assert len(endpoints)%2==0 and all(len(p)==3 for p in endpoints)
expected=[]
for a,b in zip(endpoints[::2],endpoints[1::2]):
    expected.extend([[x+(y-x)*i/(samples-1) for x,y in zip(a,b)] for i in range(samples)])
content=(directory/'PROCAR_OPT').read_text()
number=r'([-+\d.Ee]+)'
actual=[list(map(float,row)) for row in re.findall(r'k-point\s+\d+\s*:\s*'+number+r'\s+'+number+r'\s+'+number,content)]
assert len(actual)==len(expected)
residual=max(abs((x-y)-round(x-y)) for p,q in zip(actual,expected) for x,y in zip(p,q))
assert residual<=1e-6, 'Optional points differ in order or reciprocal coordinates'
bands=int(re.search(r'# of bands:\s*(\d+)',content).group(1))
values=[float(x) for x in re.findall(r'energy\s+([-+\d.Ee]+)',content)]
assert len(values)==len(expected)*bands and all(math.isfinite(x) for x in values)
stdout=(directory/'stdout.log').read_text()
assert stdout.index('Start KPOINTS_OPT')>stdout.index(' 1 F=')
print(f'segments={len(endpoints)//2} points={len(expected)} bands={bands} finite_eigenvalues={len(values)} maximum_reciprocal_residual={residual:.3g}; SCF precedes optional driver: PASS')
