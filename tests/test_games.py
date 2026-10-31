import random
import unittest


class GameTests(unittest.TestCase):
    def test_keywords_accept_spoken_spacing_and_punctuation(self):
        from games import intent
        for text in ('Trick or treat!', 'trick-or-treat', 'Please, trick or treat.'):
            self.assertEqual(intent(text), 'game')
        for text in ('Hey, Pumpkinhead!', 'hey pumpkin head'):
            self.assertEqual(intent(text), 'wake')
        self.assertIsNone(intent('I like pumpkins'))
        self.assertIsNone(intent('The candy is a treat'))

    def test_controls_require_the_wake_phrase(self):
        from games import intent
        self.assertEqual(intent('Hey pumpkinhead sleep'), 'sleep')
        self.assertEqual(intent('Hey pumpkinhead wake up'), 'wake')
        self.assertEqual(intent("Hey pumpkinhead I can't hear you"), 'volume_up')
        self.assertEqual(intent('Hey pumpkinhead I cant hear you'), 'volume_up')
        self.assertEqual(intent('Hey pumpkinhead be quiet'), 'volume_down')
        self.assertIsNone(intent('I cannot hear you, be quiet'))
        self.assertIsNone(intent('time to sleep'))
        self.assertEqual(intent('Hey pumpkinhead tell me a joke'), 'joke')
        self.assertEqual(intent('Hey pumpkinhead tell me a story'), 'story')
        self.assertEqual(intent('Hey pumpkinhead sleep, trick or treat later'), 'sleep')

    def test_pumpkin_transformation_has_a_specific_trigger(self):
        from games import intent
        self.assertEqual(intent('Hey pumpkinhead pumpkin spell'), 'pumpkin_scene')
        self.assertEqual(intent('Hey pumpkinhead Dobby and Voldemort'), 'pumpkin_scene')

    def test_boo_is_a_standalone_cheeky_trigger(self):
        from games import intent
        for text in ('Boo!', 'BOO', 'Hey pumpkinhead boo!'):
            self.assertEqual(intent(text), 'boo')
        self.assertIsNone(intent('Tell me about Boo the ghost'))
        self.assertEqual(intent('Trick or treat!'), 'game')

    def test_random_game_has_variety_and_avoids_immediate_repeat(self):
        from games import choose_game, GAMES
        rng = random.Random(7)
        previous = None
        seen = set()
        for _ in range(40):
            key = choose_game(previous, rng)
            self.assertIn(key, GAMES)
            self.assertNotEqual(key, previous)
            seen.add(GAMES[key]['kind'])
            previous = key
        self.assertEqual(seen, {scene['kind'] for scene in GAMES.values() if not scene.get('manual_only')})


class TrogdorIntentTests(unittest.TestCase):
    def test_saying_the_name_summons_a_scene_but_mode_command_still_wins(self):
        from games import intent
        for heard in ('Trogdor!', 'I love Trogdor', 'I am dressed as Strong Bad', 'burninate the porch',
                      'trog door', 'hey pumpkinhead trogdor'):
            self.assertEqual(intent(heard), 'trogdor_scene', heard)
        for heard in ('Who drew Trogdor?', 'do you know Strong Bad', 'Trogdor has how many arms?'):
            self.assertIsNone(intent(heard), heard)  # Trivia goes to Strong Bad's real answer.
        self.assertEqual(intent('hey pumpkinhead trogdor mode'), 'trogdor_mode')
        self.assertEqual(intent('hey pumpkinhead trog door mode'), 'trogdor_mode')
        self.assertIsNone(intent('frog door'))


class BenchTests(unittest.TestCase):
    def test_benched_goblin_never_hosts_but_keeps_his_routines(self):
        from core import AUTO_CHARACTERS
        from games import benched, intent, SONGS
        self.assertEqual(AUTO_CHARACTERS, ('patch', 'trogdor', 'sorting_hat'))
        self.assertFalse(benched('jingle_pumpkin'))
        self.assertEqual(SONGS, ())  # Custom jingles retired (owner, 2026-10-31).
        self.assertEqual(intent('Sing me a song!'), 'song')
        self.assertEqual(intent('can you sing a song'), 'song')
