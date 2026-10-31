from array import array
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

import speaker_bus
from speaker_bus import SpeakerBus, sample_chunks


REAL_POPEN = subprocess.Popen


class FakeAplay:
    """Consumes the stream at real time like a sound card."""
    def __init__(self, *args, **kwargs):
        self.process = REAL_POPEN(['cat'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        self.stdin = self.process.stdin

    def poll(self):
        return self.process.poll()

    def terminate(self):
        self.process.terminate()

    def wait(self, timeout=None):
        return self.process.wait(timeout)

    def kill(self):
        self.process.kill()


class SpeakerBusTests(unittest.TestCase):
    def test_clip_plays_in_real_time_after_warmup_and_cancels(self):
        with patch('speaker_bus.subprocess.Popen', FakeAplay):
            bus = SpeakerBus('bluealsa:test', warm_seconds=0, latency=.05)
            try:
                self.assertTrue(bus.open())
                started = time.monotonic()
                job = bus.play(sample_chunks(array('h', [1000]) * 12000))  # 0.5 s
                self.assertTrue(job.completed)
                self.assertGreaterEqual(time.monotonic() - started, .45)
                flag = threading.Event()
                threading.Timer(.2, flag.set).start()
                started = time.monotonic()
                job = bus.play(sample_chunks(array('h', [1000]) * 48000), current=lambda: not flag.is_set())
                self.assertFalse(job.completed)
                self.assertLess(time.monotonic() - started, 1)
            finally:
                bus.close()
        self.assertFalse(bus.is_open)

    def test_gain_clips_safely(self):
        data = array('h', [20000, -20000, 100]).tobytes()
        self.assertEqual(array('h', speaker_bus.apply_gain(data, 2.0)).tolist(), [32767, -32768, 200])


if __name__ == '__main__':
    unittest.main()
