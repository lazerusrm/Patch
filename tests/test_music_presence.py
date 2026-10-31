import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class MusicPresenceTests(unittest.TestCase):
    def test_distant_possible_person_stops_music_before_greeting(self):
        from core import person_presence
        self.assertEqual(person_presence([[0, 0, .1, .1, .35]]), (0, True))
        self.assertEqual(person_presence([[0, 0, .3, .3, .8]]), (1, True))
        self.assertEqual(person_presence([[0, 0, .1, .1, .1]]), (0, False))

    def test_idle_music_requires_live_camera_absence_and_awake_state(self):
        from pumpkin import Pumpkin
        p=object.__new__(Pumpkin)
        p.music=SimpleNamespace(tracks=['song.wav'])
        p.stop=threading.Event()
        p.controls=SimpleNamespace(sleeping=False)
        p.encounter=SimpleNamespace(active=False)
        p.frame=object()
        p.frame_time=100
        p.status={'possible_person':False}
        p.last_seen=80
        with patch('pumpkin.time.monotonic',return_value=100):
            self.assertTrue(p.idle_music_allowed())
            p.frame_time=98
            self.assertFalse(p.idle_music_allowed())
            p.frame_time=100
            p.status['possible_person']=True
            self.assertFalse(p.idle_music_allowed())
            p.status['possible_person']=False
            p.last_seen=99
            self.assertFalse(p.idle_music_allowed())
            p.last_seen=80
            p.controls.sleeping=True
            self.assertFalse(p.idle_music_allowed())
            p.controls.sleeping=False
            p.frame=None
            self.assertFalse(p.idle_music_allowed())
            p.frame=object()
            p.encounter.active=True
            self.assertFalse(p.idle_music_allowed())
