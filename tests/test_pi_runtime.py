import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock
import wave
import threading
import time


class PiRuntimeTests(unittest.TestCase):
    def test_doorbell_explicitly_uses_clear_local_voice_and_caches_it(self):
        import io,math,shutil
        from array import array
        from pumpkin import Speech
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as wav:
            wav.setparams((1,2,24000,0,'NONE','not compressed'))
            wav.writeframes(array('h',(int(1500*math.sin(i*.2)) for i in range(24000))).tobytes())
        response=SimpleNamespace(content=buffer.getvalue(),raise_for_status=lambda:None)
        with tempfile.TemporaryDirectory() as directory:
            speech=Speech(SimpleNamespace());speech.cache=Path(directory)
            with patch('pumpkin.requests.post',return_value=response) as request, \
                 patch('pumpkin.normalize_wav',side_effect=shutil.copyfile):
                path=speech.render_doorbell('Hello there.')
                self.assertEqual(speech.render_doorbell('Hello there.'),path)
            request.assert_called_once()
            self.assertEqual(request.call_args.args[0],'http://127.0.0.1:8765/tts')
            self.assertEqual(request.call_args.kwargs['data']['voice_url'],'alba')
            with wave.open(str(path)) as wav:
                self.assertEqual((wav.getframerate(),wav.getnchannels()),(24000,1))

    def test_ceremony_joins_cached_lines_into_one_pcm_file(self):
        from array import array
        from pumpkin import Speech
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            source=Path(directory)/'line.wav'
            with wave.open(str(source),'wb') as wav:
                wav.setparams((1,2,24000,0,'NONE','not compressed'))
                wav.writeframes(array('h',[1000]*2400).tobytes())
            speech=Speech(SimpleNamespace());speech.cache=Path(directory)
            with patch.object(speech,'render',return_value=source):
                path=speech.render_lines('sorting_hat',['Opening.','Verdict.'],lambda:True)
            with wave.open(str(path)) as wav:
                self.assertEqual(wav.getnframes(),10800)
            self.assertIsNone(speech.render_lines('sorting_hat',['Stop.'],lambda:False))

    def test_only_recent_audible_music_allows_zero_bluetooth_lead_in(self):
        import os
        from pumpkin import Speech
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            path = Path(directory)/'voice.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setparams((1,2,24000,0,'NONE','not compressed'))
                wav.writeframes(bytes(48000))
            with patch.dict(os.environ, {'AUDIO_OUTPUT':'bluealsa:DEV=test', 'SPEAKER_BUS':'0',
                                         'AUDIO_PREROLL_SECONDS':'3', 'AUDIO_WARM_PREROLL_SECONDS':'0'}):
                speech = Speech(SimpleNamespace())
            speech.last_output_end = 95
            process = MagicMock()
            process.poll.return_value = 0
            process.returncode = 0
            def open_player(command,**kwargs):
                with wave.open(command[-1]) as wav:
                    self.assertEqual(wav.getnframes(),expected_frames)
                return process
            with patch('pumpkin.time.monotonic',return_value=100), \
                 patch('pumpkin.subprocess.Popen',side_effect=open_player),patch('pumpkin.time.sleep'):
                for signal, expected_frames in ((99.6,24000),(99,96000),(None,96000)):
                    speech.last_music_signal = signal
                    speech.play(path,'patch')
                speech.prepared_at=99.8
                expected_frames=24000
                speech.play(path,'patch')

    def test_clone_outage_cannot_silently_select_another_voice_engine(self):
        import os
        import requests
        from pumpkin import Speech
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            token = Path(directory) / 'token'
            token.write_text('a' * 40)
            speech = Speech(SimpleNamespace())
            speech.cache = Path(directory)
            with patch.dict(os.environ, {'TTS_URL':'http://selected.invalid/tts',
                                         'PUMPKIN_TOKEN_FILE':str(token)}), \
                 patch('pumpkin.requests.post', side_effect=requests.ConnectionError()) as request:
                with self.assertRaises(requests.ConnectionError):
                    speech.render('dobby', 'Unique outage test utterance.')
            request.assert_called_once()
            self.assertEqual(request.call_args.args[0], 'http://selected.invalid/tts')

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

    def test_split_reply_plays_first_sentence_then_rest(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        order = []
        def render(character, text, prefetched=None):
            order.append(('render', text, prefetched is not None))
            return Path('/nonexistent/' + str(len(order)) + '.wav')
        p.speech = SimpleNamespace(render=render, play=lambda path, c, text, current=None: order.append(('play', text)))
        result = {'text': 'Yes! Dobby is a free elf. Getting out is trickier.',
                  'voice_text': 'Yes! Dobby is a free elf.', 'rest': 'Getting out is trickier.'}
        p.speak_reply('dobby', result, (b'OggS', 'qwen3-tts-1.7b'), lambda: True)
        played = [item[1] for item in order if item[0] == 'play']
        self.assertEqual(played, ['Yes! Dobby is a free elf.', 'Getting out is trickier.'])
        self.assertIn(('render', 'Yes! Dobby is a free elf.', True), order)
        self.assertIn(('render', 'Getting out is trickier.', False), order)

    def reaction_pumpkin(self, cached=True, inside=True):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.speech = SimpleNamespace(bus=object(), cached=lambda c, t: cached, say=MagicMock(),
                                   internal_output='plughw:inside' if inside else '')
        p.perform_scene = MagicMock(return_value=[])
        return p

    def test_reaction_heckles_only_while_the_reply_is_not_ready(self):
        p = self.reaction_pumpkin()
        waiting = threading.Event()
        with patch('pumpkin.random.random', return_value=0):
            p.start_reaction('patch', lambda: True, ready=waiting).join(2)
        p.speech.say.assert_called_once()
        steps = p.perform_scene.call_args.args[0]
        self.assertEqual([(s[0], s[3]) for s in steps], [('inside', 'voldemort')])
        p = self.reaction_pumpkin()
        done = threading.Event(); done.set()
        with patch('pumpkin.random.random', return_value=0):
            p.start_reaction('patch', lambda: True, ready=done).join(2)
        p.perform_scene.assert_not_called()  # Reply ready: straight to it, no heckle.

    def test_reaction_alone_when_no_inside_speaker(self):
        p = self.reaction_pumpkin(inside=False)
        with patch('pumpkin.random.random', return_value=0):
            p.start_reaction('dobby', lambda: True).join(2)
        p.speech.say.assert_called_once()
        p.perform_scene.assert_not_called()

    def test_uncached_reaction_is_skipped_so_reply_keeps_the_voice_server(self):
        p = self.reaction_pumpkin(cached=False)
        self.assertIsNone(p.start_reaction('patch', lambda: True))

    def trogdor_pumpkin(self, inside=True, doorbell=True):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.speech = SimpleNamespace(internal_output='plughw:inside' if inside else '')
        p.bridge = SimpleNamespace(available=lambda target: doorbell)
        p.perform_scene = MagicMock(return_value=[{'role': 'assistant', 'text': 'roar'}])
        p.play_game = MagicMock()
        p.set_status = MagicMock()
        return p

    def test_trogdor_mention_plays_scene_then_cools_down(self):
        p = self.trogdor_pumpkin()
        with patch('pumpkin.random.choice', side_effect=lambda options: 'summon' if 'summon' in options else options[0]):
            self.assertEqual(p.trogdor_scene('patch', lambda: True), [{'role': 'assistant', 'text': 'roar'}])
        actors = {step[3] for step in p.perform_scene.call_args.args[0]}
        self.assertTrue({'patch', 'trogdor', 'doorbell'} <= actors)
        self.assertIsNone(p.trogdor_scene('patch', lambda: True))  # Cooldown: next mention gets a real reply.

    def test_trogdor_scenes_skip_missing_speakers_and_rotate(self):
        from porch_bits import TROGDOR_BITS, uses_inside
        p = self.trogdor_pumpkin(inside=False, doorbell=False)
        seen = []
        with patch.dict('os.environ', {'TROGDOR_COOLDOWN_SECONDS': '0'}):
            for _ in range(4):
                p.trogdor_scene('patch', lambda: True)
                seen.append(p.recent_trogdor[-1])
        self.assertEqual(len(set(seen)), 4)
        for key in seen:
            if key in TROGDOR_BITS:
                scene = TROGDOR_BITS[key]
                self.assertFalse(uses_inside(scene))
            else:
                from games import GAMES
                self.assertFalse(any(':inside' in actor for actor in GAMES[key]['cast']))

    def test_porch_bulbs_follow_speaker_sleep_and_accents(self):
        from pumpkin import wiz_pilot, WIZ_COLORS, FIRE, HOUSE_COLORS
        lights = SimpleNamespace(level=.5, character='voldemort_pumpkin', sleeping=False, accents=[], wiz_sleep_dimming=30)
        pilot = wiz_pilot(lights, 10)
        self.assertEqual((pilot['r'], pilot['g'], pilot['b']), WIZ_COLORS['voldemort'])  # Heckles glow green.
        self.assertEqual(pilot['dimming'], 65)
        lights.accents = [(5, 20, 'flicker', FIRE)]
        pilot = wiz_pilot(lights, 10)
        self.assertEqual((pilot['r'], pilot['g'], pilot['b']), FIRE)
        self.assertTrue(45 <= pilot['dimming'] <= 100)
        lights.accents.append((8, 12, 'off', None))  # Newest cue wins while active.
        self.assertEqual(wiz_pilot(lights, 10), {'state': False})
        self.assertEqual(wiz_pilot(lights, 13)['r'], FIRE[0])
        lights.accents = [(0, 9, 'cycle', None)]
        self.assertIn(tuple(wiz_pilot(lights, 1)[k] for k in 'rgb'), [tuple(c) for c in HOUSE_COLORS.values()])
        self.assertEqual(wiz_pilot(lights, 30)['g'], WIZ_COLORS['voldemort'][1])  # Cues expired.
        lights.level = None
        idle = wiz_pilot(lights, 30)
        self.assertEqual((idle['r'], idle['b']), (255, 0))
        lights.sleeping = True
        self.assertEqual(wiz_pilot(lights, 30), {'temp': 2700, 'dimming': 30})

    def test_scene_light_step_schedules_cue_without_sound(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        cues = []
        p.speech = SimpleNamespace(internal_output='', bus=None,
                                   lights=SimpleNamespace(cue=lambda name, seconds, start=0: cues.append((name, seconds))))
        p.scene_path = MagicMock()
        p.perform_scene([('lights', 'light', 'blackout:6', 'patch')], 'patch', lambda: True)
        self.assertEqual(cues, [('blackout', 6.0)])
        p.scene_path.assert_not_called()

    def test_doorbell_and_dragon_steps_flash_porch_bulbs(self):
        from pumpkin import Pumpkin, FIRE, WIZ_COLORS
        p = object.__new__(Pumpkin)
        flashes = []
        p.speech = SimpleNamespace(lights=SimpleNamespace(flash=lambda rgb, seconds, flicker=False, start=0: flashes.append((rgb, flicker))))
        p.light_accent('doorbell', 'text', 'Package detected.', Path('/nonexistent.wav'))
        p.light_accent('porch', 'effect', 'roar', Path('/nonexistent.wav'))
        p.light_accent('porch', 'text', 'Hello there.', Path('/nonexistent.wav'))
        self.assertEqual(flashes, [(WIZ_COLORS['doorbell'], False), (FIRE, True)])

    def interactive_pumpkin(self, heard=(), seen=True, look='That bucket is suspiciously orange and alarmingly full.'):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        cues = []
        p.speech = SimpleNamespace(say=MagicMock(), bus=None, internal_output='',
                                   lights=SimpleNamespace(cue=lambda name, seconds, start=0: cues.append(name), accents=[]))
        p.cues = cues
        p.stop = threading.Event()
        p.status = {'webcam_people': 1 if seen else 0}
        p.bridge = SimpleNamespace(available=lambda target: False)
        answers = list(heard)
        p.ask = MagicMock(side_effect=lambda c, line, current, expect=(): answers.pop(0) if answers else '')
        p.turn = MagicMock(return_value={'text': look})
        return p

    def test_lumos_bit_lights_up_then_nox_puts_lights_to_bed(self):
        from porch_bits import INTERACTIVE
        p = self.interactive_pumpkin(heard=['Lumos!', 'Nox'])
        p.interactive_bit('lumos', 'dobby', lambda: True)
        self.assertEqual(p.cues, ['lumos', 'blackout'])
        said = [c.args[1] for c in p.speech.say.call_args_list]
        self.assertEqual(said, [INTERACTIVE['lumos']['success']['dobby'], INTERACTIVE['lumos']['nox_done']['*']])

    def test_misheard_nox_still_puts_the_lights_to_bed(self):
        p = self.interactive_pumpkin(heard=['Lumos!', 'Knocks?'])
        p.interactive_bit('lumos', 'patch', lambda: True)
        self.assertEqual(p.cues, ['lumos', 'blackout'])
        p = self.interactive_pumpkin(heard=['Lumos!', '...'])  # Speech heard but not understood.
        p.interactive_bit('lumos', 'patch', lambda: True)
        self.assertEqual(p.cues, ['lumos', 'blackout'])
        p = self.interactive_pumpkin(heard=['Lumos!', ''])  # Silence: lights stay up.
        p.interactive_bit('lumos', 'patch', lambda: True)
        self.assertEqual(p.cues, ['lumos'])

    def test_inspection_bit_looks_through_the_camera_and_reacts(self):
        from porch_bits import INTERACTIVE
        p = self.interactive_pumpkin()
        with patch('pumpkin.ThreadPoolExecutor') as pool:
            pool.return_value.submit.side_effect = lambda f, *a, **k: SimpleNamespace(result=lambda timeout: f(*a, **k))
            spoken = p.interactive_bit('inspection', 'nibbles', lambda: True)
        self.assertEqual(p.turn.call_args.kwargs['purpose'], 'inspection')
        self.assertEqual(p.turn.call_args.kwargs['camera'], 'webcam')
        texts = [item['text'] for item in spoken]
        self.assertIn('That bucket is suspiciously orange and alarmingly full.', texts)
        self.assertEqual(texts[-1], INTERACTIVE['inspection']['done']['nibbles'])

    def test_talent_bit_without_anyone_in_view_uses_authored_line(self):
        from porch_bits import INTERACTIVE
        p = self.interactive_pumpkin(seen=False)
        with patch('pumpkin.ThreadPoolExecutor'):
            spoken = p.interactive_bit('talent', 'boo', lambda: True)
        p.turn.assert_not_called()
        self.assertEqual(spoken[-1]['text'], INTERACTIVE['talent']['unseen']['*'])
        self.assertIn('lightning', p.cues)

    def test_long_visits_get_escalating_eviction_bits_once_each(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.status = {'character': 'patch'}
        p.speech = SimpleNamespace(internal_output='plughw:inside')
        p.visit_started = (3, 0)
        with patch('pumpkin.time.monotonic', return_value=100):
            self.assertIsNone(p.overstay_due(3))
        keys = []
        with patch('pumpkin.time.monotonic', return_value=1000):
            for _ in range(5):
                keys.append(p.overstay_due(3))
        self.assertEqual(keys, ['other_houses', 'moved_in', 'last_call', None, None])
        self.assertIsNone(p.overstay_due(4))  # A different visit.

    def test_boo_is_sped_up_without_other_voices_changing(self):
        import io, math, shutil
        from array import array
        from pumpkin import Speech
        tone = array('h', (int(6000 * math.sin(i * .05)) for i in range(24000)))
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as out:
            out.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
            out.writeframes((tone + array('h', bytes(48000)) + tone).tobytes())  # 1 s, 1 s pause, 1 s
        durations = {}
        with tempfile.TemporaryDirectory() as directory, \
             patch('pumpkin.normalize_wav', side_effect=lambda source, target, boost_db=0: shutil.copyfile(source, target)):
            token = Path(directory) / 'token'
            token.write_text('test-token')
            patcher = patch.dict('os.environ', {'PUMPKIN_TOKEN_FILE': str(token)})
            patcher.start()
            self.addCleanup(patcher.stop)
            speech = Speech(SimpleNamespace())
            speech.cache = Path(directory)
            for character in ('boo', 'patch'):
                path = speech.render(character, 'Pacing check line for ' + character,
                                     prefetched=(buffer.getvalue(), 'breeze-tts-2', 'raw'))
                with wave.open(str(path)) as audio:
                    durations[character] = audio.getnframes() / audio.getframerate()
                path.unlink()
        self.assertAlmostEqual(durations['patch'], 3, delta=.05)
        self.assertLess(durations['boo'], .85 * durations['patch'])  # Long pause shortened and 1.15x tempo.

    def test_special_mode_returns_to_normal_after_an_empty_porch(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.controls = SimpleNamespace(mode='trogdor', set_mode=MagicMock())
        p.busy = threading.Lock()
        p.encounter = SimpleNamespace(active=False)
        p.last_seen = 1000
        p.expire_mode(1100)
        p.controls.set_mode.assert_not_called()  # Someone was here a minute ago.
        p.expire_mode(1400)
        p.controls.set_mode.assert_called_once_with('normal')

    def test_overstay_without_inside_speaker_never_repeats_last_call(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.status = {'character': 'voldemort'}
        p.speech = SimpleNamespace(internal_output='plughw:inside')
        p.visit_started = (3, 0)
        with patch('pumpkin.time.monotonic', return_value=1000):
            keys = [p.overstay_due(3) for _ in range(4)]
        self.assertEqual(keys, ['other_houses', 'last_call', None, None])

    def test_lumos_lights_stay_up_when_nobody_says_nox(self):
        p = self.interactive_pumpkin(heard=['Lumos!', ''])
        p.speech.lights.accents = ['lumos-cue']
        p.interactive_bit('lumos', 'patch', lambda: True)
        self.assertEqual(p.speech.lights.accents, ['lumos-cue'])

    def pose_pumpkin(self, people):
        from pumpkin import Pumpkin
        p = self.interactive_pumpkin()
        p.pose_people = (time.monotonic() + 100, people)  # Always fresh during the test.
        return p

    def test_hands_up_poll_counts_raised_hands(self):
        from porch_bits import INTERACTIVE
        import pose
        up = {'box': (.1, .3, .9, .7, .9), 'keypoints': [(0, 0, 0)] * 17}
        with patch('pumpkin.pose.hands_raised', return_value=1):
            p = self.pose_pumpkin([up, up])
            with patch.object(p.stop, 'wait', return_value=None), patch('pumpkin.time.monotonic', side_effect=lambda c=iter(range(1000)): next(c) * .5):
                spoken = p.interactive_bit('hands_up', 'patch', lambda: True)
        self.assertEqual(spoken[-1]['text'], INTERACTIVE['hands_up']['some']['*'])

    def test_raised_hand_is_called_on_once_per_raise(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        with patch('pumpkin.pose.hands_raised', return_value=1):
            with patch('pumpkin.time.monotonic', return_value=10):
                p.observe_pose([{'box': (0, 0, 1, 1, .9)}])
            with patch('pumpkin.time.monotonic', return_value=10.5):
                p.observe_pose([{'box': (0, 0, 1, 1, .9)}])
                self.assertTrue(p.hand_up)
                self.assertTrue(p.take_hand())
                self.assertFalse(p.take_hand())  # Cooldown: not called on twice for one raise.

    def test_rings_within_15_seconds_escalate(self):
        from pumpkin import Pumpkin
        from porch_bits import RING_AGAIN_BITS, RING_THIRD_BITS, DOORBELL_BITS
        p = object.__new__(Pumpkin)
        p.bridge = SimpleNamespace(available=lambda target: True)
        p.speech = SimpleNamespace(internal_output='plughw:inside')
        p.encounter = SimpleNamespace(generation=1)
        p.engaged_generation = 1  # Talked to the host first, so no 'rang too early' bit.
        p.last_bit = None
        p.set_status = MagicMock()
        played = []
        p.perform_scene = MagicMock(side_effect=lambda steps, character, valid: played.append(steps) or [])
        banks = []
        with patch('pumpkin.choose', side_effect=lambda bank, *a, **k: banks.append(bank) or next(iter(bank))), \
             patch('pumpkin.time.monotonic', side_effect=[100, 100, 105, 105, 109, 109, 200, 200]):
            for _ in range(4):
                p.perform_bit('patch', lambda: True, kind='ring')
        self.assertEqual(banks, [DOORBELL_BITS, RING_AGAIN_BITS, RING_THIRD_BITS, DOORBELL_BITS])

    def test_unsplit_reply_plays_whole_text_once(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.speech = SimpleNamespace(render=MagicMock(return_value=Path('/nonexistent/a.wav')), play=MagicMock())
        p.speak_reply('patch', {'text': 'Whole line.'}, (b'OggS', 'breeze-tts-2'), lambda: True)
        p.speech.render.assert_called_once_with('patch', 'Whole line.', prefetched=(b'OggS', 'breeze-tts-2'))
        self.assertEqual(p.speech.play.call_count, 1)

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

    def test_candidate_cancels_idle_capture_before_arrival_is_confirmed(self):
        from pumpkin import Pumpkin
        from core import Encounter
        p = object.__new__(Pumpkin)
        p.busy = threading.Lock()
        p.controls = SimpleNamespace(sleeping=False)
        p.status = {'people': 1}
        p.set_status = MagicMock()
        p.stop = threading.Event()
        p.encounter = Encounter()
        with patch('pumpkin.listen') as capture:
            p.sleep_loop()
        capture.assert_not_called()
        self.assertFalse(p.busy.locked())

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
            with patch.dict(os.environ, {'AUDIO_OUTPUT': 'bluealsa:DEV=test', 'SPEAKER_BUS': '0', 'AUDIO_PREROLL_SECONDS': '3'}):
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

    def test_scripted_cast_plays_continuously_without_listening_gaps(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.last_game = None
        p.set_status = MagicMock()
        cues = [(0, 'patch'), (1, 'boo'), (2, 'patch'), (3, 'nibbles')]
        p.speech = SimpleNamespace(render_routine=MagicMock(return_value=(Path('/fake/routine.wav'), cues)),
                                   play=MagicMock())
        p.turn = MagicMock()
        current = lambda: True
        with patch('pumpkin.listen') as capture:
            p.play_game('patch', current, key='dark_entrance')
        capture.assert_not_called()
        p.turn.assert_not_called()
        p.speech.play.assert_called_once_with(Path('/fake/routine.wav'), 'patch', current=current, cues=cues)
        p.speech.play.reset_mock()
        p.play_game('patch', lambda: False, key='dark_entrance')
        p.speech.play.assert_not_called()

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
                path, cues = speech.render_routine_pair('dark_entrance', 0, lambda: True)
            self.assertEqual([call.args[0] for call in render.call_args_list], ['voldemort', 'dobby'])
            self.assertEqual(cues, [(0, 'voldemort'), (.28, 'dobby')])
            with wave.open(str(path)) as audio:
                self.assertEqual(audio.getnframes(), 9120)
            with wave.open(str(source), 'wb') as audio:
                audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                audio.writeframes(bytes(9600))
            with patch.object(speech, 'render', return_value=source):
                updated, updated_cues = speech.render_routine_pair('dark_entrance', 0, lambda: True)
            self.assertNotEqual(updated, path)
            self.assertEqual(updated_cues, [(0, 'voldemort'), (.38, 'dobby')])
            with patch.object(speech, 'render') as render:
                self.assertIsNone(speech.render_routine_pair('dark_entrance', 0, lambda: False))
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
                    target, _ = speech.render_routine_pair('dark_entrance', 0, lambda: True)
                self.assertEqual(target.parent, Path('/dev/shm'))
                self.assertTrue(target.exists())
                self.assertFalse(list(speech.cache.glob('routine-*.wav')))
                self.assertTrue(all(not path.exists() for path in parts))
        finally:
            for path in parts:
                path.unlink(missing_ok=True)
            if target is not None:
                target.unlink(missing_ok=True)


class LineGuardTests(unittest.TestCase):
    def test_started_line_finishes_when_the_visit_ends_near_its_end(self):
        from pumpkin import LineGuard
        live = [True]
        guard = LineGuard(lambda: live[0], duration=5.0)
        live[0] = False
        self.assertFalse(guard())  # Not started yet: dropped.
        guard.started = time.monotonic() - 1
        self.assertTrue(guard())   # 4 s left: finish it.

    def test_long_remainder_or_hard_stop_still_cuts(self):
        from pumpkin import LineGuard
        guard = LineGuard(lambda: False, duration=20.0)
        guard.started = time.monotonic()
        self.assertFalse(guard())  # 20 s left: cut.
        stopped = LineGuard(lambda: False, duration=3.0, hard_stop=lambda: True)
        stopped.started = time.monotonic()
        self.assertFalse(stopped())  # Raised hand / sleep / stop.


    def test_doorbell_press_cuts_even_a_live_line(self):
        from pumpkin import LineGuard
        cut = []
        guard = LineGuard(lambda: True, duration=3.0, preempt=lambda: True, on_preempt=lambda: cut.append(1))
        self.assertFalse(guard())
        self.assertEqual(cut, [])  # Not started: nothing to react to.
        guard.started = time.monotonic()
        self.assertFalse(guard())
        self.assertEqual(cut, [1])


class AlertLightTests(unittest.TestCase):
    def test_green_idle_fade_on_visitor_ring_strobe_and_hand_back(self):
        from alert_light import AlertLight, GREEN, ORANGE, restore_params
        a = AlertLight(macs='aa', clear_seconds=20, cycle_seconds=3)
        a.update(False, False, awake=True, now=0)
        self.assertEqual((a.target(0)['r'], a.target(0)['g']), GREEN[:2])  # Pumpkin running: green.
        a.update(True, False, awake=True, now=10)
        self.assertEqual(a.target(10)['g'], GREEN[1])                     # Fade starts at green...
        self.assertEqual(a.target(13)['r'], ORANGE[0])                    # ...orange after 3 s...
        self.assertEqual(a.target(16)['g'], GREEN[1])                     # ...green again at 6 s.
        mid = a.target(11.5)
        self.assertTrue(GREEN[0] < mid['r'] < ORANGE[0])                  # Smooth, not a jump.
        a.update(True, True, awake=True, now=20)
        self.assertNotEqual(a.target(20.1).get('r'), mid['r'])           # Ring strobe.
        a.update(False, False, awake=True, now=35)
        self.assertIsNotNone(a.visitor_since)                             # Not clear for 20 s yet.
        a.update(False, False, awake=True, now=41)
        self.assertIsNone(a.visitor_since)
        self.assertEqual(a.target(41)['g'], GREEN[1])
        a.update(False, False, awake=False, now=50)
        self.assertIsNone(a.target(50))                                   # Asleep: household light back.
        self.assertEqual(restore_params({'state': False, 'temp': 2700}), {'state': False})
        self.assertEqual(restore_params({'state': True, 'sceneId': 12, 'temp': 4200, 'dimming': 80}),
                         {'state': True, 'sceneId': 12, 'dimming': 80})

    def test_disabled_without_bulbs(self):
        from alert_light import AlertLight
        a = AlertLight(macs='')
        a.update(True, True, now=0)
        self.assertIsNone(a.visitor_since)


class GarageFireTests(unittest.TestCase):
    def mean_level(self, f, start, seconds):
        frames = [f.target(start + i * .12) for i in range(int(seconds / .12))]
        return sum(x['dimming'] for x in frames) / len(frames), frames

    def test_one_flickering_flame_hotter_for_visitors_and_trogdor(self):
        import random
        from garage_fire import FireLights
        f = FireLights(macs='aa', rng=random.Random(1))
        f.update(False, False, True, now=0)
        calm, frames = self.mean_level(f, 0, 20)
        self.assertGreater(len({x['dimming'] for x in frames}), 15)            # it flickers
        self.assertTrue(all(x['r'] == 255 and x['b'] == 0 for x in frames))     # fire colours only
        f.update(True, False, True, now=30)                                     # arrival: blaze, then roused
        blaze, _ = self.mean_level(f, 30, 3.5)
        roused, _ = self.mean_level(f, 36, 20)
        self.assertGreater(blaze, roused)
        self.assertGreater(roused, calm)
        f.update(False, False, True, now=100)
        self.assertEqual(f.mood(100), 'calm')
        f.flare(3, now=101)
        self.assertEqual(f.mood(102), 'blaze')
        f.update(awake=False, now=110)
        self.assertIsNone(f.target(110))                                        # asleep: handed back

class NightViewTests(unittest.TestCase):
    def test_dark_frames_switch_to_night_confidence_with_hysteresis(self):
        import numpy as np
        from pumpkin import Pumpkin
        from core import person_presence
        p = object.__new__(Pumpkin)
        p.webcam_visitor_score, p.webcam_night_score = .40, .28
        dark, dusk, bright = (np.full((48, 64, 3), v, np.uint8) for v in (30, 65, 120))
        self.assertTrue(p.night_view(dark))
        p.webcam_brightness_at = float('-inf'); self.assertTrue(p.night_view(dusk))    # stays night until clearly light
        p.webcam_brightness_at = float('-inf'); self.assertFalse(p.night_view(bright))
        dim_visitor = [(.3, .7, .7, .9, .32)]
        self.assertEqual(person_presence(dim_visitor, .40)[0], 0)
        self.assertEqual(person_presence(dim_visitor, .28)[0], 1)

    def test_corner_with_hidden_legs_counts_as_on_the_path(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.webcam_visitor_feet, p.webcam_corner_x, p.webcam_corner_feet = .52, .15, .45
        self.assertTrue(p.on_path((0, 0, .51, .11, .6)))        # at the corner, legs behind the plants
        self.assertFalse(p.on_path((0, .4, .51, .5, .6)))       # same height mid-frame: the sidewalk
        self.assertFalse(p.on_path((0, 0, .30, .1, .6)))        # head and shoulders only: not enough
        self.assertTrue(p.on_path((.2, .4, .7, .6, .6)))        # ordinary visitor on the path
