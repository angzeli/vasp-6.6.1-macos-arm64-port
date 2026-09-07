#!/usr/bin/env python3
"""Small runtime identities and finite-difference checks, not material certification."""
import argparse
import csv
from pathlib import Path
from validate import ROOT, OLD, WORK, run_case

BASE = dict(ENCUT=400, PREC='Accurate', ALGO='Normal', EDIFF='1E-8', NELM=100,
            ISMEAR=0, SIGMA=0.02, ISPIN=1, LREAL='.FALSE.', LASPH='.TRUE.',
            ISTART=0, ICHARG=2, NSW=0, IBRION=-1, ISIF=2, KPAR=1, NCORE=1,
            LWAVE='.FALSE.', LCHARG='.FALSE.')
METHODS = {
    'pbe': dict(GGA='PE'),
    'scan': dict(GGA=None, METAGGA='SCAN'),
    'r2scan': dict(GGA=None, METAGGA='R2SCAN'),
    'r2scan-rvv10': dict(GGA=None, METAGGA='R2SCAN', LUSE_VDW='.TRUE.', IVDW_NL=2, BPARAM=11.95, CPARAM=0.0093),
}

def methods():
    results = {}
    for method, tags in METHODS.items():
        results[method] = run_case('identity-'+method, edits=BASE | tags, timeout=900)
    for method in ['scan','r2scan','r2scan-rvv10']:
        assert results[method]['params']['METAGGA'].upper() == METHODS[method]['METAGGA']
        assert abs(results[method]['energy_eV'] - results['pbe']['energy_eV']) > 1e-4
    assert abs(results['r2scan']['energy_eV'] - results['scan']['energy_eV']) > 1e-5
    assert abs(results['r2scan-rvv10']['energy_eV'] - results['r2scan']['energy_eV']) > 1e-5
    assert results['r2scan-rvv10']['params']['LUSE_VDW'].upper() == 'T'
    for name in ['r2scan', 'r2scan-rvv10']:
        out=(WORK/('identity-'+name)/'OUTCAR').read_text()
        assert 'exchange-correlation table for R2SCAN' in out
    assert '-- rVV10 --' in (WORK/'identity-r2scan-rvv10/OUTCAR').read_text()

def hybrids():
    settings = BASE | dict(GGA='PE', LHFCALC='.TRUE.', HFSCREEN=0.2, AEXX=0.25, PRECFOCK='Normal')
    noace = run_case('hse-noace', edits=settings | dict(LFOCKACE='.FALSE.'), timeout=1200)
    ace = run_case('hse-ace', edits=settings | dict(LFOCKACE='.TRUE.'), timeout=1200)
    assert noace['params']['LHFCALC'].upper() == ace['params']['LHFCALC'].upper() == 'T'
    assert noace['params']['LFOCKACE'].upper() == 'F'
    assert ace['params']['LFOCKACE'].upper() == 'T'
    assert abs(noace['energy_eV'] - ace['energy_eV']) <= 1e-5
    optional = 'Small optional path\n4\nLine-mode\nReciprocal\n0 0 0 ! G\n0.5 0.5 0.5 ! L\n'
    run_case('hse-kpoints-opt', edits=settings | dict(LFOCKACE='.TRUE.', LORBIT=11), optional=optional, timeout=1200)
    directory = WORK/'hse-kpoints-opt'
    procar = directory/'PROCAR_OPT'
    assert procar.is_file() and procar.stat().st_size > 0
    import re
    content = procar.read_text()
    assert re.search(r'# of k-points:\s+4\b', content)
    values = [float(x) for x in re.findall(r'energy\s+([-+\d.Ee]+)', content)]
    import math
    assert values and all(math.isfinite(x) for x in values)
    stdout=(directory/'stdout.log').read_text()
    assert stdout.index('Start KPOINTS_OPT') > stdout.index(' 1 F=')
    print('Hybrid optional-point eigenvalues parsed:',len(values),flush=True)

def structure(displacement=0.04, strain=0.0):
    # Silicon primitive cell from the old fixture, converted to Cartesian Angstrom.
    # Apply epsilon_xx at fixed fractional coordinates, including the displaced atom.
    length = 5.43
    cell = [[0,length/2,length/2],[length/2,0,length/2],[length/2,length/2,0]]
    points = [[displacement,0,0],[length/4,length/4,length/4]]
    for row in cell + points: row[0] *= 1+strain
    fmt = lambda rows: ''.join(' '.join(f'{x:.12f}' for x in row)+'\n' for row in rows)
    return 'Displaced silicon derivative fixture\n1.0\n'+fmt(cell)+'Si\n2\nCartesian\n'+fmt(points)

def derivatives():
    settings = BASE | dict(ENCUT=700, EDIFF='1E-9', ISYM=0, ADDGRID='.TRUE.',
                           NGX=48, NGY=48, NGZ=48, NGXF=96, NGYF=96, NGZF=96)
    rows=[]
    for method in ['r2scan','r2scan-rvv10']:
        tags=settings | METHODS[method]
        base=run_case('deriv-'+method+'-base', edits=tags, poscar=structure(), timeout=1200)
        for h in [0.01,0.005]:
            lo=run_case(f'deriv-{method}-xminus-{h}', edits=tags, poscar=structure(0.04-h), timeout=1200)
            hi=run_case(f'deriv-{method}-xplus-{h}', edits=tags, poscar=structure(0.04+h), timeout=1200)
            predicted=-(hi['energy_eV']-lo['energy_eV'])/(2*h)
            analytic=base['forces'][0][0]
            rows.append([method,'force_x_eV/A',h,analytic,predicted,abs(analytic-predicted),0.003])
        for h in [0.001,0.0005]:
            lo=run_case(f'deriv-{method}-strainminus-{h}', edits=tags, poscar=structure(strain=-h), timeout=1200)
            hi=run_case(f'deriv-{method}-strainplus-{h}', edits=tags, poscar=structure(strain=h), timeout=1200)
            # VASP stress is positive in compression. 1 eV/A^3 = 1602.1766208 kbar.
            predicted=-(hi['energy_eV']-lo['energy_eV'])/(2*h*base['volume_A3'])*1602.1766208
            analytic=base['stress_kB'][0][0]
            rows.append([method,'stress_xx_kbar',h,analytic,predicted,abs(analytic-predicted),0.5])
    path=ROOT/'validation/reports/derivatives.tsv'
    with path.open('w',newline='') as handle:
        writer=csv.writer(handle,delimiter='\t')
        writer.writerow(['method','observable','step','analytic','finite_difference','absolute_error','tolerance','result'])
        for row in rows:
            writer.writerow(row+['PASS' if row[-2] <= row[-1] else 'FAIL'])
    for row in rows:print(row,flush=True)
    assert all(row[-2] <= row[-1] for row in rows), 'Derivative tolerance exceeded; do not certify'

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['methods','hybrids','derivatives'])
    args=parser.parse_args()
    {'methods':methods,'hybrids':hybrids,'derivatives':derivatives}[args.phase]()
