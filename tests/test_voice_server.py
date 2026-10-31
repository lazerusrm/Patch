import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

from voice_server import VoiceHandler


class VoiceServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), VoiceHandler)
        cls.server.token = 'test-token-' * 4
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_voice_endpoint_requires_token(self):
        request = urllib.request.Request(self.url + '/tts', data=b'text=Boo')
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 401)

    def test_voice_reference_cannot_be_an_arbitrary_url(self):
        request = urllib.request.Request(self.url + '/tts',
            data=urllib.parse.urlencode({'text': 'Boo', 'voice_url': 'http://private.invalid/secret'}).encode(),
            headers={'Authorization': 'Bearer ' + self.server.token})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 400)


class VoiceProfileTests(unittest.TestCase):
    def test_every_selectable_character_has_a_real_transcribed_reference(self):
        import json
        import wave
        from voice_server import ROOT
        from core import CHARACTERS
        profiles = json.loads((ROOT / 'voices.json').read_text())['characters']
        self.assertEqual(set(profiles), set(CHARACTERS))
        for name, profile in profiles.items():
            self.assertTrue(profile['text'].strip(), name)
            if 'source' in profile and not (ROOT / profile['reference']).exists():
                continue  # Fan-character clips are kept local, not published (assets/voices/README.md).
            with wave.open(str(ROOT / profile['reference'])) as audio:
                self.assertGreater(audio.getnframes() / audio.getframerate(), 2, name)
                self.assertEqual(audio.getnchannels(), 1, name)

    def test_selected_clone_engine_produces_bounded_pcm(self):
        import io
        import wave
        import numpy as np
        from unittest.mock import MagicMock
        from voice_server import VoiceEngine
        engine = object.__new__(VoiceEngine)
        engine.voices = {'trogdor': {'engine': 'qwen'}}
        engine._qwen_audio = MagicMock(return_value=(np.full(24000, .2), 24000))
        engine._breeze_audio = MagicMock()
        with wave.open(io.BytesIO(engine.render('trogdor', 'Hello.'))) as audio:
            self.assertEqual(audio.getnframes(), 24000)
            self.assertEqual(audio.getsampwidth(), 2)
        engine._breeze_audio.assert_not_called()
        engine.render('trogdor', 'Consummate Vs!')
        engine._qwen_audio.assert_called_with('trogdor', "Consummate V's!")
        engine._qwen_audio.return_value = (np.array([float('nan')]), 24000)
        with self.assertRaises(RuntimeError):
            engine.render('trogdor', 'Hello.')

    def test_large_clone_model_is_reused_without_sharing_character_prompts(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from voice_server import VoiceEngine
        engine = object.__new__(VoiceEngine)
        profile = {'qwen_size': '1.7B', 'non_streaming_mode': True, 'path': 'reference.wav', 'text': 'Reference.', 'seed': 614}
        engine.voices = {'dobby': dict(profile), 'trogdor': dict(profile)}
        engine.qwen = {}
        engine.clone_prompts = {}
        model = MagicMock()
        model.generate_voice_clone.return_value = ([['audio']], 24000)
        factory = MagicMock()
        factory.from_pretrained.return_value = model
        modules = {'torch': SimpleNamespace(bfloat16='bfloat16', manual_seed=MagicMock()),
                   'qwen_tts': SimpleNamespace(Qwen3TTSModel=factory)}
        with patch.dict(sys.modules, modules):
            engine._qwen_audio('dobby', 'Hello.')
            engine._qwen_audio('trogdor', 'Hello.')
        factory.from_pretrained.assert_called_once()
        self.assertEqual(factory.from_pretrained.call_args.args[0], 'Qwen/Qwen3-TTS-12Hz-1.7B-Base')
        self.assertEqual(model.create_voice_clone_prompt.call_count, 2)
        self.assertTrue(model.generate_voice_clone.call_args.kwargs['non_streaming_mode'])
