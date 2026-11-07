"""Visible persistent ownership holds, using only a synthetic clock and family."""
from io import StringIO
import signal
import unittest

from cmw.jobs import ownership
from ownership_fixture import Family, load_runner


class TimedDiagnostics(StringIO):
    def __init__(self, family):
        super().__init__()
        self.family = family
        self.events = []

    def write(self, text):
        if text.strip():
            self.events.append((self.family.now, text))
        return super().write(text)


class UnreadableMembership(Family):
    def __init__(self, *, change_check=False, one_read_at=None, recover_at=float('inf')):
        super().__init__(persistent=True, hold_limit=135, timeout=1000, drain_after=100000)
        self.change_check = change_check
        self.one_read_at = one_read_at
        self.recover_at = recover_at
        self.one_read_returned = False

    def read(self, name, pid=None):
        super().read(name, pid)
        if not self.launched or name != 'enumeration':
            return
        if self.now >= self.recover_at:
            self.live = False  # The subgroup naturally exits as observation recovers.
            return
        if self.one_read_at is not None and self.now >= self.one_read_at and not self.one_read_returned:
            self.one_read_returned = True
            return  # One complete read succeeds; its required fresh reread will fail.
        check = 'membership.changed' if self.change_check and self.now >= 45 else 'membership.initial'
        raise ownership.OwnershipUnavailable(check, 'synthetic unreadable membership')


class DeniedSendWithoutAbsence(Family):
    def __init__(self):
        super().__init__(intent='timeout', denied_send=1, persistent=True, hold_limit=135)

    def killpg(self, pgid, signum):
        try:
            return super().killpg(pgid, signum)
        except PermissionError:
            self.absent_at = None  # Neither delivery nor group absence becomes provable.
            raise


class PersistentHoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_runner()

    def observe(self, family, expected=('held', None)):
        family.diagnostics = TimedDiagnostics(family)
        self.assertEqual(family.run(self.runner), expected, family.diagnostics.getvalue())
        self.assertGreater(family.polls, 1)
        self.assertTrue(all(0 < delay <= 5 for delay in family.sleeps))
        return family

    def assert_visible_escalation(self, family):
        events = family.diagnostics.events
        unavailable = [(when, text) for when, text in events if 'UNVERIFIABLE' in text]
        self.assertTrue(unavailable, events)
        self.assertLess(unavailable[0][0], 1)
        attention = [(when, text) for when, text in events if 'operator attention' in text.lower()]
        self.assertEqual(len(attention), 2, events)
        self.assertGreaterEqual(attention[0][0], 60)
        self.assertLess(attention[0][0], 66)
        self.assertGreaterEqual(attention[1][0], 120)
        self.assertLess(attention[1][0], 127)
        self.assertTrue(all('UNVERIFIABLE' in text for _, text in attention))
        self.assertNotIn('ownership VERIFIED', family.diagnostics.getvalue())
        self.assertEqual(family.waits, 0)

    def test_exited_launcher_retains_visible_hold_without_completion(self):
        family = self.observe(Family(denied_reads=float('inf'), persistent=True, hold_limit=135,
                                     timeout=1000))
        self.assert_visible_escalation(family)
        self.assertEqual(family.returncode, 0)
        self.assertFalse(family.live)
        self.assertEqual(family.requests, [])

    def test_ordinary_subgroup_drainage_retains_visible_hold_without_signal(self):
        family = self.observe(UnreadableMembership())
        self.assert_visible_escalation(family)
        self.assertEqual(family.returncode, 0)
        self.assertTrue(family.live)
        self.assertEqual(family.requests, [])

    def test_timeout_cleanup_escalates_visibility_without_authorizing_term(self):
        family = self.observe(Family(intent='timeout', denied_reads=float('inf'), persistent=True,
                                     hold_limit=135))
        self.assert_visible_escalation(family)
        self.assertTrue(family.live)
        self.assertEqual(family.requests, [])

    def test_denied_send_hold_never_replays_term_or_advances_to_kill(self):
        family = self.observe(DeniedSendWithoutAbsence())
        self.assert_visible_escalation(family)
        self.assertEqual(family.requests, [(family.child, signal.SIGTERM)])
        self.assertEqual(family.delivered, [])
        self.assertTrue(family.live)

    def test_changed_deciding_check_does_not_restart_escalation_clock(self):
        family = self.observe(UnreadableMembership(change_check=True))
        self.assert_visible_escalation(family)
        self.assertIn('membership.initial', family.diagnostics.getvalue())
        self.assertIn('membership.changed', family.diagnostics.getvalue())
        self.assertEqual(family.requests, [])

    def test_failed_fresh_reread_does_not_clear_hold_or_restart_clock(self):
        family = self.observe(UnreadableMembership(one_read_at=55))
        self.assert_visible_escalation(family)
        self.assertTrue(family.one_read_returned)
        self.assertEqual(family.requests, [])

    def test_recovery_after_escalation_resumes_original_drainage(self):
        family = self.observe(UnreadableMembership(recover_at=70), ('completed', 0))
        attention = [(when, text) for when, text in family.diagnostics.events
                     if 'operator attention' in text.lower()]
        recovery = [(when, text) for when, text in family.diagnostics.events
                    if 'ownership VERIFIED' in text]
        self.assertEqual(len(attention), 1)
        self.assertGreaterEqual(attention[0][0], 60)
        self.assertEqual(len(recovery), 1)
        self.assertGreaterEqual(recovery[0][0], 70)
        self.assertEqual(family.requests, [])


if __name__ == '__main__':
    unittest.main()
