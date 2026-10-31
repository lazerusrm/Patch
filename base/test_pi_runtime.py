import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock
import wave
import threading


class PiRuntimeTests(unittest.TestCase):
    def test_story_audio_is_bounded_to_one_minute(self):
        from pumpkin import Speech
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            directory = Path(directory)
            source = directory / 'long-source.wav'
            with wave.open(str(source), 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(bytes(31 * 48000))
            speech = Speech(SimpleNamespace(level=None, character='patch'))
            speech.cache = directory / 'cache'
            speech.cache.mkdir()
            with patch.object(speech, 'render', return_value=source):
                path = speech.render_story('patch', 'First short sentence. ' * 20)
            with wave.open(str(path)) as wav:
                self.assertLessEqual(wav.getnframes() / wav.getframerate(), 60)

    def test_departure_during_tts_prevents_stale_playback(self):
        from pumpkin import Speech
        lights = SimpleNamespace(level=None, character='patch')
        speech = Speech(lights)
        active = [True]
        def render(*_):
            active[0] = False
            return Path('/dev/shm/nonexistent-stale-voice.wav')
        with patch.object(speech, 'render', side_effect=render), patch('pumpkin.subprocess.Popen') as play:
            speech.say('patch', 'Old conversation', current=lambda: active[0])
        play.assert_not_called()

    def test_sleep_command_interrupts_offering_routine(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.last_game = None
        p.set_status = MagicMock()
        p.speech = SimpleNamespace(say=MagicMock())
        p.turn = MagicMock(return_value={'transcript': 'hey pumpkinhead sleep'})
        p.control = MagicMock()
        current = lambda: True
        with patch('pumpkin.listen', return_value=b'audio'):
            p.play_game('patch', current, key='offering')
        p.control.assert_called_once_with('sleep', 'patch', current=current)
        self.assertEqual(p.speech.say.call_count, 1)

    def test_audio_failure_rearms_same_encounter(self):
        from pumpkin import Pumpkin
        from core import Encounter
        p = object.__new__(Pumpkin)
        p.busy = threading.Lock()
        p.music = SimpleNamespace(tracks=[])
        p.controls = SimpleNamespace(sleeping=False, mode='normal')
        p.status = {'character': 'patch'}
        p.stop = threading.Event()
        p.encounter = Encounter(active=True, generation=1)
        p.set_status = MagicMock()
        p.turn = MagicMock(return_value={'text': ''})
        p.speech = SimpleNamespace(say=MagicMock(side_effect=RuntimeError('USB disconnected')))
        with self.assertLogs(level='ERROR'):
            p.interact(generation=1)
        self.assertTrue(p.encounter.pending)
        self.assertGreater(p.retry_after, 0)

    def test_waking_resumes_conversation_for_current_visitors(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.busy = threading.Lock()
        p.music = SimpleNamespace(tracks=[])
        p.controls = SimpleNamespace(sleeping=True, mode='normal')
        p.status = {'character': 'patch'}
        p.stop = threading.Event()
        p.encounter = SimpleNamespace(active=True, generation=3)
        p.set_status = MagicMock()
        p.turn = MagicMock(return_value={'transcript': 'hey pumpkinhead wake up'})
        def wake(*args, **kwargs):
            p.controls.sleeping = False
        p.control = MagicMock(side_effect=wake)
        p.interact = MagicMock()
        with patch('pumpkin.listen', return_value=b'audio'):
            p.sleep_loop()
        p.interact.assert_called_once_with(generation=3, resume=True)

    def test_idle_keywords_work_before_camera_detects_a_person(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.busy = threading.Lock()
        p.music = SimpleNamespace(tracks=[])
        p.controls = SimpleNamespace(sleeping=False, mode='normal')
        p.status = {'character': 'patch'}
        p.stop = threading.Event()
        p.encounter = SimpleNamespace(active=False)
        p.set_status = MagicMock()
        p.turn = MagicMock(return_value={'transcript': 'hey pumpkinhead tell me a joke'})
        spoken = []
        def entertain(kind, character, current):
            spoken.append((kind, character, current()))
            p.stop.set()
        p.entertain = entertain
        with patch('pumpkin.listen', return_value=b'audio'):
            p.sleep_loop()
        self.assertEqual(spoken, [('joke', 'patch', True)])
        self.assertFalse(p.busy.locked())

    def test_new_arrival_cancels_idle_capture_and_remains_pending(self):
        from pumpkin import Pumpkin
        from core import Encounter
        p = object.__new__(Pumpkin)
        p.busy = threading.Lock()
        p.music = SimpleNamespace(tracks=[])
        p.controls = SimpleNamespace(sleeping=False, mode='normal')
        p.status = {'character': 'patch'}
        p.stop = threading.Event()
        p.encounter = Encounter()
        p.set_status = MagicMock()
        p.interact = MagicMock()
        def arrival(**kwargs):
            p.encounter.observe(True, 0)
            p.encounter.observe(True, 2)
            self.assertFalse(kwargs['current']())
            return None
        with patch('pumpkin.listen', side_effect=arrival):
            p.sleep_loop()
        self.assertTrue(p.encounter.pending)
        self.assertFalse(p.busy.locked())
        p.interact.assert_not_called()

    def test_stalled_playback_is_terminated_and_reaped(self):
        from pumpkin import Speech
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            path = Path(directory) / 'speech.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(bytes(480))
            lights = SimpleNamespace(level=None, character='patch')
            speech = Speech(lights)
            process = MagicMock()
            process.poll.return_value = None
            with patch.object(speech, 'render', return_value=path), \
                 patch('pumpkin.subprocess.Popen', return_value=process), \
                 patch('pumpkin.time.monotonic', side_effect=[0, 100]):
                with self.assertRaises(TimeoutError):
                    speech.say('patch', 'Hello')
            process.terminate.assert_called_once()
            process.wait.assert_called_once()
            self.assertIsNone(lights.level)

    def test_bluetooth_preroll_preserves_first_sample_and_delays_speech_lights(self):
        import os
        from array import array
        from pumpkin import Speech
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            path = Path(directory) / 'speech.wav'
            original = array('h', [12000] * 24000).tobytes()
            with wave.open(str(path), 'wb') as output:
                output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                output.writeframes(original)
            lights = SimpleNamespace(level=None, character='patch')
            with patch.dict(os.environ, {'AUDIO_OUTPUT': 'bluealsa:DEV=test', 'AUDIO_PREROLL_SECONDS': '3'}):
                speech = Speech(lights)
            process = MagicMock()
            process.poll.side_effect = [None, None, 0]
            process.returncode = 0
            temporary = []
            levels = []
            def play(command, **kwargs):
                temporary.append(Path(command[-1]))
                with wave.open(command[-1]) as audio:
                    self.assertEqual(audio.getnframes(), 4 * 24000)
                    warmup = array('h', audio.readframes(3 * 24000))
                    self.assertGreater(max(abs(value) for value in warmup), 0)
                    self.assertLessEqual(max(abs(value) for value in warmup), 300)
                    self.assertEqual(audio.readframes(24000), original)
                return process
            with patch('pumpkin.subprocess.Popen', side_effect=play), \
                 patch('pumpkin.time.monotonic', side_effect=[0, 1, 3.1]), \
                 patch('pumpkin.time.sleep', side_effect=lambda _: levels.append(lights.level)):
                speech.play(path, 'patch')
            self.assertIsNone(levels[0])
            self.assertGreater(levels[1], .2)
            self.assertFalse(temporary[0].exists())
            self.assertTrue(path.exists())

    def test_routine_plays_paired_cast_and_keeps_sleep_control_in_gaps(self):
        from pumpkin import Pumpkin, GAMES
        p = object.__new__(Pumpkin)
        p.last_game = None
        p.set_status = MagicMock()
        def render(key, start, current):
            actors = GAMES[key]['cast'][start:start + 2]
            return Path('/fake/routine.wav'), [(index, actor) for index, actor in enumerate(actors)]
        p.speech = SimpleNamespace(render_routine_pair=MagicMock(side_effect=render), play=MagicMock())
        p.turn = MagicMock(return_value={'transcript': 'Hey pumpkinhead sleep'})
        p.control = MagicMock()
        current = lambda: True
        with patch('pumpkin.listen', return_value=b''):
            p.play_game('patch', current, key='scare_shift')
        self.assertEqual([c.kwargs['cues'] for c in p.speech.play.call_args_list],
                         [[(0, 'patch'), (1, 'boo')], [(0, 'patch'), (1, 'nibbles')]])
        p.speech.play.reset_mock()
        with patch('pumpkin.listen', return_value=b'audio'):
            p.play_game('patch', current, key='scare_shift')
        self.assertEqual(p.speech.play.call_count, 1)
        p.control.assert_called_once_with('sleep', 'boo', current=current)

    def test_routine_pair_preserves_audio_and_character_timing(self):
        from pumpkin import Speech
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            directory = Path(directory)
            source = directory / 'line.wav'
            with wave.open(str(source), 'wb') as audio:
                audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                audio.writeframes(bytes(4800))
            speech = Speech(SimpleNamespace())
            speech.cache = directory
            with patch.object(speech, 'render', return_value=source) as render:
                path, cues = speech.render_routine_pair('scare_shift', 0, lambda: True)
            self.assertEqual([call.args[0] for call in render.call_args_list], ['patch', 'boo'])
            self.assertEqual(cues, [(0, 'patch'), (.28, 'boo')])
            with wave.open(str(path)) as audio:
                self.assertEqual(audio.getnframes(), 9120)
            with wave.open(str(source), 'wb') as audio:
                audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                audio.writeframes(bytes(9600))
            with patch.object(speech, 'render', return_value=source):
                updated, updated_cues = speech.render_routine_pair('scare_shift', 0, lambda: True)
            self.assertNotEqual(updated, path)
            self.assertEqual(updated_cues, [(0, 'patch'), (.38, 'boo')])
            with patch.object(speech, 'render') as render:
                self.assertIsNone(speech.render_routine_pair('scare_shift', 0, lambda: False))
                render.assert_not_called()

    def test_pumpkin_spell_inserts_snap_and_turns_voldemort_orange(self):
        from pumpkin import Speech
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            directory = Path(directory)
            effect = directory / 'assets/effects/finger-snap.wav'
            effect.parent.mkdir(parents=True)
            source = directory / 'line.wav'
            for path, frames in [(source, 2400), (effect, 5760)]:
                with wave.open(str(path), 'wb') as audio:
                    audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                    audio.writeframes(bytes(frames * 2))
            speech = Speech(SimpleNamespace())
            speech.cache = directory / 'cache'
            speech.cache.mkdir()
            with patch('pumpkin.ROOT', directory), patch.object(speech, 'render', return_value=source):
                path, cues = speech.render_routine_pair('pumpkin_voldemort', 4, lambda: True)
            self.assertEqual(cues, [(0, 'dobby'), (.28, 'voldemort'), (.52, 'voldemort_pumpkin')])
            with wave.open(str(path)) as audio:
                self.assertEqual(audio.getnframes(), 14880)

    def test_routine_lights_follow_the_speaking_character_after_preroll(self):
        from pumpkin import Speech
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            source = Path(directory) / 'speech.wav'
            with wave.open(str(source), 'wb') as audio:
                audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                audio.writeframes(bytes(48000))
            lights = SimpleNamespace(level=None, character='patch')
            speech = Speech(lights)
            speech.preroll = .2
            process = MagicMock()
            process.poll.side_effect = [None, None, None, 0]
            process.returncode = 0
            seen = []
            with patch('pumpkin.subprocess.Popen', return_value=process), \
                 patch('pumpkin.time.monotonic', side_effect=[0, .1, .3, .8]), \
                 patch('pumpkin.time.sleep', side_effect=lambda _: seen.append(lights.character)):
                speech.play(source, 'patch', cues=[(0, 'patch'), (.5, 'boo')])
            self.assertEqual(seen[:3], ['patch', 'patch', 'boo'])

    def test_temporary_fallback_does_not_replace_cached_routine_voices(self):
        from pumpkin import Speech
        parts = []
        target = None
        try:
            with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
                for _ in range(2):
                    with tempfile.NamedTemporaryFile(dir='/dev/shm', suffix='.wav', delete=False) as file:
                        path = Path(file.name)
                    parts.append(path)
                    with wave.open(str(path), 'wb') as audio:
                        audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                        audio.writeframes(bytes(4800))
                speech = Speech(SimpleNamespace())
                speech.cache = Path(directory)
                with patch.object(speech, 'render', side_effect=parts):
                    target, _ = speech.render_routine_pair('scare_shift', 0, lambda: True)
                self.assertEqual(target.parent, Path('/dev/shm'))
                self.assertTrue(target.exists())
                self.assertFalse(list(speech.cache.glob('routine-*.wav')))
                self.assertTrue(all(not path.exists() for path in parts))
        finally:
            for path in parts:
                path.unlink(missing_ok=True)
            if target is not None:
                target.unlink(missing_ok=True)
