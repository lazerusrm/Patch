from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from audition import dispatch


class AuditionTests(unittest.TestCase):
    def test_sleep_suppresses_routines_but_keeps_wake_control(self):
        p = SimpleNamespace(status={'character': 'patch'}, controls=SimpleNamespace(sleeping=True, mode='normal'),
                            control=MagicMock(), entertain=MagicMock(), play_game=MagicMock())
        dispatch(p, 'hey pumpkinhead tell me a joke', lambda: True)
        p.entertain.assert_not_called()
        dispatch(p, 'hey pumpkinhead wake up', lambda: True)
        self.assertEqual(p.control.call_args.args, ('wake', 'patch'))
        self.assertTrue(p.control.call_args.kwargs['announce'])
