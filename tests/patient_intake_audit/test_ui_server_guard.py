"""Positive controls for the calibrated browser-server audit guard."""

from collections import Counter
from contextlib import redirect_stdout
from io import StringIO
from threading import Lock
import unittest

from .ui_server import BrowserEffects


class BrowserServerGuardTests(unittest.TestCase):
    def test_calibrated_guard_blocks_counts_and_reports_process_starts(self):
        # Check the guard without installing a process-global audit hook or launching an app.
        effects = BrowserEffects.__new__(BrowserEffects)
        effects.calibrated = True
        effects.counts = Counter()
        effects.lock = Lock()

        events = ("subprocess.Popen", "os.system", "os.posix_spawn", "os.fork", "os.exec")
        output = StringIO()
        with redirect_stdout(output):
            for event in events:
                with self.subTest(event=event), self.assertRaises(PermissionError):
                    effects.guard(event, ())

        self.assertEqual(effects.counts, {"blocked_process_starts": len(events)})
        self.assertEqual(output.getvalue().splitlines(),
                         [f"AUDIT_BOUNDARY blocked_process_starts {event}" for event in events])
