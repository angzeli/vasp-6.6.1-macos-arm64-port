#!/usr/bin/env python3
"""Local, immutable-input VASP runner. Standard library only; no scheduler."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import math
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import stat
import struct
import subprocess
import sys

import launch
from observables import read_case

ROOT = Path(__file__).resolve().parent.parent
PROTECTED = Path('/Applications/Academic').resolve()
REQUIRED = ('INCAR', 'POSCAR', 'POTCAR', 'KPOINTS')
RESTARTS = {'none': (), 'wavecar': ('WAVECAR',), 'chgcar': ('CHGCAR',), 'both': ('WAVECAR', 'CHGCAR')}
RESERVED = set(REQUIRED) | {'KPOINTS_OPT', 'WAVECAR', 'CHGCAR', 'TMPCAR', 'TAUCAR',
    'OUTCAR', 'OSZICAR', 'CONTCAR', 'STOPCAR', 'IBZKPT', 'EIGENVAL', 'DOSCAR', 'PROCAR',
    'CHG', 'XDATCAR', 'PCDAT', 'LOCPOT', 'REPORT', 'VASPRUN.XML', 'VASPOUT.H5',
    'RUN_METADATA.TXT', 'STDOUT.LOG', 'STDERR.LOG'}


class PreflightError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PreflightError(message)


def number(value):
    try:
        result = float(value.replace('D', 'E').replace('d', 'e'))
    except (ValueError, AttributeError):
        raise PreflightError(f'Expected a finite number, got {value!r}') from None
    require(math.isfinite(result), 'Nonfinite numeric input is unsupported')
    return result


def integer(value):
    result = number(str(value))
    require(result.is_integer(), f'Expected an integer, got {value!r}')
    return int(result)


def canonical(value):
    value = ' '.join(value.upper().split())
    if value in ('T', '.TRUE.', 'TRUE'): return True
    if value in ('F', '.FALSE.', 'FALSE'): return False
    try: return ('number', number(value))
    except PreflightError: return ('text', value)


class Incar:
    """Span-based edits preserve everything except replaced parallel assignments.

    Supported: plain tag=value, #/! comments, semicolons, backslash continuations.
    Quoted/nested syntax and assignments without separators fail closed.
    """
    def __init__(self, text):
        self.text, self.entries = text, []
        masked = list(text)
        offset = 0
        for line in text.splitlines(keepends=True):
            comment = re.search(r'[#!]', line)
            end = comment.start() if comment else len(line.rstrip('\r\n'))
            for i in range(end, len(line.rstrip('\r\n'))): masked[offset+i] = ' '
            active = line[:end].rstrip()
            if active.endswith('\\'):
                begin = offset + len(active) - 1
                for i in range(begin, offset+len(line)): masked[i] = ' '
            offset += len(line)
        active = ''.join(masked)
        require(not re.search(r"[\"'{}\[\]()]", active), 'Quoted/nested INCAR syntax is unsupported; use ordinary unquoted assignments')
        for match in re.finditer(r'[^;\r\n]+', active):
            part = match.group()
            if not part.strip(): continue
            found = re.fullmatch(r'\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*?)\s*', part)
            require(found is not None and found.group(2) and '=' not in found.group(2),
                    'Malformed INCAR assignment or missing semicolon; no input was changed')
            self.entries.append((found.group(1).upper(), found.group(2),
                                 match.start()+found.start(1), match.start()+found.end(2)))
        for tag in {e[0] for e in self.entries} - {'NCORE', 'KPAR', 'NPAR'}:
            self.get(tag)  # reject ambiguous duplicate scientific controls

    def values(self, tag):
        return [v for key, v, _, _ in self.entries if key == tag]

    def get(self, tag, default=None):
        values = self.values(tag)
        require(not values or len({str(canonical(v)) for v in values}) == 1,
                f'Conflicting duplicate {tag} assignments; resolve them in the input')
        return values[0] if values else default

    def int(self, tag, default): return integer(self.get(tag, str(default)))
    def real(self, tag, default): return number(self.get(tag, str(default)))

    def flag(self, tag, default=False):
        value = canonical(self.get(tag, '.TRUE.' if default else '.FALSE.'))
        require(isinstance(value, bool), f'{tag} must be a logical value')
        return value

    def parallel(self, ncore, kpar):
        require(not self.values('NPAR') or ncore is not None,
                'NPAR is present: explicitly supply --ncore to replace it, or resolve the legacy input')
        values, origins = {}, {}
        for tag, cli in [('NCORE', ncore), ('KPAR', kpar)]:
            original = self.get(tag) if cli is None else None
            values[tag] = integer(cli if cli is not None else original or '1')
            origins[tag] = 'CLI' if cli is not None else 'INCAR' if original is not None else 'default 1'
        spans = [(a,b) for tag, _, a,b in self.entries if tag in {'NCORE','KPAR','NPAR'}]
        edited = self.text
        for a,b in sorted(spans, reverse=True): edited = edited[:a]+edited[b:]
        edited += f"\n# Parallel controls resolved by local run-vasp\nNCORE = {values['NCORE']}\nKPAR = {values['KPAR']}\n"
        changes = [f"{t}: {self.values(t) or ['absent']} -> {values[t]} ({origins[t]})" for t in values]
        if self.values('NPAR'): changes.append(f"NPAR removed by explicit --ncore: {self.values('NPAR')}")
        return values, origins, edited, changes


def cross(a,b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def dot(a,b): return sum(x*y for x,y in zip(a,b))


def structure(handle):
    """Read a named-species POSCAR header, leaving a CHGCAR stream at its body."""
    require(bool(handle.readline()), 'Missing structure title')
    scales = handle.readline().split()
    require(len(scales) == 1, 'Only a single POSCAR scale factor is supported')
    scale = number(scales[0])
    cell = [[number(x) for x in handle.readline().split()] for _ in range(3)]
    require(all(len(v)==3 for v in cell), 'Malformed lattice vectors')
    determinant = dot(cell[0],cross(cell[1],cell[2]))
    require(abs(determinant)>1e-12 and scale != 0, 'Singular lattice or zero POSCAR scale')
    scale = (-scale/abs(determinant))**(1/3) if scale < 0 else scale
    cell = [[x*scale for x in row] for row in cell]
    species = handle.readline().split()
    require(species and all(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', x) for x in species),
            'A VASP-5-style POSCAR with named species is required')
    counts = [integer(x) for x in handle.readline().split()]
    require(len(counts)==len(species) and all(x>0 for x in counts), 'Invalid species counts')
    mode = handle.readline().strip().lower()
    if mode.startswith('s'): mode=handle.readline().strip().lower()
    require(mode.startswith(('d','c','k')), 'POSCAR coordinate mode must be Direct or Cartesian')
    positions=[]
    determinant=dot(cell[0],cross(cell[1],cell[2]))
    for _ in range(sum(counts)):
        row=handle.readline().split()
        require(len(row)>=3, 'Truncated atomic coordinates')
        xyz=[number(x) for x in row[:3]]
        if not mode.startswith('d'):
            cart=[x*scale for x in xyz]
            xyz=[dot(cart,cross(cell[(i+1)%3],cell[(i+2)%3]))/determinant for i in range(3)]
        positions.append(xyz)
    return dict(cell=cell, species=species, counts=counts, positions=positions)


def same_structure(a,b):
    require(a['species']==b['species'] and a['counts']==b['counts'], 'Restart species/order/counts differ')
    require(max(abs(x-y) for r,s in zip(a['cell'],b['cell']) for x,y in zip(r,s)) <= 1e-7,
            'Restart cell differs; this initial runner supports matching-cell reuse')
    require(max(abs((x-y)-round(x-y)) for r,s in zip(a['positions'],b['positions']) for x,y in zip(r,s)) <= 1e-7,
            'Restart sites differ; provide the intended matching POSCAR explicitly (CONTCAR is never inherited)')


def kpoints(text, optional=False):
    raw=text.splitlines()
    require(len(raw)>=4, 'Truncated KPOINTS file')
    lines=[re.split(r'[#!]',line,maxsplit=1)[0].strip() for line in raw]
    count=integer(lines[1]);mode=lines[2].lower()
    if mode.startswith('l'):
        require(count>=2 and lines[3].lower().startswith(('r','c')), 'Invalid Line-mode sampling/coordinate mode')
        points=[]
        for line in lines[4:]:
            if line:
                xyz=[number(x) for x in line.split()]
                require(len(xyz)==3, 'Line-mode endpoints must contain three coordinates (labels need # or !)')
                points.append(xyz)
        require(len(points)>=2 and len(points)%2==0, 'Line-mode requires endpoint pairs')
        return dict(kind='line', count=count*len(points)//2, gamma=False, signature=(count,lines[3].lower(),points))
    require(not optional, 'Active KPOINTS_OPT currently supports Line-mode only')
    if count==0:
        require(mode.startswith(('g','m')), 'Only automatic Gamma/Monkhorst meshes are supported')
        mesh=[integer(x) for x in lines[3].split()]
        require(len(mesh)==3 and all(x>0 for x in mesh), 'Invalid automatic mesh')
        tail=[x for x in lines[4:] if x]
        require(len(tail)<=1, 'Unexpected automatic KPOINTS records')
        shift=[number(x) for x in tail[0].split()] if tail else [0.,0.,0.]
        require(len(shift)==3, 'Invalid k-point shift')
        gamma=mesh==[1,1,1] and all(abs(x-round(x))<1e-12 for x in shift)
        return dict(kind='automatic', count=math.prod(mesh), gamma=gamma, signature=(mode[0],mesh,shift))
    require(count>0 and mode.startswith(('r','c','k')), 'Unsupported KPOINTS representation')
    data=[line.split() for line in lines[3:] if line]
    require(len(data)==count and all(len(row)==4 for row in data), 'Explicit KPOINTS needs count rows with coordinates and weight')
    rows=[[number(x) for x in row] for row in data]
    require(all(row[3]>=0 for row in rows) and any(row[3]>0 for row in rows), 'Invalid k-point weights')
    gamma=count==1 and all(abs(x)<1e-12 for x in rows[0][:3])
    return dict(kind='explicit',count=count,gamma=gamma,signature=(mode[0],rows))


def regular(path, empty=False):
    require(path.exists() and stat.S_ISREG(path.lstat().st_mode), f'Required regular file missing or symlinked: {path}')
    require(empty or path.stat().st_size>0, f'Empty required file: {path}')
    return path


def identity(path):
    s=path.stat()
    return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)


def digest(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()


def binary_identity(variant):
    require(platform.system()=='Darwin' and platform.machine()=='arm64', 'run-vasp requires native Darwin/arm64')
    binary=regular(ROOT/'macos-arm64/bin'/('vasp_'+variant))
    require(os.access(binary,os.X_OK), 'Selected VASP binary is not executable')
    description=subprocess.check_output(['/usr/bin/file','-b',str(binary)],text=True)
    require('Mach-O' in description and 'arm64' in description, 'Selected binary lacks an arm64 Mach-O slice')
    manifest={name:sha for sha,name in (line.split() for line in (ROOT/'provenance/binary-sha256.txt').read_text().splitlines())}
    sha=digest(binary)
    require(manifest.get(str(binary.relative_to(ROOT)))==sha, 'Binary SHA-256 does not match the recorded validated build')
    require('VASP source self-identity: 6.6.1' in (ROOT/'provenance/build-info.txt').read_text(), 'Missing recorded VASP 6.6.1 identity')
    return binary,sha


def charge_header(path, target, electrons, spin):
    """Stream density and augmentation blocks once; no full-file in-memory copy."""
    with path.open() as f:
        same_structure(structure(f),target)
        blocks=0; grid=None; total=0.; augmentations=0
        for line in f:
            if not line.strip(): continue
            aug=re.fullmatch(r'\s*augmentation occupancies\s+\d+\s+(\d+)\s*',line)
            if aug:
                remaining=int(aug.group(1));augmentations+=1
                while remaining:
                    row=f.readline().split();require(row, 'Truncated CHGCAR augmentation')
                    for token in row: number(token)
                    remaining-=len(row);require(remaining>=0, 'Malformed CHGCAR augmentation count')
                continue
            fields=line.split()
            require(len(fields)==3 and all(re.fullmatch(r'\d+',v) for v in fields), 'Unsupported/truncated CHGCAR block')
            current=[int(x) for x in fields]
            require(all(x>0 for x in current) and (grid is None or grid==current), 'Inconsistent CHGCAR grid')
            grid=current;remaining=math.prod(grid);blocksum=0.
            while remaining:
                row=f.readline().split();require(row, 'Truncated CHGCAR density')
                blocksum+=sum(number(x) for x in row);remaining-=len(row)
                require(remaining>=0, 'Malformed CHGCAR density count')
            if blocks==0: total=blocksum/math.prod(grid)
            blocks+=1
        require(blocks==spin and augmentations>=sum(target['counts'])*blocks, 'Missing CHGCAR spin/augmentation blocks')
        require(abs(total-electrons)<=1e-3, f'CHGCAR electron integral {total:.6f} differs from target {electrons:.6f}')
    return f'cell/sites, {blocks} density blocks, augmentation counts and electron integral checked; PAW completeness beyond stored channels not certified'


def wave_header(path, target, incar, spin):
    with path.open('rb') as f:
        first=f.read(24);require(len(first)==24, 'Truncated WAVECAR header')
        recl,nspin,tag=map(integer,struct.unpack('<3d',first))
        require(104<=recl<=2**30 and nspin in (1,2) and tag in (45200,45210), 'Unsupported WAVECAR format; only little-endian 45200/45210 collinear records are checked')
        require(nspin==spin, 'WAVECAR spin count differs from target')
        f.seek(recl);raw=f.read(104);require(len(raw)==104, 'Truncated WAVECAR second record')
        values=struct.unpack('<13d',raw);nk,nb=map(integer,values[:2]);cutoff=number(str(values[2]))
        require(nk>0 and nb>0 and cutoff>0, 'Invalid WAVECAR dimensions')
        require(path.stat().st_size%recl==0 and path.stat().st_size >= (2+nspin*nk*(nb+1))*recl, 'Obviously truncated WAVECAR records')
        cell=[list(values[3+i*3:6+i*3]) for i in range(3)]
        require(max(abs(x-y) for a,b in zip(cell,target['cell']) for x,y in zip(a,b))<=1e-7, 'WAVECAR lattice differs')
        if incar.get('ENCUT') is not None: require(abs(incar.real('ENCUT',cutoff)-cutoff)<1e-6, 'WAVECAR cutoff differs; this runner requires matching cutoff')
        if incar.get('NBANDS') is not None: require(incar.int('NBANDS',nb)==nb, 'WAVECAR band count differs from explicit NBANDS')
        require(recl>=8*(4+3*nb), 'WAVECAR metadata record is too short')
        for i in range(nspin*nk):
            f.seek((2+i*(nb+1))*recl);raw=f.read(32)
            require(len(raw)==32, 'Truncated WAVECAR k-point header')
            row=struct.unpack('<4d',raw);npw=integer(row[0])
            require(npw>0 and npw*(8 if tag==45200 else 16)<=recl and all(math.isfinite(x) for x in row), 'Invalid WAVECAR coefficient record dimensions')
    return f'record lengths, {nk} k points, {nb} bands, spin/cell/cutoff checked; coefficients and general wavefunction compatibility NOT ASSESSED'


def parser():
    p=argparse.ArgumentParser(description='Stage a NEW local VASP execution directory; no scheduler, retries or in-place resume.')
    p.add_argument('--input',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--binary',choices=('std','gam','ncl'),default='std')
    p.add_argument('--ranks',type=int,default=1)
    p.add_argument('--ncore',type=int)
    p.add_argument('--kpar',type=int)
    p.add_argument('--mpi-mode',choices=('synthetic','native'),default='synthetic')
    p.add_argument('--restart',choices=tuple(RESTARTS),default='none')
    p.add_argument('--restart-from',type=Path)
    p.add_argument('--timeout',type=float,help='positive execution budget; required for real launch')
    p.add_argument('--stop-before',type=float,default=0,help='request STOPCAR this many seconds before hard timeout')
    p.add_argument('--extra-input',action='append',default=[],metavar='BASENAME')
    p.add_argument('--dry-run',action='store_true')
    return p


def plan(args):
    require(1<=args.ranks<=8, 'Supported rank range is 1..8')
    require(args.timeout is not None or args.dry_run, 'A real launch requires explicit --timeout SECONDS')
    require(args.timeout is None or math.isfinite(args.timeout) and args.timeout>0, '--timeout must be positive and finite')
    require(math.isfinite(args.stop_before) and args.stop_before>=0 and
            (args.stop_before==0 or args.timeout is not None and args.stop_before<args.timeout), '--stop-before must be nonnegative and smaller than --timeout')
    require(args.restart!='none' or args.restart_from is None, '--restart-from is invalid with --restart none')
    source=args.input.expanduser().resolve(strict=True)
    require(source.is_dir(), '--input must be an existing directory')
    raw=args.output.expanduser().absolute()
    require(not os.path.lexists(raw), 'Output already exists, including an empty directory or symlink')
    output=raw.resolve()
    donor=(args.restart_from or source).expanduser().resolve(strict=True) if args.restart!='none' else None
    for label,path in [('input',source),('restart donor',donor)]:
        if path is None: continue
        require(path.is_dir(), f'{label} must be a directory')
        require(not (output==path or output.is_relative_to(path) or path.is_relative_to(output)), f'Unsafe output overlap with {label}')
    require(not output.is_relative_to(PROTECTED), 'Output cannot be inside an Academic installation/source tree')
    require(not output.is_relative_to(ROOT) or output.is_relative_to(ROOT/'private'), 'Outputs inside the port repository must be under ignored private/')
    require(output.parent.is_dir() and os.access(output.parent,os.W_OK|os.X_OK), 'Output parent must already exist and be writable')
    for path in (source,output,donor):
        require(path is None or not any(ord(c)<32 for c in str(path)), 'Control characters in directory paths are unsupported')
    files={name:regular(source/name) for name in REQUIRED}
    snapshots={name:identity(path) for name,path in files.items()}
    incar=Incar(files['INCAR'].read_text())
    parallel,origins,effective,changes=incar.parallel(args.ncore,args.kpar)
    nc,kp=parallel['NCORE'],parallel['KPAR']
    require(nc>0 and kp>0 and args.ranks%kp==0 and (args.ranks//kp)%nc==0, 'Require ranks % KPAR == 0 and (ranks / KPAR) % NCORE == 0, with positive values')
    require(incar.int('IMAGES',0)==0, 'Multi-image inputs are unsupported')
    for tag in ('NCORE_IN_IMAGE1','NOMEGAPAR','NTAUPAR','NPAR_X','NPAR_Y','NCSHMEM','ICHAIN'):
        require(not incar.values(tag), f'Additional decomposition {tag} is not supported by this single-image runner')
    require(not incar.flag('LCLIMB'), 'NEB/multi-image workflows are unsupported')
    soc=incar.flag('LSORBIT');noncol=incar.flag('LNONCOLLINEAR',soc)
    require(not (soc or noncol) or args.binary=='ncl', 'SOC/noncollinear inputs require --binary ncl')
    spin=incar.int('ISPIN',1);require(spin in (1,2), 'ISPIN must be 1 or 2')
    main=kpoints(files['KPOINTS'].read_text());warnings=[]
    require(args.binary!='gam' or main['gamma'], 'vasp_gam requires a genuinely Gamma-only main KPOINTS')
    opt=source/'KPOINTS_OPT';active=opt.exists() and incar.flag('LKPOINTS_OPT',True)
    if opt.exists():
        files['KPOINTS_OPT']=regular(opt,empty=not active)
        snapshots['KPOINTS_OPT']=identity(opt)
    if not opt.exists(): require(not incar.flag('LKPOINTS_OPT',False), 'LKPOINTS_OPT is enabled but KPOINTS_OPT is missing')
    hybrid=incar.flag('LHFCALC')
    if active:
        require(args.binary!='gam', 'Active KPOINTS_OPT is unsupported by vasp_gam')
        require(main['kind']=='automatic', 'Active KPOINTS_OPT requires an automatic uniform main mesh; explicit/Line-mode main inputs are unsupported')
        kpoints(opt.read_text(),optional=True)
        require(not hybrid or nc==1, 'Hybrid KPOINTS_OPT requires NCORE=1')
        if hybrid and incar.real('HFRCUT',0)==0: warnings.append('Hybrid KPOINTS_OPT with omitted/default HFRCUT: review the method; no value was changed.')
    elif opt.exists(): warnings.append('KPOINTS_OPT is staged but disabled by LKPOINTS_OPT=.FALSE.; optional syntax is not activated.')
    if hybrid and incar.get('ALGO','Normal').lower() in ('damped','all'): warnings.append('Hybrid ALGO=Damped/All: ACE acceleration is not established; algorithm unchanged.')
    if main['kind']=='automatic' and incar.int('ISYM',2)==0: warnings.append('ISYM=0: previous symmetry-reduced IBZ counts cannot be assumed.')
    if kp>1: warnings.append('KPAR>1 passes divisibility only; performance and method-specific known issues need separate validation.')
    istart=incar.int('ISTART',1 if 'WAVECAR' in RESTARTS[args.restart] else 0)
    icharg=incar.int('ICHARG',0 if istart else 2)
    require(not hybrid or icharg<10, 'Fixed-charge hybrid calculations, including ICHARG=11, are unsupported')
    policies={'none':(0,{0,2}),'wavecar':(1,{0,2}),'chgcar':(0,{1,11}),'both':(1,{1,11})}
    expected,charges=policies[args.restart]
    require(istart==expected and icharg in charges,
            f'--restart {args.restart} requires ISTART={expected}, ICHARG in {sorted(charges)}; edit scientific inputs explicitly, not through this runner')
    require(not (icharg==11 and (incar.get('METAGGA','NONE').upper() not in ('NONE','--') or incar.flag('LDAU'))), 'Frozen-density meta-GGA/DFT+U reuse is outside this initial restart contract')
    with files['POSCAR'].open() as f: target=structure(f)
    zvals=[number(v) for v in re.findall(r'\bZVAL\s*=\s*([-+\d.EeDd]+)',files['POTCAR'].read_text(errors='strict'))]
    require(len(zvals)==len(target['counts']), 'Cannot establish POTCAR valence counts for the named species')
    electrons=incar.real('NELECT',sum(z*n for z,n in zip(zvals,target['counts'])))
    require(electrons>0, 'NELECT must be positive')
    checks=[]
    if donor:
        require(not (soc or noncol), 'Noncollinear/SOC restart compatibility is not supported yet; fresh ncl runs are supported')
        if (donor/'POSCAR').exists():
            with regular(donor/'POSCAR').open() as f: same_structure(structure(f),target)
        else: warnings.append('Donor POSCAR unavailable; WAVECAR has no site/species metadata.')
        if (donor/'INCAR').exists():
            old=Incar(regular(donor/'INCAR').read_text())
            require(old.int('ISPIN',1)==spin and not old.flag('LSORBIT') and not old.flag('LNONCOLLINEAR'), 'Donor spin setup differs')
        if (donor/'OUTCAR').exists():
            with regular(donor/'OUTCAR').open() as f: header=f.read(2_000_000)
            found=re.findall(r'NELECT\s*=\s*([-+\d.]+)\s+total number',header)
            if found: require(abs(number(found[-1])-electrons)<1e-5, 'Donor electron count differs')
        for name in RESTARTS[args.restart]:
            files[name]=regular(donor/name)
            snapshots[name]=identity(files[name])
        if (donor/'POTCAR').exists():
            require(digest(regular(donor/'POTCAR'))==digest(files['POTCAR']), 'Donor POTCAR differs; potential compatibility is not inferred')
        if 'WAVECAR' in files:
            checks.append(wave_header(files['WAVECAR'],target,incar,spin))
            if (donor/'KPOINTS').exists():
                require(kpoints(regular(donor/'KPOINTS').read_text())['signature']==main['signature'], 'WAVECAR donor main k-point selection differs; CHGCAR-only reuse permits k-point changes')
            else: warnings.append('Donor KPOINTS unavailable; wavefunction k-point compatibility awaits VASP.')
        if 'CHGCAR' in files: checks.append(charge_header(files['CHGCAR'],target,electrons,spin))
        warnings.append('Restart headers are checked, not a general compatibility proof. Runtime acceptance must be inspected; no functional-equality restriction is imposed on initial orbitals.')
    for name in args.extra_input:
        require(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_. -]*',name) is not None and name not in ('.','..'), '--extra-input needs a plain basename without traversal or shell syntax')
        require(name.upper() not in RESERVED and not any(name.upper().startswith(x+'.') for x in RESERVED)
                and Path(name).suffix.lower() not in ('.sh','.zsh','.py','.pbs','.slurm'), 'Reserved/restart/output/script file cannot be supplied through --extra-input')
        require(name not in files, 'Duplicate --extra-input name')
        files[name]=regular(source/name)
        snapshots[name]=identity(files[name])
    binary,sha=binary_identity(args.binary)
    require(all(identity(path)==snapshots[name] for name,path in files.items()), 'An input changed during preflight; retry with immutable inputs')
    sizes=snapshots
    needed=sum(s[2] for s in sizes.values())+len(effective.encode())+65536
    require(shutil.disk_usage(output.parent).free>=needed, 'Insufficient free space to stage selected files (runtime output needs additional space)')
    command,env=launch.mpi_command([str(binary)],args.ranks,args.mpi_mode)
    return dict(args=args,source=source,output=output,donor=donor,files=files,identities=sizes,
                incar=incar,effective=effective,changes=changes,parallel=parallel,origins=origins,
                binary=binary,sha=sha,binary_stat=identity(binary),command=command,env=env,bytes=needed,warnings=warnings,
                restart_checks=checks,active_opt=active,istart=istart,icharg=icharg,electrons=electrons)


def git_identity(path):
    if path is None or path.is_relative_to(PROTECTED): return 'NOT ASSESSED (no eligible repository)'
    for parent in (path,*path.parents):
        if (parent/'.git').exists():
            env=os.environ.copy();env['GIT_OPTIONAL_LOCKS']='0'
            commit=subprocess.check_output(['git','-C',str(parent),'rev-parse','HEAD'],env=env,text=True).strip()
            dirty=bool(subprocess.check_output(['git','-C',str(parent),'status','--porcelain','--untracked-files=normal'],env=env,text=True).strip())
            return f'{commit}; dirty={dirty}; root={parent}; ignored inputs are identified separately'
    return 'not in a Git repository'


def describe(p):
    a=p['args']
    print(f"Input: {p['source']}\nOutput (new): {p['output']}\nBinary: {p['binary']}\nSHA-256: {p['sha']}\nRequested version: 6.6.1")
    print('MPI command:',shlex.join(p['command']))
    print(f'MPI mode: {a.mpi_mode}; ranks={a.ranks}; timeout={a.timeout if a.timeout is not None else "NOT SET; required for execution"}; stop-before={a.stop_before}')
    print('Environment:',{k:p['env'].get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','OMPI_FC','HWLOC_SYNTHETIC')})
    print('Stage only:',', '.join(f'{n} ({s[2]} bytes)' for n,s in p['identities'].items()))
    print(f"Staging space estimate: {p['bytes']} bytes; additional runtime output space is not estimated")
    print(f"Restart: {a.restart}; donor={p['donor']}; ISTART={p['istart']}; ICHARG={p['icharg']}; KPOINTS_OPT active={p['active_opt']}")
    for line in p['changes']: print('INCAR change:',line)
    for line in p['restart_checks']: print('Restart preflight:',line)
    for line in p['warnings']: print('WARNING:',line)


def output_evidence(p):
    out=p['output'];pieces=[]
    for name in ('stdout.log','stderr.log','OUTCAR'):
        path=out/name
        if path.exists():
            with path.open(errors='replace') as f:
                head=f.read(2_000_000)
                f.seek(0,2);end=f.tell();f.seek(max(0,end-256000));tail=f.read()
            pieces.append(head+'\n'+tail)
    text='\n'.join(pieces)
    versions=set(re.findall(r'\bvasp[.\s]+(\d+\.\d+\.\d+)\b',text,re.I))
    data={'observed_version':','.join(sorted(versions)) or 'UNKNOWN',
          'normal_footer':'General timing and accounting' in text,
          'scientific_convergence':'NOT ASSESSED', 'restart_observed':'not requested'}
    rejected=False
    if p['args'].restart!='none':
        observations=[]
        if 'WAVECAR' in p['files']:
            bad=bool(re.search(r'WAVECAR\s+(?:not (?:read|found)|is not)|(?:error|invalid|incompatible)[^\n]*WAVECAR',text,re.I))
            starts=re.findall(r'ISTART\s*=\s*(\d+)\s+job\s*:',text)
            bad=bad or bool(starts and starts[-1]=='0')
            accepted=bool(re.search(r'WAVECAR file was read successfully|WAVECAR successfully read',text,re.I))
            observations.append('WAVECAR '+('REJECTED / fresh-start fallback' if bad else 'ACCEPTED' if accepted else 'UNKNOWN'))
            rejected |= bad
        if 'CHGCAR' in p['files']:
            accepted=bool(re.search(r'charge[- ]density (?:read|was read)|charge.*read from file|read.*charge.*file',text,re.I))
            observations.append('CHGCAR '+('ACCEPTED' if accepted else 'UNKNOWN; requested by ICHARG'))
        data['restart_observed']='; '.join(observations)
    try:
        result=read_case(out)
        data.update(energy_eV=result['energy_eV'],nelect=result['nelect'],finite_observables=True)
        if p['incar'].int('NSW',0)==0 and p['icharg']<10:
            # The EDIFF footer can also appear for NELM=1. A capped run or
            # electronic STOPCAR checkpoint is not positive SCF evidence.
            capped=result['iterations'] >= int(result['params'].get('NELM',p['incar'].int('NELM',60)))
            stopcar=out/'STOPCAR'
            electronic_stop=stopcar.exists() and bool(re.search(r'LABORT\s*=\s*\.?T',stopcar.read_text(),re.I))
            if capped or electronic_stop:
                data['scientific_convergence']='NOT CONFIRMED (NELM limit or electronic stop request)'
            else:
                data['scientific_convergence']='CONFIRMED (static electronic)' if result['normal'] and result['converged'] else 'NOT CONVERGED (static electronic)'
    except (ValueError, OSError, KeyError, TypeError, __import__('xml.etree.ElementTree',fromlist=['ParseError']).ParseError):
        data['finite_observables']='NOT ASSESSED (incomplete/unsupported output)'
    return data,versions=={'6.6.1'},rejected


def execute(p):
    out=p['output'];a=p['args'];meta=None;previous={};baseline={}
    # MPI version is a read-only utility probe, never invoked by --dry-run.
    mpi_version=subprocess.check_output([launch.MPI,'--version'],text=True).splitlines()[0]
    require('5.0.9' in mpi_version, 'MPI version differs from the recorded port')
    provenance=(git_identity(ROOT),git_identity(p['source']))
    out.mkdir(mode=0o700)  # exclusive ownership; no parents and no exist_ok

    def note(key,value):
        meta.write(f'{key}: {value}\n');meta.flush()

    def interrupted(sig,_frame):
        raise InterruptedError(sig,signal.Signals(sig).name)

    try:
        meta=(out/'RUN_METADATA.txt').open('x')
        for sig in (signal.SIGINT,signal.SIGTERM): previous[sig]=signal.signal(sig,interrupted)
        note('state','STAGING');note('child_status','NOT STARTED')
        note('staging_start_utc',datetime.now(timezone.utc).isoformat())
        for key in ('source','output','donor','binary','sha','parallel','origins','active_opt','istart','icharg'):
            note(key,p[key])
        note('variant',a.binary);note('requested_version','6.6.1')
        note('launcher_repository',provenance[0]);note('input_repository',provenance[1])
        note('mpi',f'{launch.MPI}; {mpi_version}; mode={a.mpi_mode}; ranks={a.ranks}')
        note('command',shlex.join(p['command']))
        note('threads',{k:p['env'].get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','OMPI_FC','HWLOC_SYNTHETIC')})
        note('hard_budget_seconds',a.timeout);note('stop_before_seconds',a.stop_before)
        note('restart_requested',a.restart);note('restart_preflight',p['restart_checks'])
        note('warnings',p['warnings']);note('incar_overrides',p['changes'])
        for name,path in p['files'].items():
            require(identity(path)==p['identities'][name],f'{name} changed after preflight')
            sha=hashlib.sha256()
            with path.open('rb') as source, (out/name).open('xb') as dest:
                for block in iter(lambda:source.read(1024*1024),b''):
                    dest.write(block);sha.update(block)
            require(identity(path)==p['identities'][name],f'{name} changed while staging; owned failed directory retained')
            note('staged_file',f'{name}; bytes={p["identities"][name][2]}; source_stat={p["identities"][name]}; SHA256={sha.hexdigest()}')
            if name=='INCAR': note('original_incar_sha256',sha.hexdigest())
        (out/'INCAR').write_text(p['effective'])
        note('effective_incar_sha256',digest(out/'INCAR'))
        for name in ('WAVECAR','CHGCAR'):
            if (out/name).exists(): baseline[name]=identity(out/name)[2:]
        def stop():
            tag='LSTOP' if p['incar'].int('NSW',0)>0 else 'LABORT'
            try:
                with (out/'STOPCAR').open('x') as f: f.write(f'{tag} = .TRUE.\n')
                message=f'{tag} requested at {datetime.now(timezone.utc).isoformat()}'
            except FileExistsError:
                message='Existing STOPCAR preserved; launcher did not overwrite it'
            note('advance_stop_request',message)
            return message
        require(identity(p['binary'])==p['binary_stat'], 'Selected binary changed after identity verification')
        note('state','RUNNING')
        with (out/'stdout.log').open('x') as stdout, (out/'stderr.log').open('x') as stderr:
            result=launch.supervise(p['command'],a.timeout,cwd=out,env=p['env'],stdout=stdout,stderr=stderr,
                                    stop_before=a.stop_before,on_stop=stop,awake=True)
        for key,value in result.items(): note(key,value)
        evidence,version_ok,rejected=output_evidence(p)
        for key,value in evidence.items(): note(key,value)
        status=result['status']
        if status==0 and (not version_ok or rejected):
            status=65;note('validation_failure','Version unverified/mismatched or requested WAVECAR rejected; inspect retained outputs')
        for name in ('WAVECAR','CHGCAR'):
            path=out/name
            state='absent' if not path.exists() else 'new' if name not in baseline else 'updated' if identity(path)[2:]!=baseline[name] else 'unchanged staged copy'
            note('checkpoint',f'{name}: {state}; bytes={path.stat().st_size if path.exists() else 0}; output checkpoint validity NOT ASSESSED')
        note('launcher_status',status);note('state','FINISHED')
        print(f"Run ended: status={status}; reason={result['reason']}; {evidence['scientific_convergence']}; restart={evidence['restart_observed']}")
        print('Metadata:',out/'RUN_METADATA.txt')
        return status
    except (Exception,KeyboardInterrupt) as error:
        status=128+error.errno if isinstance(error,InterruptedError) else 130 if isinstance(error,KeyboardInterrupt) else 1
        if meta:
            note('state','FAILED; owned directory retained');note('failure',str(error));note('launcher_status',status)
            note('end_utc',datetime.now(timezone.utc).isoformat())
        print(f'Launcher failed; retained {out}: {error}',file=sys.stderr)
        return status
    finally:
        if meta: meta.close()
        for sig,handler in previous.items(): signal.signal(sig,handler)


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        p=plan(args);describe(p)
        if args.dry_run:
            print('DRY RUN: no files created; no VASP/MPI process launched.')
            return 0
        return execute(p)
    except (PreflightError,OSError,ValueError,subprocess.SubprocessError) as error:
        print('Preflight/launch refused:',error,file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())
