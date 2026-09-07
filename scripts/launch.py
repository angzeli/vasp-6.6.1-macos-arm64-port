#!/usr/bin/env python3
"""Bounded MPI launch; fallback is explicit and never retries a calculation."""
import argparse
import os
import signal
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--ranks', type=int, default=1)
parser.add_argument('--mode', choices=['native', 'synthetic'], default='native')
parser.add_argument('--timeout', type=float, default=600)
parser.add_argument('program', nargs=argparse.REMAINDER)
args = parser.parse_args()
if not 1 <= args.ranks <= 8 or args.timeout <= 0:
    parser.error('ranks must be 1..8 and timeout must be positive')
program = args.program[1:] if args.program[:1] == ['--'] else args.program
if not program:
    parser.error('a program is required after --')
env = os.environ.copy()
env.pop('HWLOC_SYNTHETIC', None)
command = ['/opt/homebrew/Cellar/open-mpi/5.0.9/bin/mpirun', '-np', str(args.ranks)]
if args.mode == 'synthetic':
    cores = int(subprocess.check_output(['/usr/sbin/sysctl', '-n', 'hw.physicalcpu'], text=True))
    env['HWLOC_SYNTHETIC'] = f'Package:1 Core:{cores} PU:1'
    command += ['--bind-to', 'none', '--map-by', 'slot']
command += program
print(f'MPI mode={args.mode} ranks={args.ranks} timeout_s={args.timeout}', file=sys.stderr, flush=True)
started = time.monotonic()
process = subprocess.Popen(command, env=env, start_new_session=True)
try:
    status = process.wait(timeout=args.timeout)
except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    status = 124 if isinstance(error, subprocess.TimeoutExpired) else 130
    print('Stopped this launch process group after timeout/interruption.', file=sys.stderr)
print(f'MPI exit={status} wall_s={time.monotonic()-started:.3f}', file=sys.stderr, flush=True)
sys.exit(status if status >= 0 else 128 - status)
