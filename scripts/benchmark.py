#!/usr/bin/env python3
"""Bounded beta-phase comparisons using private copies of existing references."""
import argparse
import csv
import math
from pathlib import Path
import re
import shutil
import subprocess
import time
from observables import read_case
from validate import ROOT, WORK

PROJECT = Path('/Users/liangze/Desktop/Imperial/Year 26-27/fyp/computational/vasp/wp1_polymorph_polytype_benchmark')
PBE = PROJECT/'calculation/03_static_scf/beta'
HSE = PROJECT/'calculation/05_hybrid_validation/01_hse06_scf/beta'
PATH_REFERENCE = PROJECT/'calculation/04_electronic_structure/beta/band/KPOINTS'
TABLE = ROOT/'validation/reports/beta.tsv'

def prepare(name, source, edits):
    directory=WORK/name
    directory.mkdir(parents=True,exist_ok=False)
    for f in ['INCAR','POSCAR','POTCAR','KPOINTS']:shutil.copy2(source/f,directory/f)
    settings={}
    for line in (directory/'INCAR').read_text().splitlines():
        line=line.split('#')[0].split('!')[0]
        if '=' in line:
            key,value=line.split('=',1);settings[key.strip().upper()]=value.strip()
    settings.update(edits)
    (directory/'INCAR').write_text(''.join(f'{k} = {v}\n' for k,v in settings.items()))
    for f in ['POSCAR','POTCAR','KPOINTS']:
        assert (directory/f).read_bytes()==(source/f).read_bytes()
    return directory

def execute(directory,binary,timeout,expected_version,convergence=True):
    command=[str(ROOT/'scripts/run-mpi.sh'),'--ranks','8','--mode','synthetic','--timeout',str(timeout),'--',str(binary)]
    started=time.monotonic()
    with (directory/'stdout.log').open('w') as output:
        status=subprocess.run(command,cwd=directory,stdout=output,stderr=subprocess.STDOUT).returncode
    result={}
    try:result=read_case(directory)
    except Exception as error:print(f'{directory.name}: incomplete output: {error}',flush=True)
    out=(directory/'OUTCAR').read_text(errors='replace') if (directory/'OUTCAR').exists() else ''
    loops=[float(x) for x in re.findall(r'LOOP:\s+cpu time\s+[\d.]+:\s+real time\s+([\d.]+)',out)]
    row=dict(case=directory.name,version=result.get('version',''),exit=status,wall_s=round(time.monotonic()-started,3),
             energy_eV=result.get('energy_eV',''),nelect=result.get('nelect',''),converged=result.get('converged',False),
             normal=result.get('normal',False),iterations=result.get('iterations',''),
             iteration_seconds=','.join(map(str,loops)),sxx_kB=result.get('stress_kB',[['']])[0][0])
    exists=TABLE.exists()
    with TABLE.open('a',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(row),delimiter='\t')
        if not exists:writer.writeheader()
        writer.writerow(row)
    print(row,flush=True)
    if convergence:
        assert status==0 and result.get('normal') and result.get('converged')
        assert result['version'].startswith(expected_version)
    else:
        assert status in [0,124], f'Unexpected benchmark exit: {status}'
        if status==0:
            assert result.get('normal') and result['version'].startswith(expected_version)
    return result

def pbe():
    for release,binary in [('5.4.4',Path('/Applications/Academic/vasp.5.4.4/macos-arm64/bin/vasp_std')),
                           ('6.6.1',ROOT/'macos-arm64/bin/vasp_std')]:
        edits=dict(NCORE=1,KPAR=1,NBANDS=40,LCHARG='.FALSE.',LWAVE='.TRUE.' if release=='6.6.1' else '.FALSE.')
        directory=prepare('beta-pbe-'+release,PBE,edits)
        execute(directory,binary,1800,release)

def benchmark(ace):
    name='beta-hse-ace' if ace else 'beta-hse-damped'
    directory=prepare(name,HSE,dict(NCORE=1,KPAR=1,NBANDS=40,NELM=2,NELMIN=2,NELMDL=0,
                      ALGO='Normal' if ace else 'Damped',LFOCKACE='.TRUE.' if ace else '.FALSE.',
                      LWAVE='.FALSE.',LCHARG='.FALSE.',ISIF=2))
    restart=WORK/'beta-pbe-6.6.1/WAVECAR'
    assert restart.is_file()
    shutil.copy2(restart,directory/'WAVECAR')
    execute(directory,ROOT/'macos-arm64/bin/vasp_std',1200,'6.6.1',convergence=False)

def preflight():
    # Small regular mesh and 3 samples per segment retain the Stage 04 topology.
    # This is deliberately not the full 12x12x4 / 40-samples production workload.
    directory=prepare('beta-hse-kopt-preflight',HSE,dict(ISTART=0,ICHARG=2,NCORE=1,KPAR=1,NBANDS=40,
        NELM=80,NELMIN=6,EDIFF='1E-6',ALGO='Normal',LFOCKACE='.TRUE.',LORBIT=11,
        LWAVE='.FALSE.',LCHARG='.FALSE.',ISIF=2))
    (directory/'KPOINTS').write_text('Bounded beta preflight\n0\nGamma\n3 3 2\n0 0 0\n')
    lines=PATH_REFERENCE.read_text().splitlines()
    lines[0]='Stage 04 topology; bounded three-sample preflight'
    lines[1]='3'
    (directory/'KPOINTS_OPT').write_text('\n'.join(lines)+'\n')
    result=execute(directory,ROOT/'macos-arm64/bin/vasp_std',1800,'6.6.1')
    content=(directory/'PROCAR_OPT').read_text()
    assert re.search(r'# of k-points:\s+27\b',content)
    values=[float(x) for x in re.findall(r'energy\s+([-+\d.Ee]+)',content)]
    assert len(values)==27*40 and all(math.isfinite(x) for x in values)
    print('Beta optional path: all nine reference segments; 27 points x 40 finite eigenvalues',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['pbe','damped','ace','preflight'])
    phase=parser.parse_args().phase
    if phase=='pbe':pbe()
    elif phase=='preflight':preflight()
    else:benchmark(phase=='ace')
