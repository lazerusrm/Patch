import json
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


class ModeTests(unittest.TestCase):
    def test_mode_switches_require_wake_phrase_and_allow_spoken_variants(self):
        from games import intent
        for words in ('Hey pumpkinhead Trogdor mode', 'Hey, pumpkin head, Trogdor mode!'):
            self.assertEqual(intent(words), 'trogdor_mode')
        self.assertEqual(intent('Hey pumpkinhead normal mode'), 'normal_mode')
        self.assertEqual(intent('Hey pumpkin head Dobby mode'), 'dobby_mode')
        self.assertEqual(intent('Hey pumpkinhead sorting hat mode'), 'sorting_hat_mode')
        self.assertEqual(intent('Voldemort mode!'), 'voldemort_mode')
        self.assertIsNone(intent('Tell me about Voldemort'))
        self.assertEqual(intent('Dobby mode'), 'dobby_mode')  # Short plain command works without the wake phrase.
        self.assertEqual(intent('Dobbie mode!'), 'dobby_mode')
        self.assertEqual(intent('Trogdor mode'), 'trogdor_mode')
        self.assertEqual(intent('sorting hat mode please'), 'sorting_hat_mode')
        self.assertIsNone(intent('I really really like your dobby mode a lot'))
        self.assertIsNone(intent('What is Trogdor mode?'))
        self.assertEqual(intent('Hey pumpkinhead sleep in Trogdor mode'), 'sleep')

    def test_mode_persists_but_invalid_saved_mode_is_normal(self):
        from controls import Controls
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            path = Path(directory) / 'controls.json'
            with patch('controls.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'Playback [50%]')):
                control = Controls(path)
                control.set_mode('trogdor')
                self.assertEqual(Controls(path).mode, 'trogdor')
                control.set_sleep(True)
                self.assertEqual(json.loads(path.read_text())['mode'], 'trogdor')
                with self.assertRaises(ValueError):
                    control.set_mode('unknown')
                path.write_text(json.dumps({'volume':50,'mode':'unknown'}))
                self.assertEqual(Controls(path).mode, 'normal')

    def test_special_voice_never_enters_normal_rotation(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.controls = SimpleNamespace(mode='normal')
        for _ in range(40):
            self.assertIn(p.choose_character('voldemort'), ('patch','trogdor','sorting_hat'))
        p.controls.mode = 'trogdor'
        self.assertEqual(p.choose_character('boo'), 'trogdor')
        for mode in ('sorting_hat','dobby','voldemort'):
            p.controls.mode = mode
            self.assertEqual(p.choose_character('boo'), mode)
        p.controls.mode = 'normal'
        self.assertEqual(p.choose_character('patch'), 'patch')
        self.assertNotIn(p.choose_character('boo'), ('boo', 'nibbles', 'dobby'))  # Not hosts any more.

    def test_mode_control_announces_new_voice_and_keeps_volume(self):
        from controls import Controls
        from pumpkin import Pumpkin
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            with patch('controls.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'Playback [50%]')):
                p = object.__new__(Pumpkin)
                p.controls = Controls(Path(directory)/'controls.json')
                p.set_status = MagicMock()
                heard = []
                p.speech = SimpleNamespace(say=lambda character,text,**kwargs:heard.append(character))
                p.control('trogdor_mode', 'patch')
                self.assertEqual(p.controls.mode, 'trogdor')
                self.assertEqual(heard, ['trogdor'])
                p.control('normal_mode', 'trogdor')
                self.assertEqual(p.controls.mode, 'normal')
                self.assertIn(heard[-1], ('patch','trogdor','sorting_hat'))
                self.assertEqual(p.controls.volume, 50)

    def test_special_mode_answers_trivia_after_three_turns(self):
        from core import Encounter
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.busy = threading.Lock()
        p.stop = threading.Event()
        p.controls = SimpleNamespace(mode='trogdor', sleeping=False)
        p.status = {'character': 'trogdor'}
        p.encounter = Encounter(active=True, generation=1)
        p.set_status = MagicMock()
        p.speech = SimpleNamespace(say=MagicMock())
        p.turn = MagicMock(side_effect=lambda *args, **kwargs:
            {'transcript': 'Who drew Trogdor?'} if kwargs.get('listen_only') else {'text': 'Strong Bad.'})
        captures = [0]
        def listen(**kwargs):
            captures[0] += 1
            if captures[0] > 4:
                p.stop.set()
            return b'audio'
        with patch('pumpkin.listen', side_effect=listen):
            p.interact(generation=1, resume=True)
        self.assertEqual(p.speech.say.call_count, 4)

    def test_sorting_cycles_all_four_houses_without_immediate_repeat(self):
        from core import HOUSES
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.set_status = MagicMock()
        p.speech = SimpleNamespace(render_lines=MagicMock(return_value=Path('/fake/ceremony.wav')),play=MagicMock())
        first = [p.sort_visitor() for _ in range(4)]
        second = [p.sort_visitor() for _ in range(4)]
        self.assertEqual(set(first), set(HOUSES))
        self.assertEqual(set(second), set(HOUSES))
        self.assertNotEqual(first[-1], second[0])
        self.assertEqual(p.speech.play.call_count, 8)
        p.speech.play.reset_mock()
        self.assertIsNone(p.sort_visitor(lambda: False))
        p.speech.play.assert_not_called()

    def test_sort_me_requests_a_sorting_ceremony(self):
        from games import intent
        self.assertEqual(intent('Hey pumpkinhead sort me'), 'sort')
        self.assertEqual(intent('Sort me!'), 'sort')
        self.assertEqual(intent('Hey pumpkinhead sorting hat mode'), 'sorting_hat_mode')

    def test_routines_can_be_requested_and_fixed_modes_keep_their_cast(self):
        from games import intent, choose_game, GAMES
        self.assertEqual(intent('Hey pumpkinhead do a routine'), 'routine')
        for _ in range(20):
            self.assertFalse(GAMES[choose_game(allow_cast=False)].get('cast'))
            self.assertFalse(GAMES[choose_game()].get('manual_only'))

    def test_sorting_conversation_remembers_its_house_without_mutating_history(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.status = {'house': 'Ravenclaw'}
        p.backend = 'http://test.invalid'
        p.token = 'test-only'
        response = MagicMock()
        response.json.return_value = {'text': 'Ravenclaw!'}
        history = []
        with patch('pumpkin.requests.post', return_value=response) as post:
            p.turn('sorting_hat', history, text='Which house did I get?')
        self.assertIn('Ravenclaw', post.call_args.kwargs['json']['history'][-1]['text'])
        self.assertEqual(history, [])
