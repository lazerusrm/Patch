from types import SimpleNamespace
import random
import threading
import time
import unittest
from unittest.mock import patch

import wled_strip
from wled_strip import WledStrip, packets, strip_frame

COLORS = {'patch': (255, 80, 0), 'boo': (80, 130, 255), 'trogdor': (255, 35, 0)}
HOUSES = {'Gryffindor': (255, 10, 0), 'Ravenclaw': (20, 60, 255), 'Hufflepuff': (255, 190, 0),
          'Slytherin': (0, 255, 60)}


def lights(**values):
    return SimpleNamespace(**{'sleeping': False, 'level': None, 'character': 'patch', 'accents': [], **values})


class StripFrameTests(unittest.TestCase):
    def test_idle_and_sleep_leave_the_strip_to_wled(self):
        self.assertIsNone(strip_frame(lights(), 10, 290, COLORS, HOUSES))
        self.assertIsNone(strip_frame(lights(sleeping=True, level=.8), 10, 290, COLORS, HOUSES))
        self.assertIsNone(strip_frame(lights(sleeping=True, accents=[(0, 20, 'solid', (1, 2, 3))]), 10, 290, COLORS, HOUSES))

    def test_speech_lights_every_led_in_the_character_colour_and_swells(self):
        quiet = strip_frame(lights(character='boo', level=0), 10, 100, COLORS, HOUSES)
        loud = strip_frame(lights(character='boo', level=1), 10, 100, COLORS, HOUSES)
        self.assertEqual(len(quiet), 100)
        self.assertEqual(len(set(quiet)), 1)
        self.assertEqual(loud, [COLORS['boo']] * 100)
        self.assertTrue(all(0 < q < l for q, l in zip(quiet[0], loud[0]) if l))
        half = strip_frame(lights(character='boo', level=.5), 10, 1, COLORS, HOUSES)[0]
        self.assertLess(quiet[0][2], COLORS['boo'][2] * .1)  # Near dark between syllables.
        self.assertLess(half[2], COLORS['boo'][2] * .4)      # Strong contrast through the middle.

    def test_unknown_character_uses_patch(self):
        frame = strip_frame(lights(character='mystery', level=1), 10, 10, COLORS, HOUSES)
        self.assertEqual(frame[5], COLORS['patch'])

    def test_newest_scene_cue_wins_over_speech(self):
        state = lights(level=.5, accents=[(0, 20, 'solid', (9, 9, 9)), (5, 20, 'off', None)])
        self.assertEqual(strip_frame(state, 10, 4, COLORS, HOUSES), [(0, 0, 0)] * 4)
        self.assertEqual(strip_frame(state, 3, 4, COLORS, HOUSES), [(9, 9, 9)] * 4)
        self.assertEqual(strip_frame(state, 25, 4, COLORS, HOUSES)[2], (84, 26, 0))  # Cue over: speech at half.

    def test_cue_modes(self):
        rng = random.Random(1)
        flicker = strip_frame(lights(accents=[(0, 9, 'flicker', (200, 100, 0))]), 1, 50, COLORS, HOUSES, rng)
        self.assertGreater(len(set(flicker)), 1)
        self.assertTrue(all(200 * .55 * .85 - 1 <= r <= 200 for r, _, _ in flicker))
        on = strip_frame(lights(accents=[(0, 9, 'strobe', (255, 255, 255))]), 1.0, 3, COLORS, HOUSES)
        off = strip_frame(lights(accents=[(0, 9, 'strobe', (255, 255, 255))]), 1.13, 3, COLORS, HOUSES)
        self.assertNotEqual(on, off)
        houses = strip_frame(lights(accents=[(0, 9, 'cycle', None)]), 1, 8, COLORS, HOUSES)
        self.assertEqual(set(houses), set(HOUSES.values()))


class WorkLightTests(unittest.TestCase):
    def test_work_light_is_white_over_speech_and_cues_but_not_asleep(self):
        state = lights(level=.5, work_until=12, accents=[(0, 20, 'cycle', None)])
        self.assertEqual(strip_frame(state, 10, 5, COLORS, HOUSES), [(255, 255, 255)] * 5)
        self.assertNotEqual(strip_frame(state, 13, 5, COLORS, HOUSES)[0], (255, 255, 255))
        state.sleeping = True
        self.assertIsNone(strip_frame(state, 10, 5, COLORS, HOUSES))

    def porch(self, night, enabled=True, sleeping=False):
        from pumpkin import Pumpkin
        p = Pumpkin.__new__(Pumpkin)
        seen = []
        p.speech = SimpleNamespace(lights=SimpleNamespace(wled=SimpleNamespace(enabled=enabled),
                                                          work_light=seen.append))
        p.controls = SimpleNamespace(sleeping=sleeping)
        p.webcam_night = night
        return p, seen

    def test_porch_light_only_after_dark_by_default(self):
        with patch.dict('os.environ', {}, clear=False):
            import os
            os.environ.pop('WLED_WORK_LIGHT', None)
            p, seen = self.porch(night=False)
            self.assertFalse(p.porch_light(5))
            p, seen = self.porch(night=True)
            self.assertTrue(p.porch_light(5))
            self.assertEqual(seen, [5])
            for kwargs in ({'enabled': False}, {'sleeping': True}):
                p, seen = self.porch(night=True, **kwargs)
                self.assertFalse(p.porch_light(5))
        with patch.dict('os.environ', {'WLED_WORK_LIGHT': 'always'}):
            self.assertTrue(self.porch(night=False)[0].porch_light(5))
        with patch.dict('os.environ', {'WLED_WORK_LIGHT': 'off'}):
            self.assertFalse(self.porch(night=True)[0].porch_light(5))

    def test_lights_work_light_sets_and_clears(self):
        from pumpkin import Lights
        state = Lights.__new__(Lights)
        state.work_light(4)
        self.assertGreater(state.work_until, time.monotonic() + 3)
        state.work_light(0)
        self.assertLessEqual(state.work_until, time.monotonic())


