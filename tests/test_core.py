import unittest
import io
import wave


class CoreTests(unittest.TestCase):
    def test_fast_arrival_preserves_debounce_for_uncertain_people(self):
        from core import Encounter, strong_person
        e = Encounter(arrival_delay=.15)
        self.assertFalse(e.observe(True, 0))
        self.assertFalse(e.observe(False, .1))
        self.assertFalse(e.observe(True, .2))
        self.assertTrue(e.observe(True, .36))
        self.assertEqual(e.claim(), 1)
        self.assertIsNone(e.claim())
        close = [[.2,.3,.9,.7,.95]]
        self.assertTrue(strong_person(close))
        self.assertFalse(strong_person([[.2,.3,.9,.7,.6]]))
        self.assertFalse(strong_person([[.2,.3,.3,.4,.95]]))
        e = Encounter(arrival_delay=.15)
        self.assertTrue(e.observe(True, 0, immediate=strong_person(close)))
        self.assertFalse(e.observe(True, .01, immediate=True))

    def test_presence_requires_stability_and_absence_before_regreeting(self):
        from core import Encounter
        e = Encounter()
        self.assertFalse(e.observe(True, 0))
        self.assertTrue(e.observe(True, 1.1))
        self.assertFalse(e.observe(True, 90))
        self.assertFalse(e.observe(False, 91))
        self.assertFalse(e.observe(True, 92))
        self.assertFalse(e.observe(False, 93))
        self.assertFalse(e.observe(False, 102))
        self.assertFalse(e.observe(True, 103))
        self.assertTrue(e.observe(True, 104.1))

    def test_false_detection_does_not_accumulate(self):
        from core import Encounter
        e = Encounter()
        self.assertFalse(e.observe(True, 0))
        self.assertFalse(e.observe(False, .5))
        self.assertFalse(e.observe(True, 2))
        self.assertFalse(e.observe(True, 2.5))

    def test_departure_invalidates_old_conversation_generation(self):
        from core import Encounter
        e = Encounter()
        e.observe(True, 0)
        e.observe(True, 1)
        first = e.generation
        e.observe(False, 2)
        e.observe(False, 11)
        self.assertFalse(e.active)
        self.assertNotEqual(e.generation, first)
        departed = e.generation
        e.observe(False, 12)
        self.assertEqual(e.generation, departed)
        e.observe(True, 13)
        self.assertTrue(e.observe(True, 14))
        self.assertNotEqual(e.generation, departed)

    def test_new_arrival_remains_pending_until_worker_is_available(self):
        from core import Encounter
        e = Encounter()
        e.observe(True, 0)
        e.observe(True, 1)
        self.assertEqual(e.claim(), e.generation)
        self.assertIsNone(e.claim())
        e.observe(False, 2)
        e.observe(False, 11)
        e.observe(True, 12)
        e.observe(True, 13)
        # A busy worker delays claiming; later frames must retain this arrival.
        e.observe(True, 20)
        self.assertEqual(e.claim(), e.generation)
        self.assertIsNone(e.claim())

    def test_input_validation_rejects_unknown_characters_and_large_media(self):
        from core import validate_request
        for data in ({'character': 'root'}, {'character': 'patch', 'audio': 'a' * 900000},
                     {'character': 'patch', 'history': 'bad'}, {'character': 'patch', 'image': '!bad!'}):
            with self.assertRaises(ValueError):
                validate_request(data)
        self.assertEqual(validate_request({'character': 'patch'})['history'], [])

    def test_speech_is_short_and_has_no_markup(self):
        from core import clean_reply
        self.assertEqual(clean_reply('**Boo!**\nHello, friend.'), 'Boo! Hello, friend.')
        self.assertLessEqual(len(clean_reply('word ' * 500).split()), 45)

    def test_envelope_tracks_speech_and_clamps(self):
        from core import brightness
        self.assertEqual(brightness([0] * 100), .08)
        self.assertGreater(brightness([4000, -4000] * 50), .2)
        self.assertLessEqual(brightness([32767] * 100), 1)

    def test_led_encoding_is_grb_and_has_reset(self):
        from core import encode_leds
        off = encode_leds((0, 0, 0), 2)
        green = encode_leds((0, 255, 0), 2)
        self.assertEqual(len(off), len(green))
        self.assertEqual(green[:240], bytes(240))
        self.assertEqual(green[-240:], bytes(240))
        self.assertEqual(green[240:243], bytes([219, 109, 182]))
        self.assertEqual(off[240:243], bytes([146, 73, 36]))

    def test_audio_boundary_accepts_pcm_and_rejects_excess_duration(self):
        from core import validate_audio
        def wav_bytes(seconds):
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(bytes(32000 * seconds))
            return buffer.getvalue()
        validate_audio(wav_bytes(1))
        for invalid in (b'not audio', wav_bytes(13)):
            with self.assertRaises(ValueError):
                validate_audio(invalid)

    def test_idle_flame_breathes_warmly_within_hardware_brightness_cap(self):
        from core import flame_rgb
        colors = [flame_rgb(i / 10) for i in range(200)]
        self.assertGreater(len(set(colors)), 8)
        self.assertGreater(max(c[0] for c in colors) - min(c[0] for c in colors), 15)
        for red, green, blue in colors:
            self.assertTrue(0 < green < red <= 38)
            self.assertEqual(blue, 0)


if __name__ == '__main__':
    unittest.main()
