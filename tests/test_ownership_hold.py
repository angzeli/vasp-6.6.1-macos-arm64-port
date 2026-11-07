"""Issue #19 parity and single-fault qualification; no real processes or signals."""
import signal
from types import SimpleNamespace
import unittest

from cmw.jobs import ownership
from ownership_fixture import Family, load_runner


class OwnershipHoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_runner()

    def check(self, expected, **options):
        family = Family(**options)
        self.assertEqual(family.run(self.runner), expected, family.diagnostics.getvalue())
        self.assertTrue(all(pgid == family.child for pgid, _ in family.requests))
        return family

    def test_ordinary_exit_across_wall_step(self):
        family = self.check(('completed', 0), wall_step=28791.6)
        self.assertEqual(family.requests, [])

    def test_real_timeout_across_wall_step(self):
        family = self.check(('timeout', 124), intent='timeout', wall_step=28791.6)
        self.assertEqual(family.requests, [(family.child, signal.SIGTERM)])

    def test_single_denied_read_allows_natural_drainage(self):
        for step in (0, 28791.6):
            with self.subTest(wall_step=step):
                family = self.check(('completed', 0), denied_reads=1, wall_step=step)
                self.assertEqual(family.requests, [])

    def test_unavailable_exit_reports_a_distinct_outcome_from_gone(self):
        # Former expected failure: a persistent unreadable owner stays held;
        # proven replacement refuses authority, without signalling either one.
        denied = self.check(('held', None), denied_reads=float('inf'), persistent=True)
        gone = Family(reused=True)
        outcome = gone.run(self.runner)
        self.assertIn('GONE', outcome[0].upper())
        self.assertIsNone(outcome[1])
        self.assertIn('UNVERIFIABLE', denied.diagnostics.getvalue().upper())
        self.assertEqual(denied.requests, [])
        self.assertEqual(gone.requests, [])
        self.assertEqual(denied.waits, 0)

    def test_unavailable_cleanup_identifies_unverifiable_ownership(self):
        # Former expected failure: timeout intent does not authorize an
        # unreadable target or discard supervision when the probe stays denied.
        family = self.check(('held', None), intent='timeout', denied_reads=float('inf'),
                            persistent=True)
        self.assertIn('UNVERIFIABLE', family.diagnostics.getvalue().upper())
        self.assertEqual(family.requests, [])
        self.assertEqual(family.waits, 0)

    def test_recovered_whole_check_resumes_ordinary_drainage(self):
        family = self.check(('completed', 0), denied_reads=2)
        self.assertEqual(family.requests, [])

    def test_recovered_whole_check_resumes_ordinary_drainage_across_step(self):
        family = self.check(('completed', 0), denied_reads=2, wall_step=28791.6)
        self.assertEqual(family.requests, [])

    def test_j4_1_clock_step_replay_in_both_directions(self):
        # Observed incident values: boot 1793633892 -> 1793662684;
        # adjusted birth 1793654971.378596 -> 1793683763.378596.
        for step in (28791.6, -28791.6):
            for intent, expected in (('exit', ('completed', 0)), ('timeout', ('timeout', 124)),
                                     ('cancel', ('SIGTERM', 143))):
                with self.subTest(step=step, intent=intent):
                    family = self.check(expected, intent=intent, wall_step=step)
                    self.assertEqual(family.requests, [] if intent == 'exit' else
                                     [(family.child, signal.SIGTERM)])

    def test_denied_send_armed_during_drainage_is_never_reached(self):
        family = self.check(('completed', 0), denied_reads=2, denied_send=1)
        self.assertEqual(family.requests, [])
        self.assertFalse(family.send_injected)

    def test_denied_send_during_cleanup_holds_until_absence_without_replay(self):
        for intent, expected in (('cancel', ('SIGTERM', 143)), ('timeout', ('timeout', 124))):
            for send in (1, 2):
                with self.subTest(intent=intent, send=send):
                    family = self.check(expected, intent=intent, denied_send=send, resistant=send == 2)
                    self.assertTrue(family.send_injected)
                    self.assertIn('UNVERIFIABLE', family.diagnostics.getvalue().upper())
                    self.assertEqual(family.requests, [(family.child, signal.SIGTERM)] +
                                     ([(family.child, signal.SIGKILL)] if send == 2 else []))
                    self.assertNotIn(family.requests[-1], family.delivered)
                    self.assertGreaterEqual(family.now, family.absent_at)

    def test_single_transient_fault_at_every_observation_boundary(self):
        cases = 0
        for intent in ('exit', 'cancel', 'timeout'):
            for resistant in ((False,) if intent == 'exit' else (False, True)):
                baseline = Family(intent=intent, resistant=resistant)
                expected = baseline.run(self.runner)
                self.assertIsNotNone(expected[1], expected)
                self.assertTrue(baseline.reads)
                for fault_kind in ('permission', 'io'):
                    for point, observation in enumerate(baseline.reads, 1):
                        with self.subTest(intent=intent, resistant=resistant, point=point,
                                          read=observation, fault=fault_kind):
                            family = Family(intent=intent, resistant=resistant,
                                            fault_at=point, fault_kind=fault_kind)
                            self.assertEqual(family.run(self.runner), expected, family.diagnostics.getvalue())
                            self.assertTrue(family.injected)
                            self.assertEqual(family.requests, baseline.requests)
                            cases += 1
        print(f'Single-observation fault sweep: {cases} cases')

    def test_pending_cancel_during_exit_hold_is_not_reported_completed(self):
        family = self.check(('SIGTERM', 143), denied_reads=1, cancel_during_hold=True, drain_after=100)
        self.assertEqual(family.requests, [(family.child, signal.SIGTERM)])

    def test_pending_cancel_after_natural_drainage_does_not_invent_a_send(self):
        family = self.check(('SIGTERM', 143), denied_reads=1, cancel_during_hold=True)
        self.assertEqual(family.requests, [])

    def test_deadline_expiring_during_exit_hold_is_not_reported_completed(self):
        family = self.check(('timeout', 124), denied_reads=1, timeout=.15, drain_after=100)
        self.assertEqual(family.requests, [(family.child, signal.SIGTERM)])

    def test_later_subgroup_denial_never_replays_an_earlier_delivered_term(self):
        family = Family(intent='timeout', extra_group=True, denied_send=2)
        self.assertEqual(family.run(self.runner), ('timeout', 124), family.diagnostics.getvalue())
        self.assertEqual(family.requests, [(family.child, signal.SIGTERM), (family.extra, signal.SIGTERM)])
        self.assertEqual(family.delivered, [(family.child, signal.SIGTERM)])
        self.assertTrue(family.send_injected)

    def test_unreadable_delivery_outcome_is_not_replayed(self):
        family = self.check(('timeout', 124), intent='timeout', denied_send=1, uncertain_send=True)
        self.assertEqual(family.requests, [(family.child, signal.SIGTERM)])
        self.assertEqual(family.delivered, family.requests)
        self.assertIn('UNVERIFIABLE', family.diagnostics.getvalue().upper())

    def test_older_cmw_is_refused_before_launch(self):
        for missing in ('observe_owner', 'OwnershipStatus', 'OwnershipUnavailable'):
            with self.subTest(missing=missing):
                family = Family()
                reason, status = family.run(self.runner, api_override=(missing, None))
                self.assertIsNone(status)
                self.assertIn('CMW', reason)
                self.assertIn('tri-state', reason.lower())
                self.assertFalse(family.launched)
                self.assertEqual(family.requests, [])

    def test_cmw_without_read_domain_is_refused_before_launch(self):
        def historical_send(owner, signum, *, include_leader=True):
            raise AssertionError('old signal helper must never be called')
        family = Family()
        reason, status = family.run(self.runner, api_override=('signal_session', historical_send))
        self.assertIsNone(status)
        self.assertIn('CMW', reason)
        self.assertFalse(family.launched)

    def test_legacy_identity_is_refused_before_launch(self):
        family = Family()
        reason, status = family.run(self.runner, api_override=(
            'identity', lambda pid: {'version': 1, 'pid': pid}))
        self.assertIsNone(status)
        self.assertFalse(family.launched)
        self.assertIn('CMW', reason)

    def test_unverifiable_startup_is_refused_before_launch(self):
        family = Family()
        observation = ownership.OwnershipObservation(
            ownership.OwnershipStatus.UNVERIFIABLE, 'start_token', 2, family.boot, {})
        reason, status = family.run(self.runner, api_override=('observe_owner', lambda owner: observation))
        self.assertIsNone(status)
        self.assertIn('UNVERIFIABLE', reason.upper())
        self.assertFalse(family.launched)
        self.assertEqual(family.requests, [])

    def test_confirmed_topology_change_refuses_without_signal(self):
        family = Family(topology_changed=True)
        reason, status = family.run(self.runner)
        self.assertIsNone(status)
        self.assertIn('authority changed', reason)
        self.assertEqual(family.requests, [])

    def test_incomplete_tri_state_enum_is_refused_before_launch(self):
        family = Family()
        incomplete = SimpleNamespace(VERIFIED='VERIFIED', GONE='GONE')
        reason, status = family.run(self.runner, api_override=('OwnershipStatus', incomplete))
        self.assertIsNone(status)
        self.assertIn('tri-state', reason)
        self.assertFalse(family.launched)


if __name__ == '__main__':
    unittest.main()
