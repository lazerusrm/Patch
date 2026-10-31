import json
import threading
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from pathlib import Path
from http.server import ThreadingHTTPServer

from backend import Handler, Brain, LOCK


class BackendTests(unittest.TestCase):
    def test_compact_voice_preserves_renderer_identity(self):
        import io
        import wave
        import urllib.parse
        audio = io.BytesIO()
        with wave.open(audio, 'wb') as wav:
            wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
            import math, struct
            wav.writeframes(b''.join(struct.pack('<h', int(4000 * math.sin(i * .07))) for i in range(24000)))
        upstream = MagicMock(content=audio.getvalue(), headers={'X-Voice-Model':'qwen3-tts-1.7b'})
        request = urllib.request.Request(self.url + '/tts',
            data=urllib.parse.urlencode({'text':'Hello.', 'voice_url':'dobby'}).encode(),
            headers={'Authorization':'Bearer '+self.server.token})
        with patch('backend.requests.post', return_value=upstream):
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.headers['X-Voice-Model'], 'qwen3-tts-1.7b')
                self.assertEqual(response.headers['Content-Type'], 'audio/ogg')
                self.assertEqual(response.headers['X-Loudness'], 'matched')
                self.assertTrue(response.read().startswith(b'OggS'))

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.token = 'test-token-' * 4
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_split_lead_keeps_punchline_for_second_sentence(self):
        from backend import split_lead
        self.assertEqual(split_lead('A full-size Snickers? You hold it. I do not trust me either.'),
                         ('A full-size Snickers? You hold it.', 'I do not trust me either.'))
        # An opening too short to cover the rest's render keeps the reply whole.
        self.assertEqual(split_lead('Wow. Two hundred years haunting theaters and people still ask me for directions.')[1], '')
        self.assertEqual(split_lead('Two pieces, certainly. Accio chocolate! You will need to reach.'),
                         ('Two pieces, certainly.', 'Accio chocolate! You will need to reach.'))
        self.assertEqual(split_lead('They scooped out my insides.'), ('They scooped out my insides.', ''))
        # A tail too short for the Breeze voices stays attached.
        self.assertEqual(split_lead('Dobby is a free elf. Ha!'), ('Dobby is a free elf. Ha!', ''))

    def test_split_turn_returns_first_sentence_and_prerenders_rest(self):
        import base64, urllib.parse
        rendered = []
        def fake_render(actor, text):
            rendered.append(text)
            return b'OggS' + text.encode(), 'qwen3-tts-1.7b'
        self.server.brain = SimpleNamespace(respond=lambda data: {
            'text': 'Yes! Dobby is a free elf, sir. Getting out is proving trickier.'})
        with patch.object(Handler, 'render_compact', side_effect=lambda self, a, t: fake_render(a, t), autospec=True):
            request = urllib.request.Request(self.url + '/turn',
                data=json.dumps({'character': 'dobby', 'text': 'Are you real?', 'speak': True, 'split': True}).encode(),
                headers={'Authorization': 'Bearer ' + self.server.token})
            with urllib.request.urlopen(request) as response:
                body = json.load(response)
            self.assertEqual(body['voice_text'], 'Yes! Dobby is a free elf, sir.')
            self.assertEqual(body['rest'], 'Getting out is proving trickier.')
            self.assertEqual(base64.b64decode(body['voice']), b'OggSYes! Dobby is a free elf, sir.')
            tts = urllib.request.Request(self.url + '/tts',
                data=urllib.parse.urlencode({'text': body['rest'], 'voice_url': 'dobby'}).encode(),
                headers={'Authorization': 'Bearer ' + self.server.token})
            with urllib.request.urlopen(tts) as response:
                self.assertEqual(response.read(), b'OggS' + body['rest'].encode())
        # The rest was rendered once, in the background, not again for the /tts request.
        self.assertEqual(rendered, ['Yes! Dobby is a free elf, sir.', 'Getting out is proving trickier.'])

    def test_unsplit_turn_keeps_whole_reply_voice(self):
        self.server.brain = SimpleNamespace(respond=lambda data: {'text': 'One. Two three four five.'})
        with patch.object(Handler, 'render_compact', return_value=(b'OggS', 'qwen3-tts-1.7b')) as render:
            request = urllib.request.Request(self.url + '/turn',
                data=json.dumps({'character': 'dobby', 'text': 'hi', 'speak': True}).encode(),
                headers={'Authorization': 'Bearer ' + self.server.token})
            with urllib.request.urlopen(request) as response:
                body = json.load(response)
        self.assertNotIn('rest', body)
        render.assert_called_once_with('dobby', 'One. Two three four five.')

    def fake_codex(self, directory, delays, fail=()):
        import os, stat
        script = Path(directory) / 'codex'
        script.write_text('#!/usr/bin/env python3\n'
            'import sys, time\n'
            'args = sys.argv; model = args[args.index("-m") + 1]; out = args[args.index("-o") + 1]\n'
            'sys.stdin.read()\n'
            f'delays = {delays!r}; fail = {list(fail)!r}\n'
            'time.sleep(delays[model])\n'
            'if model in fail: sys.exit(1)\n'
            'open(out, "w").write("Reply from " + model + ".")\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return str(script)

    def hedged_reply(self, delays, fail=(), hedge_seconds='0.3'):
        import os, tempfile
        brain = object.__new__(Brain)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'CODEX_BIN': self.fake_codex(directory, delays, fail), 'PUMPKIN_MODEL': 'sol',
                'PUMPKIN_HEDGE_MODEL': 'luna', 'PUMPKIN_HEDGE_SECONDS': hedge_seconds,
                'PUMPKIN_RUNTIME': directory}):
            (Path(directory) / 'codex-home').mkdir()
            with patch('backend.RUNTIME', Path(directory)):
                return brain.respond({'character': 'patch', 'text': 'hi', 'history': []})

    def test_fast_primary_reply_needs_no_hedge(self):
        self.assertEqual(self.hedged_reply({'sol': 0, 'luna': 0})['model'], 'sol')

    def test_slow_primary_is_raced_by_hedge_model(self):
        reply = self.hedged_reply({'sol': 5, 'luna': 0})
        self.assertEqual((reply['model'], reply['text']), ('luna', 'Reply from luna.'))

    def test_failed_primary_falls_back_to_hedge_immediately(self):
        import time
        started = time.monotonic()
        reply = self.hedged_reply({'sol': 0, 'luna': 0}, fail=('sol',), hedge_seconds='5')
        self.assertEqual(reply['model'], 'luna')
        self.assertLess(time.monotonic() - started, 4)

    def test_auth_is_required_before_processing_media(self):
        request = urllib.request.Request(self.url + '/turn', data=b'not json')
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 401)

    def test_authenticated_invalid_media_is_rejected(self):
        request = urllib.request.Request(self.url + '/turn',
            data=json.dumps({'character': 'patch', 'image': 'not base64!'}).encode(),
            headers={'Authorization': 'Bearer ' + self.server.token})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 400)

    def test_authenticated_health(self):
        request = urllib.request.Request(self.url + '/health',
            headers={'Authorization': 'Bearer ' + self.server.token})
        with urllib.request.urlopen(request) as response:
            self.assertTrue(json.load(response)['ready'])

    def test_asr_can_run_while_vision_is_busy(self):
        self.server.brain = SimpleNamespace(respond=lambda data: {'text': '', 'transcript': 'Boo!'})
        LOCK.acquire()
        try:
            request = urllib.request.Request(self.url + '/turn',
                data=json.dumps({'character': 'patch', 'listen_only': True}).encode(),
                headers={'Authorization': 'Bearer ' + self.server.token})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(json.load(response)['transcript'], 'Boo!')
        finally:
            LOCK.release()

    def test_low_confidence_segments_cannot_trigger_commands(self):
        brain = object.__new__(Brain)
        brain.whisper = MagicMock()
        brain.whisper.transcribe.return_value = (iter([
            SimpleNamespace(text='turn it up', no_speech_prob=.9, avg_logprob=-.3),
            SimpleNamespace(text='sleep', no_speech_prob=.1, avg_logprob=-1.5),
            SimpleNamespace(text='Boo!', no_speech_prob=.1, avg_logprob=-.3),
        ]), None)
        with patch('backend.validate_audio'):
            self.assertEqual(brain.transcribe(b'audio'), 'Boo!')


if __name__ == '__main__':
    unittest.main()
