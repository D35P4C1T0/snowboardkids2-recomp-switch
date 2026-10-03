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

    def test_performance_profile_and_batch(self):
        data, output = self.parse('''[ 2000 ms] profile: stage=nvk_submit count=10 mean_us=200 p50_us=250 p95_us=500 p99_us=750 max_us=700 late=0 id=12
[ 2100 ms] audio: timing min_us=20000 max_us=60000 gap_us=28000 input_frames=100 output_frames=200 corrections=0
batch probe: count=2 image=0 PASS
batch probe: count=2 image=1 PASS
batch probe: ALL PASS
''')
        self.assertEqual(data['profiles'][0]['count'], 10)
        self.assertIn('mean=0.20 ms', output)
        self.assertIn('production gap max=28.00 ms', output)
        self.assertIn('Batched transfers: 2 passed, 0 failed; suite passed', output)
        data, output = self.parse('batch probe: submitting phase=0 count=8\n')
        self.assertEqual(data['batch_status'], 'incomplete')

    def test_interval_filters_metrics_but_keeps_faults(self):
        data, _ = self.parse("""[ 1000 ms] perf: 30.00 fps, frame 33.33 ms, acquire 0.01 ms, present 0.02 ms, GPU wait 1.00 ms
[ 2000 ms] perf: 60.00 fps, frame 16.67 ms, acquire 0.01 ms, present 0.02 ms, GPU wait 1.00 ms
[ 1000 ms] profile: stage=nvk_submit count=10 mean_us=200 p50_us=250 p95_us=500 p99_us=750 max_us=700 late=0 id=12
[ 2000 ms] profile: stage=nvk_submit count=10 mean_us=100 p50_us=250 p95_us=500 p99_us=750 max_us=700 late=0 id=12
[ 1000 ms] audio: timing min_us=20000 max_us=60000 gap_us=28000 input_frames=100 output_frames=200 corrections=0
[ 2000 ms] audio: timing min_us=20000 max_us=60000 gap_us=17000 input_frames=100 output_frames=200 corrections=0
[ 3000 ms] NVK native fault: result=0x0 type=3
""")
        analyzer.select_metrics(data, 2, 2)
        self.assertEqual([sample.fps for sample in data['perf']], [60.0])
        self.assertEqual([sample['mean_us'] for sample in data['profiles']], [100])
        self.assertEqual([sample['gap_us'] for sample in data['audio_timing']], [17000])
        self.assertEqual(len(data['driver_faults']), 1)
        with self.assertRaises(ValueError): analyzer.select_metrics(data, 3, 2)
        with self.assertRaises(ValueError): analyzer.select_metrics(data, -1, None)
        with self.assertRaises(ValueError): analyzer.select_metrics(data, float("nan"), None)
        with self.assertRaises(ValueError): analyzer.select_metrics(data, 0, float("inf"))

    def test_legacy_and_split_framebuffer_timings(self):
        data, output = self.parse("slow: FB RDRAM draw frame=1 wait=23.00 ms\nslow: FB RDRAM color copyback frame=2 total=26.50 ms submit=5.00 ms fence=21.50 ms\n")
        self.assertEqual([item[0] for item in data['slow_framebuffers']], [23.0, 26.5])
        self.assertIn('max=26.50 ms', output)

    def test_truncated_profiles_are_ignored(self):
        data, output = self.parse("profile: stage=nvk_submit count=10 mean_us=200\naudio: timing min_us=1 max_us=2\n")
        self.assertEqual(data['profiles'], [])
        self.assertEqual(data['audio_timing'], [])

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
