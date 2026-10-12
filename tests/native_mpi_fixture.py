"""Explicit acceptance shim: actual runner/MPI, a compiled benign MPI program.

Not loaded in ordinary CI and never discovers or executes a scientific engine.
The caller supplies invented prepared inputs and a harmless compiled program in
its task-owned acceptance workspace. Optional invented native output text is
only for testing result-binding composition, never real-engine qualification.
"""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


def entry(arguments):
    if arguments[:1] == ['-B']:
        arguments = arguments[1:]
    module = Path(arguments[0]).resolve(strict=True)
    if module.name != 'run_vasp.py':
        raise ValueError('This test shim accepts only the candidate run_vasp.py')
    root = Path(os.environ['PORT_TEST_CASE']).resolve(strict=True)
    workspace = Path(os.environ['PORT_NATIVE_WORKSPACE']).resolve(strict=True)
    program = Path(os.environ['PORT_NATIVE_PROGRAM']).resolve(strict=True)
    if not root.is_relative_to(workspace) or not program.is_relative_to(workspace):
        raise ValueError('Native test inputs and compiled program must belong to the acceptance workspace')
    if program.name.lower() in {'vasp_std', 'vasp_gam', 'vasp_ncl', 'orca', 'cp2k', 'multiwfn'}:
        raise ValueError('Scientific engine names are not allowed by this test shim')
    sys.path.insert(0, str(module.parent))
    import run_vasp as runner
    import launch
    original_supervise = launch.supervise

    def supervise(command, timeout, **options):
        # Keep every runner check and genuine deadline/control/MPI operation.
        # Optional fixture output is visibly invented and never engine-produced.
        if os.environ.get('PORT_NATIVE_INVENTED_OUTPUTS') == '1':
            configuration = json.loads((root/'payload.json').read_text())
            for name, text in configuration['outputs'].items():
                if Path(name).name != name or name.upper() == 'STOPCAR':
                    raise ValueError('Unsafe invented output name')
                (Path(options['cwd'])/name).write_text(text)
            options['stdout'].write('vasp.6.6.1 (invented benign MPI acceptance fixture)\n')
            options['stdout'].flush()
        return original_supervise(command, timeout, **options)

    with patch.object(runner, 'binary_identity', return_value=(program, runner.digest(program))), \
         patch.object(launch, 'supervise', side_effect=supervise):
        return runner.main(arguments[1:])


if __name__ == '__main__':
    raise SystemExit(entry(sys.argv[1:]))
