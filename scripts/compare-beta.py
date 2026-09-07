#!/usr/bin/env python3
"""Compare native beta PBE results with explicit units and finite tolerances."""
import csv
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from observables import read_case
from validate import ROOT, WORK

old=WORK/'beta-pbe-5.4.4'
new=WORK/'beta-pbe-6.6.1'
for name in ['POSCAR','POTCAR','KPOINTS']:
    assert (old/name).read_bytes()==(new/name).read_bytes()
assert [int(x) for x in (new/'POSCAR').read_text().splitlines()[6].split()]==[4,2,1]

def gap(directory):
    root=ET.parse(directory/'vasprun.xml').getroot()
    rows=root.findall("calculation/eigenvalues/array/set/set/set/r")
    occupied=[];empty=[]
    for row in rows:
        energy,occupation=map(float,row.text.split())
        (occupied if occupation>0.5 else empty).append(energy)
    return max(0.0,min(empty)-max(occupied))

a=read_case(old);b=read_case(new)
assert a['converged'] and b['converged'] and a['normal'] and b['normal']
rows=[]
for label,va,vb,tolerance in [
    ('energy_eV_per_formula_unit',a['energy_eV'],b['energy_eV'],1e-4),
    ('electron_count',a['nelect'],b['nelect'],0),
    ('mesh_gap_eV',gap(old),gap(new),0.001),
    ('pressure_kbar',sum(a['stress_kB'][i][i] for i in range(3))/3,sum(b['stress_kB'][i][i] for i in range(3))/3,0.1),
]: rows.append([label,va,vb,abs(vb-va),tolerance])
force_delta=max(abs(x-y) for ar,br in zip(a['forces'],b['forces']) for x,y in zip(ar,br))
stress_delta=max(abs(x-y) for ar,br in zip(a['stress_kB'],b['stress_kB']) for x,y in zip(ar,br))
rows += [['maximum_force_difference_eV_per_A',0,force_delta,force_delta,0.001],
         ['maximum_stress_difference_kbar',0,stress_delta,stress_delta,0.1]]
def resolved(directory, result, tag):
    # VASP 5 omits IVDW from XML; both releases report the resolved cutoff in OUTCAR.
    if tag=='GGA':
        out=(directory/'OUTCAR').read_text()
        values=re.findall(r'^\s*GGA\s*=\s*(\w+)\s+(?:GGA type|functional components)',out,re.M)
        assert values, 'Missing resolved GGA functional'
        return values[-1]
    if tag in ['ENCUT', 'IVDW']:
        out=(directory/'OUTCAR').read_text()
        suffix=r'\s+eV' if tag=='ENCUT' else r'\b'
        values=re.findall(r'^\s*'+tag+r'\s*=\s*([-+\d.Ee]+)'+suffix,out,re.M)
        assert values, f'Missing resolved {tag}'
        return float(values[-1])
    value=result['params'][tag]
    return float(value)

for tag in ['ENCUT','NBANDS','ISYM','ISPIN','GGA','IVDW','ISMEAR','NELECT']:
    assert resolved(old,a,tag)==resolved(new,b,tag), f'Resolved {tag} differs'
for name in [old,new]:
    text=(name/'OUTCAR').read_text()
    print(name.name,'space-group operation counts',re.findall(r'Found\s+(\d+) space group operations',text),
          'irreducible k points',re.findall(r'NKPTS\s*=\s*(\d+)',text)[:1])
with (ROOT/'validation/reports/beta-comparison.tsv').open('w',newline='') as handle:
    writer=csv.writer(handle,delimiter='\t')
    writer.writerow(['observable','VASP_5.4.4','VASP_6.6.1','absolute_difference','tolerance','result'])
    for row in rows:
        writer.writerow(row+['PASS' if row[-2]<=row[-1] else 'FAIL'])
        print(row,flush=True)
assert all(row[-2]<=row[-1] for row in rows), 'Cross-version numerical tolerance exceeded'
