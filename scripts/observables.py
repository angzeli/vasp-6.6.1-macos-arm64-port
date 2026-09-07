#!/usr/bin/env python3
"""Read finished VASP results; process success alone is not convergence."""
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

def read_case(directory):
    directory = Path(directory)
    out = (directory / 'OUTCAR').read_text(errors='replace')
    tree = ET.parse(directory / 'vasprun.xml').getroot()
    calculations = tree.findall('calculation')
    if not calculations:
        raise ValueError('No completed calculation in XML')
    final = calculations[-1]
    version = tree.findtext("generator/i[@name='version']", '').strip()
    energy = float(final.findtext("energy/i[@name='e_fr_energy']"))
    forces = [[float(v) for v in row.text.split()] for row in final.findall("varray[@name='forces']/v")]
    stress = [[float(v) for v in row.text.split()] for row in final.findall("varray[@name='stress']/v")]
    if not forces or len(stress) != 3:
        raise ValueError('Missing force/stress arrays')
    if not all(math.isfinite(x) for x in [energy] + sum(forces, []) + sum(stress, [])):
        raise ValueError('Nonfinite energy, force or stress')
    if re.search(r'(?i)(?<![a-z])(?:nan|[+-]?infinity)(?![a-z])', out):
        raise ValueError('NaN/Infinity token in OUTCAR')
    params = {e.attrib['name']: (e.text or '').strip() for e in tree.findall('.//parameters//i')}
    nelect = float(params['NELECT'])
    elapsed = re.findall(r'Elapsed time \(sec\):\s*([\d.]+)', out)
    volume = float(final.findtext("structure/crystal/i[@name='volume']"))
    loops = [float(x) for x in re.findall(r'LOOP:\s+cpu time\s+[\d.]+:\s+real time\s+([\d.]+)', out)]
    return dict(version=version, energy_eV=energy, nelect=nelect, forces=forces,
                stress_kB=stress, volume_A3=volume, iterations=len(final.findall('scstep')),
                converged='aborting loop because EDIFF is reached' in out,
                normal='General timing and accounting' in out,
                elapsed_s=float(elapsed[-1]) if elapsed else None, loops_s=loops,
                params=params, max_force_eVA=max(abs(x) for x in sum(forces, [])))
