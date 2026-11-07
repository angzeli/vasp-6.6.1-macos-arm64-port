"""Synthetic MPI family: real CMW ownership algorithms, no operating-system control."""
from contextlib import ExitStack, redirect_stderr
from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import errno
import signal
import sys

import psutil
from cmw.jobs import ownership


def load_runner():
    path = Path(__file__).resolve().parents[1] / 'scripts/launch.py'
    spec = spec_from_file_location('ownership_test_launch', path)
    runner = module_from_spec(spec)
    pins = {'PORT_OPENMPI_VERSION': 'fixture', 'PORT_PRRTE_VERSION': 'fixture'}
    with patch.dict(sys.modules, toolchain=SimpleNamespace(load=lambda: (pins, 'fixture'))):
        spec.loader.exec_module(runner)
    return runner


class HoldObserved(BaseException):
    """End a persistent-hold observation without pretending that the runner returned."""


class Family:
    leader, payload, child, extra = 1900000000, 1900000001, 1900000002, 1900000003
    boot = '00000000-0000-4000-8000-000000000001'

    def __init__(self, *, intent='exit', wall_step=0, denied_reads=0, reused=False,
                 fault_at=None, denied_send=None, resistant=False, persistent=False,
                 extra_group=False, cancel_during_hold=False, timeout=None, uncertain_send=False,
                 drain_after=3, fault_kind='permission', topology_changed=False, hold_limit=12):
        self.intent = intent
        self.wall_step = wall_step
        self.denied_reads = denied_reads
        self.reused = reused
        self.fault_at = fault_at
        self.denied_send = denied_send
        self.resistant = resistant
        self.persistent = persistent
        self.extra_group = extra_group
        self.cancel_during_hold = cancel_during_hold
        self.timeout = timeout
        self.uncertain_send = uncertain_send
        self.drain_after = drain_after
        self.fault_kind = fault_kind
        self.topology_changed = topology_changed
        self.hold_limit = hold_limit
        self.now = 0.
        self.polls = 0
        self.probes = 0
        self.launched = False
        self.live = False
        self.extra_live = False
        self.requests = []
        self.delivered = []
        self.reads = []
        self.injected = False
        self.send_injected = False
        self.absent_at = None
        self.absent_group = None
        self.handlers = {}
        self.sleeps = []
        self.waits = 0
        self.returncode = None
        self.pid = self.child
        self.diagnostics = StringIO()

    def read(self, name, pid=None):
        if self.launched:
            self.reads.append((name, pid))
            if not self.injected and len(self.reads) == self.fault_at:
                self.injected = True
                if self.fault_kind == 'io':
                    raise OSError(errno.EIO, 'synthetic unreadable observation')
                raise PermissionError(errno.EACCES, 'synthetic observation denial')

    def evidence(self, pid):
        self.read('identity', pid)
        if pid not in (self.leader, self.payload, self.child, self.extra):
            raise AssertionError('inspection outside synthetic family')
        if self.launched and pid == self.leader:
            self.probes += 1
            if self.probes <= self.denied_reads:
                raise PermissionError(errno.EACCES, 'synthetic anchor denial')
        if (pid == self.child and not self.live) or (pid == self.extra and not self.extra_live):
            raise psutil.NoSuchProcess(pid)
        return pid * 100 + int(self.launched and self.reused and pid == self.leader), False

    def getsid(self, pid):
        self.read('sid', pid)
        if pid not in (0, self.leader, self.payload, self.child, self.extra):
            raise AssertionError('inspection outside synthetic session')
        if (pid == self.child and not self.live) or (pid == self.extra and not self.extra_live):
            raise ProcessLookupError()
        if self.launched and self.topology_changed and pid == self.leader:
            return self.leader + 100
        return self.leader

    def getpgid(self, pid):
        self.read('pgid', pid)
        if pid in (0, self.leader, self.payload):
            return self.leader
        if pid == self.child and self.live:
            return self.child
        if pid == self.extra and self.extra_live:
            return self.extra
        raise ProcessLookupError()

    def pids(self):
        self.read('enumeration')
        return ([self.leader, self.payload] + ([self.child] if self.live else []) +
                ([self.extra] if self.extra_live else []))

    def process(self, pid):
        def status():
            self.read('status', pid)
            return psutil.STATUS_RUNNING
        return SimpleNamespace(pid=pid, status=status, ppid=lambda: self.payload,
                               create_time=lambda: 1793654971.378596 +
                               (28792.0 if self.wall_offset() > 0 else
                                -28792.0 if self.wall_offset() < 0 else 0))

    def wall_offset(self):
        return self.wall_step if self.launched else 0

    def poll(self):
        self.polls += 1
        self.now += .01
        if self.intent == 'cancel' and self.polls == 1:
            self.handlers[signal.SIGTERM](signal.SIGTERM, None)
        if self.intent == 'exit':
            # Launcher exits first; its rank subgroup drains independently.
            self.returncode = 0
            if self.polls >= self.drain_after:
                self.live = False
                self.extra_live = False
        elif not self.live:
            self.returncode = 0
        return self.returncode

    def wait(self, timeout=None):
        self.waits += 1
        if self.live:
            raise AssertionError('attempted to reap a still-live synthetic child')
        self.returncode = 0
        return 0

    def sleep(self, seconds):
        if seconds < 0:
            raise AssertionError('negative sleep')
        self.sleeps.append(seconds)
        self.now += seconds
        if self.cancel_during_hold and self.probes and self.probes <= self.denied_reads:
            self.handlers[signal.SIGTERM](signal.SIGTERM, None)
            self.cancel_during_hold = False
        if self.absent_at is not None and self.now >= self.absent_at:
            if self.absent_group == self.extra:
                self.extra_live = False
            else:
                self.live = False
        if self.persistent and self.now >= self.hold_limit:
            raise HoldObserved()
        if self.now > max(40, self.hold_limit + 10):
            raise AssertionError('synthetic supervisor exceeded observation budget')

    def killpg(self, pgid, signum):
        if pgid not in (self.child, self.extra):
            raise AssertionError('signal/probe outside the permitted synthetic subgroup')
        if signum == 0:
            self.read('absence', pgid)
            if not (self.live if pgid == self.child else self.extra_live):
                raise ProcessLookupError()
            return
        self.requests.append((pgid, signum))
        if self.denied_send == len(self.requests):
            self.send_injected = True
            self.absent_at = self.now + .5
            self.absent_group = pgid
            if self.uncertain_send:
                self.delivered.append((pgid, signum))
                raise OSError(errno.EIO, 'synthetic delivery outcome unreadable')
            raise PermissionError(errno.EPERM, 'synthetic denied send')
        self.delivered.append((pgid, signum))
        if signum == signal.SIGKILL or not self.resistant:
            if pgid == self.child:
                self.live = False
            else:
                self.extra_live = False

    def set_handler(self, signum, handler):
        previous = self.handlers.get(signum)
        self.handlers[signum] = handler
        return previous

    def popen(self, *args, **kwargs):
        if self.launched:
            raise AssertionError('unexpected extra synthetic launch')
        self.launched = self.live = True
        self.extra_live = self.extra_group
        return self

    def run(self, runner, *, api_override=None, control=None):
        family = self
        class Wall(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls.fromtimestamp(1793654971.378596 + family.wall_offset(), tz)

        fake_os = SimpleNamespace(getpgrp=lambda: self.getpgid(self.payload),
                                  getpid=lambda: self.payload, getsid=self.getsid,
                                  getpgid=self.getpgid, killpg=self.killpg, setpgrp=lambda: None,
                                  environ={'CMW_JOBS_OWN_SESSION': '1'})
        clock = SimpleNamespace(monotonic=lambda: self.now, sleep=self.sleep)
        real_members = ownership.group_members
        def members(pgid, *, session=False):
            return real_members(pgid, pids=self.pids(), process_factory=self.process, session=session)

        with ExitStack() as stack:
            def replace(obj, name, value):
                stack.enter_context(patch.object(obj, name, value))
            replace(ownership, 'os', fake_os)
            replace(ownership, 'socket', SimpleNamespace(gethostname=lambda: 'synthetic'))
            replace(ownership, 'boot_session_id', lambda: self.boot)
            replace(ownership, 'group_members', members)
            replace(ownership, 'time', clock)
            replace(ownership.process_identity, 'os', fake_os)
            replace(ownership.process_identity, 'socket', SimpleNamespace(gethostname=lambda: 'synthetic'))
            replace(ownership.process_identity, 'boot_session_id', lambda: self.boot)
            replace(ownership.process_identity, 'process_evidence', self.evidence)
            replace(ownership.psutil, 'Process', self.process)
            replace(ownership.psutil, 'boot_time',
                    lambda: 1793633892.0 + (28792.0 if self.wall_offset() > 0 else
                                          -28792.0 if self.wall_offset() < 0 else 0))
            replace(runner, 'os', fake_os)
            replace(runner, 'time', clock)
            replace(runner, 'datetime', Wall)
            replace(runner, 'signal', SimpleNamespace(
                SIGINT=signal.SIGINT, SIGTERM=signal.SIGTERM, SIGKILL=signal.SIGKILL,
                Signals=signal.Signals, signal=self.set_handler))
            replace(runner, 'subprocess', SimpleNamespace(Popen=self.popen))
            if api_override is not None:
                name, value = api_override
                if value is None:
                    original = getattr(ownership, name)
                    delattr(ownership, name)
                    stack.callback(setattr, ownership, name, original)
                else:
                    replace(ownership, name, value)
            stack.enter_context(redirect_stderr(self.diagnostics))
            try:
                timeout = self.timeout if self.timeout is not None else (.15 if self.intent == 'timeout' else 30)
                result = runner.supervise(['synthetic-only'], timeout,
                                          grace=.2, managed_foreground=True, control=control)
            except HoldObserved:
                return 'held', None
            except (RuntimeError, ValueError, ownership.JobsError) as exc:
                return str(exc), None
            return result['reason'], result['status']
