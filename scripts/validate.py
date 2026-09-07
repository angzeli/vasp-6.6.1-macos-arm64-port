#!/usr/bin/env python3
"""Sequential small-fixture gates; calculations are exclusively private."""
import argparse
import csv
from pathlib import Path
import shutil
import subprocess
import time
from observables import read_case

ROOT = Path(__file__).resolve().parent.parent
OLD = Path('/Applications/Academic/vasp.5.4.4/macos-arm64/validation')
WORK = ROOT / 'private/validation'
TABLE = ROOT / 'validation/reports/results.tsv'
FIELDS = ['case', 'variant', 'ranks', 'version', 'exit', 'converged', 'normal',
          'energy_eV', 'nelect', 'iterations', 'max_force_eVA', 'sxx_kB',
          'elapsed_s', 'wall_s', 'status']

def record(name, variant, ranks, status, wall, result):
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    row = dict(case=name, variant=variant, ranks=ranks, exit=status, wall_s=f'{wall:.3f}')
    row.update({k: result.get(k, '') for k in FIELDS if k in result})
    row['sxx_kB'] = result.get('stress_kB', [['']])[0][0]
    row['status'] = 'PASS' if status == 0 and result.get('normal') and result.get('converged') and result.get('version') == '6.6.1' else 'FAIL'
    exists = TABLE.exists()
    with TABLE.open('a', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter='\t')
        if not exists: writer.writeheader()
        writer.writerow(row)
    print('\t'.join(str(row.get(k, '')) for k in FIELDS), flush=True)
    return row['status'] == 'PASS'

def run_case(name, variant='std', ranks=2, source=None, edits=None, kpoints=None, poscar=None,
             optional=None, timeout=600, require=True):
    directory = WORK / name
    directory.mkdir(parents=True, exist_ok=False)
    source = source or OLD / 'std-scf-r1'
    for f in ['INCAR', 'POSCAR', 'POTCAR', 'KPOINTS']:
        shutil.copy2(source / f, directory / f)
    if edits:
        settings = {}
        for line in (directory/'INCAR').read_text().splitlines():
            line = line.split('#')[0].split('!')[0]
            if '=' in line:
                key, value = line.split('=', 1); settings[key.strip().upper()] = value.strip()
        for key, value in edits.items():
            if value is None: settings.pop(key, None)
            else: settings[key] = str(value)
        (directory/'INCAR').write_text(''.join(f'{k} = {v}\n' for k,v in settings.items()))
    if kpoints: (directory/'KPOINTS').write_text(kpoints)
    if poscar: (directory/'POSCAR').write_text(poscar)
    if optional: (directory/'KPOINTS_OPT').write_text(optional)
    mode = (ROOT/'private/mpi-mode.txt').read_text().strip()
    command = [str(ROOT/'scripts/run-mpi.sh'), '--ranks', str(ranks), '--mode', mode,
               '--timeout', str(timeout), '--', str(ROOT/f'macos-arm64/bin/vasp_{variant}')]
    started = time.monotonic()
    with (directory/'stdout.log').open('w') as handle:
        status = subprocess.run(command, cwd=directory, stdout=handle, stderr=subprocess.STDOUT).returncode
    result = {}
    try: result = read_case(directory)
    except Exception as error: print(f'{name}: parse failure: {error}', flush=True)
    passed = record(name, variant, ranks, status, time.monotonic()-started, result)
    if require and not passed: raise RuntimeError(f'{name} failed; inspect its private output')
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['std', 'gam', 'ncl'])
    phase = parser.parse_args().phase
    if phase == 'std':
        results = [run_case(f'std-pbe-r{n}', ranks=n) for n in [1,2,4,8]]
        assert max(x['energy_eV'] for x in results)-min(x['energy_eV'] for x in results) <= 1e-6
        assert len(set(x['nelect'] for x in results)) == 1
    elif phase == 'gam':
        source = OLD/'gam-scf-r2'
        standard = run_case('std-gamma-r2', source=source)
        gamma = run_case('gam-pbe-r2', variant='gam', source=source)
        assert abs(standard['energy_eV']-gamma['energy_eV']) <= 1e-6
    else:
        result = run_case('ncl-soc-r2', variant='ncl', source=OLD/'ncl-soc-r2')
        assert result['params']['LSORBIT'].upper() == 'T'