class PacketTests(unittest.TestCase):
    def test_dnrgb_chunks_cover_every_led(self):
        frame = [(i % 256, 1, 2) for i in range(600)]
        sent = list(packets(frame))
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0][:4], bytes((4, 2, 0, 0)))
        self.assertEqual(len(sent[0]), 4 + 489 * 3)
        self.assertEqual(sent[1][:4], bytes((4, 2, 489 >> 8, 489 & 255)))
        self.assertEqual(len(sent[1]), 4 + 111 * 3)
        self.assertEqual(sent[1][4:7], bytes((489 % 256, 1, 2)))
        self.assertEqual(list(packets([])), [])


class FakeSocket:
    def __init__(self, *_):
        self.sent = []

    def sendto(self, data, address):
        self.sent.append((data, address))

    def close(self):
        pass


class StripRunTests(unittest.TestCase):
    def run_strip(self, state, seconds=.25, fail=False):
        calls = []

        def request(path, body=None):
            calls.append((path, body))
            if fail:
                raise OSError('no route')
            if path == '/json/info':
                return {'leds': {'count': 6}, 'name': 'test'}
            if path == '/json/state' and body is None:
                return {'on': True, 'bri': 77, 'seg': [{'id': 0, 'fx': 0, 'col': [[1, 2, 3]], 'n': 'x'}]}
            return {}

        sock = FakeSocket()
        strip = WledStrip(state, COLORS, HOUSES, host='10.0.0.9', delay=0)
        with patch.object(strip, 'request', side_effect=request), \
             patch.object(wled_strip.socket, 'socket', return_value=sock):
            strip.start()
            time.sleep(seconds)
            strip.close()
        return strip, calls, sock

    def test_disabled_without_host(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(WledStrip(lights(), COLORS, HOUSES).enabled)

    def test_idle_sets_the_fire_once_and_restores_on_close(self):
        strip, calls, sock = self.run_strip(lights())
        posts = [body for path, body in calls if body is not None]
        self.assertEqual(posts[0], wled_strip.IDLE_FIRE)
        self.assertEqual(posts[-1], {'on': True, 'bri': 77, 'seg': [{'id': 0, 'fx': 0, 'col': [[1, 2, 3]]}], 'live': False})
        self.assertEqual(len(posts), 2)
        self.assertEqual(sock.sent, [])

    def test_speech_streams_frames_to_the_realtime_port(self):
        _, _, sock = self.run_strip(lights(level=.7, character='boo'))
        self.assertGreater(len(sock.sent), 2)
        data, address = sock.sent[0]
        self.assertEqual(address, ('10.0.0.9', 21324))
        self.assertEqual(len(data), 4 + 6 * 3)

    def test_sleep_turns_the_strip_off(self):
        _, calls, sock = self.run_strip(lights(sleeping=True))
        self.assertIn(('/json/state', {'on': False}), calls)
        self.assertEqual(sock.sent, [])

    def test_unreachable_strip_backs_off_without_raising(self):
        strip, calls, _ = self.run_strip(lights(level=1), seconds=.3, fail=True)
        self.assertEqual([path for path, _ in calls], ['/json/info'])
        self.assertIsNone(strip.saved)

    def test_reboot_while_idle_sets_the_idle_effect_again(self):
        uptimes = iter([500, 3])
        posts = []

        def request(path, body=None):
            if path == '/json/info':
                return {'leds': {'count': 6}, 'uptime': next(uptimes, 4)}
            if body is None:
                return {'on': True, 'bri': 1, 'seg': []}
            posts.append(body)
            return {}

        strip = WledStrip(lights(), COLORS, HOUSES, host='10.0.0.9', delay=0)
        with patch.object(strip, 'request', side_effect=request), \
             patch.object(wled_strip, 'CHECK_SECONDS', .05), \
             patch.object(wled_strip.socket, 'socket', return_value=FakeSocket()):
            strip.start()
            time.sleep(.3)
            strip.stop.set()
            strip.thread.join(timeout=2)
        self.assertEqual(posts.count(wled_strip.IDLE_FIRE), 2)

    def test_delay_holds_frames_back(self):
        state = lights()
        strip = WledStrip(state, COLORS, HOUSES, host='x', delay=.5)
        strip.count = 4
        self.assertIsNone(strip.delayed(10))
        state.level = 1
        self.assertIsNone(strip.delayed(10.2))
        self.assertIsNotNone(strip.delayed(10.75))

    def test_brightness_applied_with_the_idle_effect(self):
        with patch.dict('os.environ', {'WLED_BRIGHTNESS': '210'}):
            strip = WledStrip(lights(), COLORS, HOUSES, host='x', delay=0)
        self.assertEqual(strip.idle['bri'], 210)
        self.assertEqual(strip.idle['seg'], wled_strip.IDLE_FIRE['seg'])
        with patch.dict('os.environ', {'WLED_BRIGHTNESS': '0'}), self.assertRaises(ValueError):
            WledStrip(lights(), COLORS, HOUSES, host='x', delay=0)

    def test_invalid_delay_rejected(self):
        with self.assertRaises(ValueError):
            WledStrip(lights(), COLORS, HOUSES, host='x', delay=5)


if __name__ == '__main__':
    unittest.main()
