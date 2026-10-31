from pathlib import Path
import random
import unittest


class EntertainmentTests(unittest.TestCase):
    def test_library_has_variety_and_stories_are_short(self):
        from entertainment import Library, story_chunks
        library = Library(Path(__file__).resolve().parents[1] / 'entertainment.json', random.Random(4))
        for character in ('patch', 'boo', 'nibbles'):
            jokes = [library.draw('joke', character) for _ in range(8)]
            self.assertEqual(len({item['id'] for item in jokes}), 8)
            stories = [library.draw('story', character) for _ in range(3)]
            self.assertEqual(len({item['id'] for item in stories}), 3)
            for story in stories:
                self.assertLessEqual(len(story['text'].split()), 65)
                chunks = story_chunks(story['text'])
                self.assertEqual(' '.join(chunks), story['text'])
                self.assertTrue(all(len(c.split()) <= 30 for c in chunks))

    def test_every_selectable_character_has_jokes_and_stories(self):
        from core import CHARACTERS
        from entertainment import Library
        library = Library(Path(__file__).resolve().parents[1] / 'entertainment.json')
        for character in CHARACTERS:
            for kind in ('joke', 'story'):
                self.assertEqual(library.draw(kind, character)['character'], character)
