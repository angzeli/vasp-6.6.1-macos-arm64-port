"""Controlled port finalization delegates to the shared strict runner gate."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from cmw.jobs import ownership

SPEC = importlib.util.spec_from_file_location('controlled_drainage_launch', Path(__file__).resolve().parents[1] / 'scripts/launch.py')
launch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launch)


class ControlledDrainageTests(unittest.TestCase):
    def test_exited_launcher_waits_for_strict_drain_without_local_signal(self):
        control = Mock(elapsed=1, intervals=[], suspended_seconds=0, unsuspended_elapsed=1)
        control.execution_budget_exhausted.return_value = False
        control.domain_drained.side_effect = [False, False, True]
        child = Mock(pid=30, returncode=0)
        child.poll.return_value = 0
        with patch.dict(os.environ, {'CMW_JOBS_OWN_SESSION': '1'}), \
             patch.object(launch.os, 'getpid', return_value=20), \
             patch.object(launch.os, 'getpgrp', return_value=10), \
             patch.object(launch.os, 'getsid', return_value=10), \
             patch.object(ownership, 'identity', return_value={'pid': 10}), \
             patch.object(ownership, 'owner_alive', return_value=True), \
             patch.object(ownership, 'group_members', return_value=[10, 20]), \
             patch.object(launch.subprocess, 'Popen', return_value=child) as popen, \
             patch.object(launch.signal, 'signal'), \
             patch.object(launch.time, 'sleep'), \
             patch.object(launch.os, 'killpg') as send:
            result = launch.supervise(['fixture-only-command'], 5, managed_foreground=True, control=control)
        self.assertEqual(result['status'], 0)
        self.assertEqual(control.domain_drained.call_count, 3)
        self.assertEqual(child.poll.call_count, 3)
        control.register.assert_called_once_with(30, strategy='openmpi')
        control.request_termination.assert_not_called()
        popen.assert_called_once()
        send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
