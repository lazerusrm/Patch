import threading
import time
import unittest
from collections import deque
from unittest.mock import patch

import numpy as np

from audio_frontend import AudioFrontEnd, BargeWatch, Resampler


class FrontEndTests(unittest.TestCase):
    def frontend(self):
        return AudioFrontEnd('test', processor=lambda capture, render: capture, vad=lambda frame: True)

    def test_resampling_keeps_duration_across_chunks(self):
        resample, total = Resampler(), 0
        for size in [480, 479, 481, 7, 1000] * 200:
            total += len(resample(np.zeros(size, np.int16)))
        self.assertAlmostEqual(total, 489400 * 2 / 3, delta=1)  # No drift over ~20 s of odd chunks.
        ramp = Resampler()(np.arange(0, 3000, 1, dtype=np.int16))
        self.assertTrue(np.allclose(ramp[:10], np.arange(10) * 1.5, atol=1))

    def test_reference_frames_are_due_after_the_speaker_delay(self):
        frontend = self.frontend()
        frontend.ref_delay = .5
        frontend.feed_reference(np.ones(480, np.int16).tobytes(), written_at=100.0)  # 20 ms at 24 kHz
        self.assertEqual(frontend._due_reference(100.4), [])
        due = frontend._due_reference(100.52)
        self.assertEqual(len(due), 2)  # Two 10 ms frames at 16 kHz.

    def test_barge_needs_sustained_speech_louder_than_the_echo(self):
        watch = BargeWatch()
        t = watch.started
        for i in range(100):  # Pumpkin talking: VAD fires on echo, but it stays at the echo level.
            self.assertFalse(watch.update(t + i * .01, True, 200 + (i % 7), floor=20))
        triggered = False
        for i in range(100, 160):  # Visitor speaks over it, clearly louder than the residual echo.
            triggered = watch.update(t + i * .01, True, 900, floor=20) or triggered
        self.assertTrue(triggered)
        self.assertIsNotNone(watch.triggered_at)

    def test_short_noise_does_not_interrupt(self):
        watch = BargeWatch()
        t = watch.started
        for i in range(100):
            watch.update(t + i * .01, False, 50, floor=20)
        for i in range(100, 110):  # 100 ms bang
            watch.update(t + i * .01, True, 2000, floor=20)
        for i in range(110, 170):
            watch.update(t + i * .01, False, 50, floor=20)
        self.assertIsNone(watch.triggered_at)

    def test_a_blip_does_not_end_the_listening_window(self):
        import voice_input
        frontend = self.frontend()
        frontend.alive = True
        tone = (np.sin(np.arange(160) * .3) * 4000).astype(np.int16).tobytes()
        def push(frame, count):
            for _ in range(count):
                with frontend.sub_lock:
                    for queue in frontend.subscribers:
                        queue.append(frame)
                time.sleep(.002)
        def feed():
            time.sleep(.05)
            push(tone, 4)          # 40 ms blip (the pumpkin's tail) ...
            push(bytes(320), 70)   # ... and silence: this used to return nothing at once
            push(tone, 40)         # then the visitor says "Lumos" (400 ms)
            push(bytes(320), 70)
        threading.Thread(target=feed, daemon=True).start()
        with patch.object(voice_input, 'FRONTEND', frontend), \
             patch.dict('os.environ', {'MIC_VAD': 'energy', 'MIC_END_SILENCE': '.5'}):
            audio = voice_input.listen(wait=3)
        self.assertGreater(len(audio), 44 + 10000)

    def test_listen_reads_the_cleaned_stream_including_preroll(self):
        import voice_input
        frontend = self.frontend()
        frontend.alive = True
        speech = (np.sin(np.arange(160) * .3) * 4000).astype(np.int16).tobytes()
        now = time.monotonic()
        for i in range(30):  # 300 ms of speech already in history before listening starts
            frontend.history.append((now - .3 + i * .01, speech))
        def feed():
            time.sleep(.05)
            for _ in range(80):  # then 0.8 s of silence ends the utterance
                with frontend.sub_lock:
                    for queue in frontend.subscribers:
                        queue.append(bytes(320))
                time.sleep(.002)
        threading.Thread(target=feed, daemon=True).start()
        with patch.object(voice_input, 'FRONTEND', frontend), \
             patch.dict('os.environ', {'MIC_VAD': 'energy', 'MIC_END_SILENCE': '.5'}):
            audio = voice_input.listen(wait=3, since=now - .35)
        self.assertGreater(len(audio), 44 + 9000)  # Kept the pre-roll speech.
