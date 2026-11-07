"""Capability compatibility with actual historical and configured CMW sources."""
from hashlib import sha1
from importlib.util import module_from_spec, spec_from_file_location
import os
from pathlib import Path
import signal
import sys
import unittest
from unittest.mock import patch

import cmw.jobs
from cmw.jobs import ownership
from ownership_fixture import Family, load_runner


class CmwApiCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_runner()

    def test_actual_31616be_api_is_refused_before_launch(self):
        reference = os.environ.get('CMW_LEGACY_REFERENCE')
        self.assertTrue(reference, 'Set CMW_LEGACY_REFERENCE to the historical reference checkout')
        path = Path(reference) / 'src/cmw/jobs/ownership.py'
        source = path.read_bytes()
        # Frozen negative-reference provenance, not a production compatibility pin.
        # Git blob of ownership.py at CMW 31616be474b2e2fd04ab6257c990983d46ddfcde.
        blob = sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest()
        self.assertEqual(blob, '4138a5c6c5d2eeb9c852792613b6bbbbab1330bb')
        spec = spec_from_file_location('cmw.jobs._legacy_ownership_compatibility', path)
        legacy = module_from_spec(spec)
        spec.loader.exec_module(legacy)
        self.assertTrue(callable(legacy.owner_alive))
        self.assertFalse(hasattr(legacy, 'observe_owner'))
        family = Family()
        # The actual historical module is imported, but none of its process
        # helpers may execute: refusal must precede identity capture and spawn.
        with patch.dict(sys.modules, {'cmw.jobs.ownership': legacy}), \
             patch.object(cmw.jobs, 'ownership', legacy), \
             patch.object(legacy, 'identity', side_effect=AssertionError('Historical identity must not run')):
            reason, status = family.run(self.runner)
        self.assertIsNone(status)
        self.assertIn('tri-state', reason.lower())
        self.assertFalse(family.launched)
        self.assertEqual(family.requests, [])

    def test_read_domain_without_denied_send_hold_capability_is_refused(self):
        # The pre-PR21 API already had read_domain but not the additive
        # anchor_ready_for_release capability associated with denied-send holds.
        def pre_hold_send(owner, signum, *, include_leader=True, absence_grace=0,
                          check_authority=None, read_domain=None, send_group=None):
            raise AssertionError('Incompatible signal helper must not execute')

        family = Family()
        reason, status = family.run(self.runner, api_override=('signal_session', pre_hold_send))
        self.assertIsNone(status)
        self.assertIn('CMW', reason)
        self.assertFalse(family.launched)
        self.assertEqual(family.requests, [])

    def test_configured_reference_accepts_and_recovers_denied_and_uncertain_sends(self):
        for uncertain in (False, True):
            with self.subTest(uncertain=uncertain):
                family = Family(intent='timeout', denied_send=1, uncertain_send=uncertain)
                self.assertEqual(family.run(self.runner), ('timeout', 124))
                self.assertTrue(family.launched)
                self.assertEqual(family.requests, [(family.child, signal.SIGTERM)])
                self.assertIn('UNVERIFIABLE', family.diagnostics.getvalue())
                self.assertGreaterEqual(family.now, family.absent_at)

    def test_newer_compatible_api_is_accepted_without_version_or_commit_match(self):
        current_send = ownership.signal_session

        def future_send(owner, signum, *, include_leader=True, absence_grace=0,
                        check_authority=None, read_domain=None, send_group=None,
                        anchor_ready_for_release=None, future_option=None):
            return current_send(owner, signum, include_leader=include_leader,
                                absence_grace=absence_grace, check_authority=check_authority,
                                read_domain=read_domain, send_group=send_group,
                                anchor_ready_for_release=anchor_ready_for_release)

        family = Family(intent='timeout', denied_send=1)
        with patch.object(ownership, '__version__', '9999.0', create=True), \
             patch.object(ownership, '__commit__', 'unlisted-future-candidate', create=True):
            self.assertEqual(family.run(self.runner, api_override=('signal_session', future_send)),
                             ('timeout', 124))
        self.assertEqual(family.requests, [(family.child, signal.SIGTERM)])
        self.assertIn('UNVERIFIABLE', family.diagnostics.getvalue())


if __name__ == '__main__':
    unittest.main()
