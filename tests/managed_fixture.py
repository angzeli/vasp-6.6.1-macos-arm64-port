"""Test-only external dependency substitutes; actual port code remains under test.

The entry role is an explicitly selected interpreter shim for run-vasp.sh. It
substitutes binary/MPI discovery and caffeinate only. No real engine or MPI runs.
"""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from unittest.mock import patch


def payload(root, role):
    configuration = json.loads((root/'payload.json').read_text())
    if role == 'rank':
        if configuration.get('resistant'):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        (root/'rank.json').write_text(json.dumps({'pid': os.getpid(), 'sid': os.getsid(0), 'pgid': os.getpgrp()}))
        deadline = time.monotonic()+40
        while not (root/'release').exists() and time.monotonic() < deadline:
            time.sleep(.02)
        return 0
    for name, text in configuration['outputs'].items():
        (Path.cwd()/name).write_text(text)
    print('vasp.6.6.1 (invented fixture banner)', flush=True)
    (root/'threads.json').write_text(json.dumps({key: os.environ.get(key) for key in
                                              ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS')}))
    if configuration.get('subgroup'):
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'rank', str(root)], preexec_fn=os.setpgrp)
        deadline = time.monotonic()+5
        while not (root/'rank.json').exists() and time.monotonic() < deadline:
            time.sleep(.02)
        if not (root/'rank.json').exists():
            raise RuntimeError('Owned rank did not become ready')
    return configuration.get('exit_code', 0)


def entry(arguments):
    if arguments[:1] == ['-B']:
        arguments = arguments[1:]
    module_path = Path(arguments[0]).resolve()
    root = Path(os.environ['PORT_TEST_CASE']).resolve()
    assert module_path.name == 'run_vasp.py'
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(module_path.parent))
    import run_vasp as runner
    import launch
    real_check_output, real_supervise = subprocess.check_output, launch.supervise
    script = Path(__file__).resolve()

    def audit(event, args):
        if event == 'open':
            file, mode, flags = args
            writing = isinstance(mode,str) and any(c in mode for c in 'wax+') or isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)
            if writing and isinstance(file,(str,bytes,os.PathLike)):
                path = Path(os.fsdecode(file)).absolute()
                if path.name.upper() == 'STOPCAR' or not path.is_relative_to(root):
                    raise RuntimeError('Forbidden fixture write: '+str(path))
        if event == 'subprocess.Popen':
            argv = list(args[1])
            allowed = argv == [sys.executable,str(script),'payload',str(root)] or argv[:2] == ['git','-C']
            if not allowed:
                raise RuntimeError('Non-fixture executable refused: '+str(argv))
    sys.addaudithook(audit)

    def discovery(argv, *args, **kwargs):
        if argv == [launch.MPI,'--version']:
            return 'TEST-ONLY mpirun (Open MPI) 5.0.9\n'
        return real_check_output(argv,*args,**kwargs)

    def command(program,ranks,mode,**kwargs):
        assert program == [sys.executable] and kwargs.get('managed_foreground') is True
        assert 1 <= ranks <= 8 and mode == 'native'
        return [sys.executable,str(script),'payload',str(root)],dict(os.environ)

    def supervise(command,timeout,**kwargs):
        assert kwargs['stop_before'] == 0
        kwargs['awake'] = False
        return real_supervise(command,timeout,**kwargs)

    with patch.object(runner,'binary_identity',return_value=(Path(sys.executable),'invented Python binary substitute')), \
         patch.object(launch,'mpi_command',side_effect=command), \
         patch.object(subprocess,'check_output',side_effect=discovery), \
         patch.object(launch,'supervise',side_effect=supervise):
        return runner.main(arguments[1:])


if __name__ == '__main__':
    if sys.argv[1:2] in (['payload'], ['rank']):
        raise SystemExit(payload(Path(sys.argv[2]),sys.argv[1]))
    raise SystemExit(entry(sys.argv[1:]))
