import base64
import io
import math
import threading
import unittest
import wave
from array import array
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from voice_input import SpeechGate, listen


def tone(amplitude=1200, dc=0):
    return array('h', (int(dc + amplitude * math.sin(i * .19)) for i in range(320))).tobytes()


class InputPipelineTests(unittest.TestCase):
    def test_compressed_audio_roundtrip_and_expansion_limit(self):
        import zlib
        from core import decode_audio_payload
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(bytes(32000))
        original = buffer.getvalue()
        payload = {'audio':base64.b64encode(zlib.compress(original)).decode(),'audio_encoding':'zlib'}
        self.assertEqual(decode_audio_payload(payload), original)
        payload['audio'] = base64.b64encode(zlib.compress(bytes(900000))).decode()
        with self.assertRaises(ValueError):
            decode_audio_payload(payload)

    def test_opus_transport_decodes_to_bounded_pcm(self):
        import subprocess
        from core import decode_audio_payload
        source = io.BytesIO()
        with wave.open(source, 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(tone() * 50)
        compact = subprocess.check_output(['ffmpeg','-v','error','-i','pipe:0','-c:a','libopus',
                                          '-b:a','32k','-f','ogg','pipe:1'],input=source.getvalue())
        decoded = decode_audio_payload({'audio':base64.b64encode(compact).decode(),'audio_encoding':'opus'})
        with wave.open(io.BytesIO(decoded)) as wav:
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(len(wav.readframes(16001)), 32000)
        self.assertLess(len(compact), len(source.getvalue()) / 3)

    def test_voice_classifier_rejects_loud_noise_and_keeps_quiet_speech_onset(self):
        calls = []
        soft = tone(180)
        def classifier(chunk):
            calls.append(chunk)
            return chunk == soft
        gate = SpeechGate(threshold=100, voice_test=classifier)
        for _ in range(50):
            self.assertFalse(gate.feed(tone(1200)))
        self.assertFalse(gate.started)
        for _ in range(12):
            gate.feed(soft)
        for _ in range(36):
            done = gate.feed(tone(1200))
        self.assertTrue(done)  # Loud non-speech cannot extend the speaking window.
        self.assertTrue(gate.wav())
        self.assertEqual(len(calls), 98)

    def test_gate_keeps_onset_rejects_click_and_handles_dc_offset(self):
        gate = SpeechGate()
        soft = tone(100)
        for _ in range(20):
            gate.feed(soft)
        for _ in range(12):
            gate.feed(tone())
        for _ in range(40):
            if gate.feed(bytes(640)):
                break
        with wave.open(io.BytesIO(gate.wav())) as wav:
            self.assertEqual(wav.readframes(320), soft)
            self.assertGreater(wav.getnframes(), 16000)
        for signal in (tone(0, 2000), tone(70)):
            gate = SpeechGate()
            for _ in range(100):
                gate.feed(signal)
            self.assertEqual(gate.wav(), b'')
        gate = SpeechGate()
        gate.feed(tone(20000))
        for _ in range(40):
            gate.feed(bytes(640))
        self.assertEqual(gate.wav(), b'')

    def test_answer_at_end_of_wait_is_not_cut_off_and_odd_reads_are_preserved(self):
        process = MagicMock()
        process.stdout.fileno.return_value = 123
        now = [0.0]
        # Wait almost seven seconds, then speak for a second and pause.
        chunks = [bytes(640)] * 340 + [tone()] * 50 + [bytes(640)] * 40
        chunks[340:341] = [chunks[340][:1], chunks[340][1:]]
        def read(*_):
            now[0] += .02
            return chunks.pop(0)
        with patch('voice_input.subprocess.Popen', return_value=process), \
             patch('voice_input.time.monotonic', side_effect=lambda: now[0]), \
             patch('voice_input.select.select', return_value=([process.stdout], [], [])), \
             patch('voice_input.os.read', side_effect=read):
            audio = listen(wait=7)
        self.assertGreater(now[0], 8)
        with wave.open(io.BytesIO(audio)) as wav:
            self.assertGreater(wav.getnframes() / 16000, 1.8)
        process.terminate.assert_called_once()
        process.wait.assert_called_once()

    def test_cancelled_capture_reaps_microphone(self):
        process = MagicMock()
        with patch('voice_input.subprocess.Popen', return_value=process):
            self.assertEqual(listen(current=lambda: False), b'')
        process.terminate.assert_called_once()
        process.stdout.close.assert_called_once()

    def test_camera_burst_has_three_ordered_frames_and_obeys_media_limit(self):
        import cv2
        import numpy as np
        from vision_frames import visitor_image
        frames = iter(np.full((480, 640, 3), value, dtype=np.uint8) for value in (30, 90, 150))
        image = visitor_image(lambda: next(frames), interval=0)
        decoded = cv2.imdecode(np.frombuffer(base64.b64decode(image), dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, (1125, 640, 3))
        self.assertLess(len(image), 500000)
        self.assertEqual([round(float(decoded[y, 50].mean())) for y in (100, 475, 850)], [30, 90, 150])
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        duplicate = visitor_image(lambda: frame, interval=0)
        decoded = cv2.imdecode(np.frombuffer(base64.b64decode(duplicate), dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape[0], 375)
        self.assertEqual(visitor_image(lambda: frame, current=lambda: False), '')

    def test_quiet_visitor_can_answer_late_and_continue_beyond_three_turns(self):
        from core import Encounter
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.busy = threading.Lock()
        p.stop = threading.Event()
        p.controls = SimpleNamespace(mode='normal', sleeping=False)
        p.status = {'character': 'patch'}
        p.encounter = Encounter(active=True, generation=1)
        p.set_status = MagicMock()
        p.speech = SimpleNamespace(say=MagicMock())
        p.turn = MagicMock(side_effect=lambda *args, **kw:
                           {'transcript': 'I am a dinosaur'} if kw.get('listen_only') else {'text': 'A dinosaur! Welcome.'})
        captures = iter([b''] + [b'voice'] * 5)
        def capture(**kw):
            try:
                return next(captures)
            except StopIteration:
                p.stop.set()
                return b''
        with patch('pumpkin.listen', side_effect=capture):
            p.interact(generation=1, resume=True)
        self.assertEqual(p.speech.say.call_count, 5)

    def test_late_vision_does_not_block_listening_or_play_stale_reply(self):
        from core import Encounter
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.choose_character = MagicMock(return_value='patch')
        p.busy = threading.Lock()
        p.stop = threading.Event()
        p.controls = SimpleNamespace(mode='normal', sleeping=False)
        p.status = {'character': 'patch'}
        p.encounter = Encounter(active=True, generation=1)
        p.set_status = MagicMock()
        p.speech = SimpleNamespace(say=MagicMock())
        p.turn = MagicMock()
        pool = MagicMock()
        pool.submit.return_value.done.return_value = False
        pool.submit.return_value.result.side_effect = TimeoutError()
        def capture(**kw):
            p.stop.set()
            return b''
        with patch('pumpkin.ThreadPoolExecutor', return_value=pool), \
             patch('pumpkin.random.random', return_value=1), \
             patch('pumpkin.listen', side_effect=capture) as mic:
            p.interact(generation=1)
        mic.assert_called_once()
        self.assertEqual(p.speech.say.call_count, 1)
        pool.submit.return_value.result.assert_not_called()
        pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)

    def test_requested_sorting_keeps_hat_for_followup(self):
        from core import Encounter
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.busy = threading.Lock()
        p.stop = threading.Event()
        p.controls = SimpleNamespace(mode='normal', sleeping=False)
        p.status = {'character': 'patch'}
        p.encounter = Encounter(active=True, generation=1)
        p.set_status = MagicMock()
        p.speech = SimpleNamespace(say=MagicMock())
        p.last_sorting_line = 'Ravenclaw!'
        p.entertain = MagicMock()
        p.turn = MagicMock(side_effect=[{'transcript': 'sort me'}, {'transcript': 'why that house'}, {'text': 'A fine question.'}])
        captures = iter([b'voice', b'voice'])
        def capture(**kw):
            try:
                return next(captures)
            except StopIteration:
                p.stop.set()
                return b''
        with patch('pumpkin.listen', side_effect=capture):
            p.interact(generation=1, resume=True)
        p.entertain.assert_called_once()
        self.assertEqual(p.turn.call_args.args[0], 'sorting_hat')
        self.assertEqual(p.turn.call_args.args[1][0]['text'], 'Ravenclaw!')
