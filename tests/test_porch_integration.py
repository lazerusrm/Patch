from datetime import datetime, timedelta, timezone
import io
import random
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import wave

from unifi_client import UniFiBridge
from visitor_motion import VisitorMotion
from porch_bits import DOORBELL_BITS, DOORSTEP_BITS, FILLER_BITS, choose, choose_bit, resolve, scene_lines
from sorting_ceremonies import AUTHORED_SORTING


def box(area):
    return [0, 0, area ** .5, area ** .5, .9]


class PorchIntegrationTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict('os.environ', {'PREMATURE_RING_CHANCE': '0', 'DOORSTEP_DANCE_CHANCE': '0'})
        patcher.start()
        self.addCleanup(patcher.stop)


    def _bit_pumpkin(self, internal=''):
        import pumpkin
        p = object.__new__(pumpkin.Pumpkin)
        effect = pumpkin.ROOT / 'assets/effects/polite-ding.wav'
        p.last_bit = None
        p.set_status = MagicMock()
        p.encounter = SimpleNamespace(generation=1)
        p.speech = SimpleNamespace(render=MagicMock(return_value=effect), render_doorbell=MagicMock(return_value=effect),
                                   play=MagicMock(), say=MagicMock(), internal_output=internal)
        return p

    def test_doorbell_line_then_porch_punchline_in_order(self):
        p = self._bit_pumpkin()
        order = []
        p.bridge = SimpleNamespace(available=lambda target: target == 'doorbell',
                                   play=lambda *a: order.append('doorbell') or True)
        p.speech.play.side_effect = lambda *a, **k: order.append('porch')
        with patch('pumpkin.choose', return_value='snitch'):
            spoken = p.perform_bit('patch', lambda: True)
        self.assertEqual(order, ['doorbell', 'porch'])
        self.assertEqual(len(spoken), 2)
        self.assertTrue(spoken[0]['text'].startswith('The doorbell: '))
        p.speech.render_doorbell.assert_called_once()

    def test_inside_step_uses_internal_speaker_and_porch_keeps_reply(self):
        p = self._bit_pumpkin('plughw:CARD=UACDemoV10,DEV=0')
        p.bridge = SimpleNamespace(available=lambda target: False, play=MagicMock(return_value=True))
        with patch('pumpkin.choose', return_value='roommate'):
            p.perform_bit('patch', lambda: True)
        first, second = p.speech.play.call_args_list
        self.assertEqual(first.kwargs['device'], 'plughw:CARD=UACDemoV10,DEV=0')
        self.assertEqual(first.args[1], 'voldemort_pumpkin')
        self.assertEqual(p.speech.render.call_args_list[0].args[0], 'voldemort')
        self.assertNotIn('device', second.kwargs)
        self.assertEqual(second.args[1], 'patch')

    def test_inside_bits_fall_back_cleanly_without_internal_speaker(self):
        for _ in range(30):
            key = choose(FILLER_BITS, None, 'patch', inside=False)
            self.assertFalse(any(step[0] == 'inside' for step in FILLER_BITS[key]))
        self.assertIsNone(choose({'only': FILLER_BITS['secret']}, None, 'patch', inside=False))

    def test_missing_cue_abandons_punchline_and_does_not_overlap_local_speech(self):
        p = self._bit_pumpkin()
        p.bridge = SimpleNamespace(available=lambda target: True, play=MagicMock(return_value=False))
        with patch('pumpkin.choose', return_value='hold'):  # Doorbell cue first, then the porch punchline.
            p.perform_bit('patch', lambda: True)
        p.speech.play.assert_not_called()
        p.speech.render.assert_not_called()

    def test_engaged_visitor_only_gets_friendly_doorstep_bits(self):
        p = self._bit_pumpkin('plughw:x')
        p.bridge = SimpleNamespace(available=lambda target: True, play=MagicMock(return_value=True))
        p.engaged_generation = 1
        for _ in range(20):
            p.last_doorstep_at = 0
            p.perform_bit('patch', lambda: True, kind='doorstep')
            self.assertIn(p.last_bit, ('fake_ring', 'trapped_tip'))

    def test_every_scene_resolves_for_every_host(self):
        from core import CHARACTERS
        for bank in (DOORBELL_BITS, DOORSTEP_BITS, FILLER_BITS):
            for key, scene in bank.items():
                hosts = [c for c in CHARACTERS if resolve(scene, c) is not None]
                self.assertTrue(hosts, key)
                for _, text in scene_lines(scene):
                    self.assertLessEqual(len(text.split()), 25, text)

    def test_varied_bits_and_short_sorting_lines(self):
        previous = None
        for _ in range(30):
            key = choose_bit(previous, character='patch')
            self.assertNotEqual(key, previous)
            previous = key
        self.assertTrue(all(len(line.split()) <= 45 for line in AUTHORED_SORTING))

    def test_common_reply_skips_remote_dialogue_and_tts_generation(self):
        from core import Encounter
        from pumpkin import Pumpkin
        from porch_bits import QUICK_REPLIES,quick_reply
        p=object.__new__(Pumpkin)
        p.busy=threading.Lock();p.stop=threading.Event()
        p.controls=SimpleNamespace(mode='normal',sleeping=False)
        p.encounter=Encounter(active=True,generation=1);p.status={'character':'dobby'}
        p.choose_character=MagicMock(return_value='dobby');p.set_status=MagicMock()
        p.turn=MagicMock(return_value={'transcript':'Hello Dobby, how are you?'})
        p.speech=SimpleNamespace(say=MagicMock(side_effect=lambda *a,**kw:p.stop.set()))
        with patch('pumpkin.listen',return_value=b'speech'):
            p.interact(generation=1,resume=True)
        self.assertEqual(p.turn.call_count,1)
        self.assertTrue(p.turn.call_args.kwargs['listen_only'])
        self.assertEqual(p.speech.say.call_args.args[1],QUICK_REPLIES['wellbeing']['dobby'])
        self.assertEqual(quick_reply('dobby','Thanks, but where is the candy?'),'')

    def test_compact_bridge_upload_preserves_padded_duration_and_job_identity(self):
        import subprocess
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            path = Path(directory)/'voice.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setparams((1,2,24000,0,'NONE','not compressed'))
                wav.writeframes(bytes(48000))
            client = UniFiBridge()
            client.health={'ready':True,'capabilities':{'audio':True,'audio_compact':True}}
            client.request=MagicMock(side_effect=[SimpleNamespace(json=lambda:{'id':'compact','state':'playing'}),
                                                   SimpleNamespace(json=lambda:{'state':'finished'})])
            self.assertTrue(client.play('doorbell',path,lambda:True))
            sent=client.request.call_args_list[0]
            self.assertEqual(sent.kwargs['headers']['Content-Type'],'audio/ogg')
            self.assertEqual(sent.kwargs['headers']['X-Loudness'],'raw')
            pcm=subprocess.check_output(['ffmpeg','-v','error','-f','ogg','-i','pipe:0',
                                         '-ar','24000','-ac','1','-f','s16le','pipe:1'],input=sent.kwargs['data'])
            self.assertEqual(len(pcm),74400)  #1sec voice +0.25 lead/0.3 drain padding, preserved by Opus.
            self.assertEqual(client.request.call_args_list[1].args,('GET','/audio/compact'))

    def test_disconnected_indoor_chime_does_not_crash_completed_sorting(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.chime_output = 'bluealsa:DEV=11:22:33:44:55:66,PROFILE=a2dp'
        p.chime_preroll = .25
        p.speech = SimpleNamespace(play=MagicMock(side_effect=RuntimeError('disconnected')))
        with self.assertLogs(level='WARNING'):
            self.assertFalse(p.play_chime(Path('cue.wav'), 'sorting_hat', lambda: True))

    def test_events_deduplicate_expire_and_motion_end_is_not_departure(self):
        client = UniFiBridge()
        stamp = datetime.now(timezone.utc)
        event = {'id': 'ring1', 'type': 'doorbell.ring', 'occurred_at': stamp.isoformat()}
        client.ingest([event, event, {**event, 'id': 'old', 'occurred_at': (stamp - timedelta(minutes=1)).isoformat()}])
        self.assertEqual(client.take()['id'], 'ring1')
        self.assertIsNone(client.take())
        client.ingest([{**event, 'id': 'motion-end', 'type': 'motion.ended'}])
        self.assertIsNone(client.take())
        client.ingest([{**event, 'id': 'bad', 'occurred_at': 3}])
        self.assertIsNone(client.take())

    def test_quick_second_press_counts_and_drain_keeps_one(self):
        client = UniFiBridge()
        stamp = datetime.now(timezone.utc).isoformat()
        client.ingest([{'id': 'a', 'type': 'doorbell.ring', 'occurred_at': stamp}])
        client.last_ring -= 3  # Second press 3 s later: counted (it was dropped under 8 s before).
        client.ingest([{'id': 'b', 'type': 'doorbell.ring', 'occurred_at': stamp}])
        client.ingest([{'id': 'c', 'type': 'doorbell.ring', 'occurred_at': stamp}])  # Bounce: ignored.
        self.assertEqual(len(client.press_times), 2)
        self.assertEqual(client.drain(keep=1), 2)
        self.assertEqual(client.take()['id'], 'b')
        self.assertIsNone(client.take())

    def test_old_word_bits_cover_every_host_with_a_doorbell_correction(self):
        for key in ('old_word', 'old_word_cool', 'old_word_message'):
            for host in ('patch', 'trogdor', 'sorting_hat'):
                steps = resolve(FILLER_BITS[key], host)
                self.assertIsNotNone(steps, (key, host))
                self.assertEqual(steps[1][0], 'doorbell')
                self.assertTrue(all(step[2] for step in steps))

    def test_stationary_people_and_camera_failure_never_trigger_farewell(self):
        m = VisitorMotion()
        for i in range(20):
            self.assertFalse(m.observe([box(.1)], i * .2, 1, True))
        self.assertFalse(m.observe([], 4, 1, True))
        self.assertFalse(m.observe([box(.1)], 5, 1, True))
        self.assertFalse(m.observe([], 6, 1, True, camera_ok=False))
        self.assertFalse(m.observe([], 9, 1, True))
        self.assertFalse(m.observe([box(.1)], 10, 1, True))
        self.assertFalse(m.observe([], 11, 1, True))
        self.assertTrue(m.observe([], 13.1, 1, True))
        self.assertFalse(m.observe([box(.1)], 13.2, 1, True))

    def test_retreat_requires_calibration_and_rejects_single_size_jump(self):
        for enabled in (False, True):
            m = VisitorMotion(allow_retreat=enabled)
            for i, area in enumerate((.12, .1, .085, .07, .06, .05)):
                departing = m.observe([box(area)], i * .25, 1, True)
            self.assertEqual(departing, enabled)
        m = VisitorMotion(allow_retreat=True)
        for i, area in enumerate((.12, .12, .12, .12, .05, .05)):
            self.assertFalse(m.observe([box(area)], i * .25, 1, True))

    def test_remote_audio_finishes_before_next_turn_and_cancels_on_departure(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            path = Path(directory) / 'test.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\x01\x00' * 24000)
            client = UniFiBridge()
            client.health = {'ready': True, 'capabilities': {'audio': True}}
            response = lambda **values: SimpleNamespace(json=lambda: values)
            client.request = MagicMock(side_effect=[response(id='owned', state='playing'), response(state='finished')])
            self.assertTrue(client.play('doorbell', path, lambda: True))
            self.assertEqual([call.args[0] for call in client.request.call_args_list], ['POST', 'GET'])
            self.assertEqual(client.request.call_args_list[0].kwargs['headers']['X-Loudness'], 'raw')
            with wave.open(io.BytesIO(client.request.call_args_list[0].kwargs['data'])) as sent:
                self.assertEqual(sent.getnframes(), 37200)  # 1 s + 0.25 s lead + 0.3 s drain
                self.assertEqual(sent.readframes(6000), bytes(12000))
                self.assertEqual(sent.readframes(24000), b'\x01\x00' * 24000)
                self.assertEqual(sent.readframes(7200), bytes(14400))
            client.request = MagicMock(return_value=response(id='owned', state='playing'))
            checks = iter([True, False])
            self.assertFalse(client.play('doorbell', path, lambda: next(checks)))
            self.assertEqual(client.request.call_args_list[-1].args, ('DELETE', '/audio/owned'))

    def sorting_pumpkin(self, status, look):
        from concurrent.futures import Future
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.status = status
        p.set_status = MagicMock()
        p.stop = threading.Event()
        p.bridge = SimpleNamespace(available=lambda target: True, play=MagicMock(return_value=True))
        p.speech = SimpleNamespace(render_lines=MagicMock(return_value=Path('/fake/ceremony.wav')),
                                   play=MagicMock(), say=MagicMock())
        p.turn = MagicMock(return_value=look)
        pool = MagicMock()
        def complete(function, *args, **kwargs):
            result = Future()
            if look is not None:
                result.set_result(function(*args, **kwargs))
            return result
        pool.submit.side_effect = complete
        return p, pool

    def test_sort_me_sends_visitor_from_the_door_back_to_the_path_then_comments_and_sorts(self):
        from sorting_ceremonies import POSITION
        p, pool = self.sorting_pumpkin({'people': 1, 'doorstep_people': 1},
                                       {'text': 'That splendid cape deserves a suitably dramatic destination.'})
        def step_back(*args, **kwargs):
            p.status.update(doorstep_people=0, doorbell_people=1)  # They walk back onto the straight path.
        p.speech.say.side_effect = step_back
        with patch('pumpkin.ThreadPoolExecutor', return_value=pool):
            house = p.sort_visitor(lambda: True, observe=True)
        self.assertIn(p.speech.say.call_args_list[0].args[1], POSITION['doorbell'])
        self.assertEqual(p.turn.call_args.kwargs['camera'], 'doorbell')
        self.assertEqual(p.turn.call_args.kwargs['purpose'], 'sorting')
        p.speech.play.assert_called_once()
        line = p.speech.play.call_args.kwargs['text']
        self.assertTrue(line.startswith('That splendid cape'))
        self.assertIn(house.upper() + '!', line)
        self.assertIn('splendid cape', p.sorting_vision.result()['text'])

    def test_sort_me_uses_webcam_and_falls_back_when_nobody_appears(self):
        from sorting_ceremonies import NOT_FOUND, POSITION, UNSURE
        p, pool = self.sorting_pumpkin({'people': 0, 'webcam_people': 0, 'doorbell_people': 0}, None)
        with patch('pumpkin.ThreadPoolExecutor', return_value=pool), \
             patch.dict('os.environ', {'SORT_POSITION_SECONDS': '0.3'}):
            house = p.sort_visitor(lambda: True, observe=True)
        said = [c.args[1] for c in p.speech.say.call_args_list]
        self.assertIn(said[0], POSITION['webcam'])
        self.assertEqual(said[-1], NOT_FOUND)
        p.turn.assert_not_called()  # Nobody in view: no camera request.
        self.assertTrue(p.speech.play.call_args.kwargs['text'].startswith(UNSURE))

    def test_sort_me_never_hangs_on_a_slow_look(self):
        from sorting_ceremonies import UNSURE
        p, pool = self.sorting_pumpkin({'people': 1, 'webcam_people': 1}, None)
        with patch('pumpkin.ThreadPoolExecutor', return_value=pool), \
             patch.dict('os.environ', {'SORT_LOOK_SECONDS': '0.2'}):
            house = p.sort_visitor(lambda: True, observe=True)
        self.assertTrue(p.speech.play.call_args.kwargs['text'].startswith(UNSURE))
        self.assertIn(house.upper(), p.speech.play.call_args.kwargs['text'])
