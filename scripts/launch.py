#!/usr/bin/env python3
"""Single owner of MPI process-group lifetime; also used by run_vasp."""
import argparse
from datetime import datetime, timezone, timedelta
import math
import os
import signal
import subprocess
import sys
import time

MPI = '/opt/homebrew/Cellar/open-mpi/5.0.9/bin/mpirun'


def mpi_command(program, ranks, mode):
    if not 1 <= ranks <= 8 or mode not in ('native', 'synthetic'):
        raise ValueError('ranks must be 1..8; mode must be native or synthetic')
    env = os.environ.copy()
    env.pop('HWLOC_SYNTHETIC', None)
    env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    command = [MPI, '-np', str(ranks)]
    if mode == 'synthetic':
        cores = int(subprocess.check_output(['/usr/sbin/sysctl', '-n', 'hw.physicalcpu'], text=True))
        env['HWLOC_SYNTHETIC'] = f'Package:1 Core:{cores} PU:1'
        command += ['--bind-to', 'none', '--map-by', 'slot']
    return command + list(program), env


def supervise(command, timeout, *, cwd=None, env=None, stdout=None, stderr=None,
              stop_before=0, on_stop=None, awake=False, grace=10):
    """Own one session, forward INT/TERM, enforce a deadline and reap the leader.

    Internal command injection supports synthetic tests, not a public CLI option.
    The hard deadline excludes staging; termination may take up to grace seconds.
    """
    if not math.isfinite(timeout) or timeout <= 0 or not 0 <= stop_before < timeout:
        raise ValueError('timeout must be positive; 0 <= stop-before < timeout')
    requested = []
    previous = {}
    process = inhibitor = None
    reason, status, stop_note = 'completed', None, 'disabled' if not stop_before else 'not reached'
    started = time.monotonic()
    start_utc = datetime.now(timezone.utc).isoformat()

    def receive(signum, _frame):
        if not requested:
            requested.append(signum)

    def group_exists():
        try:
            os.killpg(process.pid, 0)
            return True
        except ProcessLookupError:
            return False

    def send_group(signum):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    def cleanup():
        if not group_exists():
            process.wait()
            return
        send_group(signal.SIGTERM)
        end = time.monotonic() + grace
        while time.monotonic() < end:
            process.poll()  # reap the leader even if descendants survive it
            if not group_exists():
                break
            time.sleep(0.05)
        if group_exists():
            send_group(signal.SIGKILL)
        process.wait()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, receive)
        # Install handlers before creating the child: a startup signal cannot orphan it.
        started = time.monotonic()
        start_utc = datetime.now(timezone.utc).isoformat()
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout,
                                   stderr=stderr, start_new_session=True)
        if awake:
            inhibitor = subprocess.Popen(['/usr/bin/caffeinate', '-i', '-w', str(os.getpid())],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while True:
            child = process.poll()
            if requested:
                reason = signal.Signals(requested[0]).name
                status = 128 + requested[0]
                break
            if child is not None:
                status = child if child >= 0 else 128 - child
                break
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                reason, status = 'timeout', 124
                break
            if stop_before and stop_note == 'not reached' and elapsed >= timeout - stop_before:
                stop_note = str(on_stop()) if on_stop else 'no stop callback'
            time.sleep(min(0.1, timeout - elapsed))
        if reason != 'completed' or group_exists():
            cleanup()
    except BaseException:
        if process is not None:
            cleanup()
        raise
    finally:
        if inhibitor is not None:
            inhibitor.terminate()
            try:
                inhibitor.wait(timeout=2)
            except subprocess.TimeoutExpired:
                inhibitor.kill()
                inhibitor.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return dict(status=status, child_status=process.returncode, reason=reason,
                start_utc=start_utc, hard_deadline_utc=(datetime.fromisoformat(start_utc)+timedelta(seconds=timeout)).isoformat(), end_utc=datetime.now(timezone.utc).isoformat(),
                elapsed_s=round(time.monotonic() - started, 6), pid=process.pid,
                advance_stop=stop_note)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--ranks', type=int, default=1)
    parser.add_argument('--mode', choices=['native', 'synthetic'], default='native')
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('program', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    program = args.program[1:] if args.program[:1] == ['--'] else args.program
    if not program:
        parser.error('a program is required after --')
    try:
        command, env = mpi_command(program, args.ranks, args.mode)
        print(f'MPI mode={args.mode} ranks={args.ranks} timeout_s={args.timeout}', file=sys.stderr, flush=True)
        result = supervise(command, args.timeout, env=env)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"MPI exit={result['status']} child={result['child_status']} reason={result['reason']} wall_s={result['elapsed_s']:.3f}", file=sys.stderr)
    return result['status']


if __name__ == '__main__':
    sys.exit(main())
