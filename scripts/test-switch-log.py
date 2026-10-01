#!/usr/bin/env python3
"""Check full-game metrics and interrupted, untimestamped GPU probes."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'switch_log', Path(__file__).with_name('analyze-switch-log.py'))
analyzer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = analyzer
spec.loader.exec_module(analyzer)


class LogTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run.log'
            path.write_text(text)
            data = analyzer.parse_log(path)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                analyzer.print_summary(path, data)
            return data, output.getvalue()

    def test_crash_after_pass_is_incomplete(self):
        data, output = self.parse('''transfer probe: testing image readback
transfer probe: buffer 4x2 PASS mismatches=0
[nvk] NVK channel fault: notification=32/0 status=0xffff
NVK execution FAILED: syncpt=27 target=10 current=10 result=0x0
fatal: Plume submit failed: -4
''')
        self.assertEqual(data['transfer_status'], 'incomplete')
        self.assertEqual(len(data['driver_faults']), 2)
        self.assertEqual(len(data['fatals']), 1)
        self.assertIn('1 passed, 0 failed; suite incomplete', output)

    def test_terminal_status_does_not_count_as_a_case(self):
        data, output = self.parse('''transfer probe: buffer 1x1 PASS mismatches=0
transfer probe: image 1x1 PASS mismatches=0
transfer probe: ALL PASS
''')
        self.assertEqual(data['transfer_status'], 'passed')
        self.assertIn('2 passed, 0 failed; suite passed', output)
        data, output = self.parse('''transfer probe: image 1x1 FAIL mismatches=4
transfer probe: FAILED
''')
        self.assertEqual(data['transfer_status'], 'failed')
        self.assertIn('0 passed, 1 failed; suite failed', output)

    def test_timestamped_game_metrics_survive(self):
        data, output = self.parse('''[ 1000 ms] launcher: Start Game selected
[ 2000 ms] perf: 30.00 fps, frame 33.33 ms, acquire 0.01 ms, present 0.02 ms, GPU wait 1.00 ms
[ 3000 ms] NVK native fault: result=0x0 type=3
''')
        self.assertEqual(data['duration_ms'], 3000)
        self.assertEqual(data['game_start_ms'], 1000)
        self.assertEqual(data['perf'][0].fps, 30.0)
        self.assertIn('Gameplay: 1 windows, FPS median=30.00', output)
        self.assertIn('Driver: NVK native fault:', output)

    def test_sampling_is_separate_from_transfers(self):
        data, output = self.parse('''transfer probe: image 1x1 FAIL mismatches=4
transfer probe: FAILED
sampling probe: testing RT64 texture-copy rendering
sampling probe: rendered 4x2 PASS mismatches=0
sampling probe: ALL PASS
''')
        self.assertEqual(data['sampling_status'], 'passed')
        self.assertIn('Texture sampling: 1 passed, 0 failed; suite passed', output)
        data, output = self.parse('''sampling probe: testing RT64 texture-copy rendering
NVK method fault: class=0xb197 method=0x1614 data=0 irq=0x00200000 detail=0
fatal: Plume submit failed: -4
''')
        self.assertEqual(data['sampling_status'], 'incomplete')
        self.assertEqual(len(data['driver_faults']), 1)
        self.assertIn('Texture sampling: 0 passed, 0 failed; suite incomplete', output)


if __name__ == '__main__':
    unittest.main()
