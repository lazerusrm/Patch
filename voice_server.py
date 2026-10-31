"""Authenticated local speech with per-character reference cloning."""
import io
import json
import logging
import os
import re
from pathlib import Path
import threading
import time
import wave
import sys
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs

from backend import Handler
from core import CHARACTERS, clean_reply

ROOT = Path(__file__).resolve().parent
VOICE_LOCK = threading.Lock()
# Live porch lines queue briefly instead of failing; background pre-rendering yields to them.
WAITING_LIVE = [0]
WAITING_LOCK = threading.Lock()


def acquire_voice(priority, timeout=8.0):
    deadline = time.monotonic() + timeout
    if priority != 'low':
        with WAITING_LOCK:
            WAITING_LIVE[0] += 1
        try:
            return VOICE_LOCK.acquire(timeout=timeout)
        finally:
            with WAITING_LOCK:
                WAITING_LIVE[0] -= 1
    while time.monotonic() < deadline:
        if not WAITING_LIVE[0] and VOICE_LOCK.acquire(timeout=.05):
            if not WAITING_LIVE[0]:
                return True
            VOICE_LOCK.release()  # A live line arrived meanwhile: let it go first.
        time.sleep(.02)
    return False


class VoiceEngine:
    def __init__(self):
        profiles = json.loads((ROOT / 'voices.json').read_text())['characters']
        self.voices = {}
        for name in CHARACTERS:
            metadata = profiles[name]
            path = ROOT / metadata['reference']
            if not path.is_file() or not metadata['text'].strip():
                raise ValueError('Missing voice reference: ' + name)
            self.voices[name] = {**metadata, 'path': str(path)}
        self.qwen = {}
        self.clone_prompts = {}
        import torch
        sys.path.insert(0, str(ROOT / 'runtime/breeze-source'))
        from breeze_infer.runtime import load_runtime, resolve_device, update_generation_config_for_breeze
        from models.fast_streaming import FastBreezeStreamingRuntime, FastStreamingConfig
        torch.set_num_threads(4)
        self.tokenizer, self.model, self.audio_tokenizer = load_runtime(
            ROOT / 'runtime/breeze-model', device=resolve_device(), attn_implementation='eager')
        update_generation_config_for_breeze(self.model)
        self.runtime = FastBreezeStreamingRuntime(
            self.model, self.audio_tokenizer,
            FastStreamingConfig(max_new_tokens=500, max_seq_len=2048,
                                fast_backbone_decode=True, fast_depth_decoder=True,
                                fast_codec=True, repetition_penalty=1.1), tokenizer=self.tokenizer)

    def _breeze_audio(self, character, text):
        import numpy as np
        from breeze_infer.runtime import set_all_seeds
        from breeze_infer.templates import get_template, prepare_inputs, select_template_name
        voice = self.voices[character]
        request = {'id': 'pumpkin-' + character, 'text': text, 'speaker': 'S0',
                   'instruction': voice['instruct'], 'ref_audio_path': voice['path'],
                   'ref_text': voice['text']}
        set_all_seeds(voice['seed'])
        inputs = prepare_inputs(self.tokenizer, self.audio_tokenizer, self.model, [request],
                                get_template(select_template_name(request)), guidance_scale=voice.get('cfg', 4),
                                guidance_scale_ref=None, guidance_scale_ins=None)
        chunks = []
        frames = 0
        rate = self.runtime.sample_rate
        for chunk in self.runtime.iter_audio_chunks(inputs, request_id=request['id'], seed=voice['seed']):
            audio = np.asarray(chunk.audio, dtype=np.float32)
            chunks.append(audio)
            frames += len(audio)
            if frames > rate * 30:
                raise RuntimeError('Generated speech exceeded duration limit')
        audio = np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)
        return audio, rate

    def _qwen_audio(self, character, text):
        import torch
        from qwen_tts import Qwen3TTSModel
        voice = self.voices[character]
        size = voice.get('qwen_size', '0.6B')
        revision = {'0.6B': '5d83992436eae1d760afd27aff78a71d676296fc',
                    '1.7B': 'fd4b254389122332181a7c3db7f27e918eec64e3'}[size]
        name = 'Qwen/Qwen3-TTS-12Hz-' + size + '-Base'
        if name not in self.qwen:
            self.qwen[name] = Qwen3TTSModel.from_pretrained(
                name, revision=revision, device_map='cuda:0',
                dtype=torch.bfloat16, attn_implementation='sdpa')
        model = self.qwen[name]
        key = (name, character)
        if key not in self.clone_prompts:
            self.clone_prompts[key] = model.create_voice_clone_prompt(
                ref_audio=voice['path'], ref_text=voice['text'],
                x_vector_only_mode=voice.get('x_vector_only_mode', False))
        torch.manual_seed(voice['seed'])
        waves, rate = model.generate_voice_clone(
            text=text, language='English', voice_clone_prompt=self.clone_prompts[key],
            non_streaming_mode=voice.get('non_streaming_mode', False), max_new_tokens=800)
        return waves[0], rate

    @staticmethod
    def _pitch(audio, rate):
        """Median and 95th-percentile f0 of the voiced frames (fast YIN, not pYIN)."""
        import numpy as np, librosa
        y = librosa.resample(np.asarray(audio, dtype=np.float32), orig_sr=rate, target_sr=16000)
        f0 = librosa.yin(y, fmin=80, fmax=1000, sr=16000, frame_length=1024, hop_length=320)
        level = librosa.feature.rms(y=y, frame_length=1024, hop_length=320)[0][:len(f0)]
        f0 = f0[level > max(.02, float(np.percentile(level, 60)) * .5)]
        if len(f0) < 5:
            return None, None
        return float(np.median(f0)), float(np.percentile(f0, 95))

    def _steady_take(self, character, spoken, audio, rate):
        """Re-take a squeaky render with other seeds; keep the steadiest take within budget."""
        import time as _time
        voice = self.voices[character]
        low, high = voice['pitch_range']
        def badness(take):
            med, p95 = self._pitch(*take)
            if med is None:
                return 0
            return max(0, low - med) / low + max(0, med - high) / high + max(0, p95 / med - 1.5)
        best, best_score = (audio, rate), badness((audio, rate))
        started = _time.monotonic()
        seed = voice['seed']
        for retry in voice.get('retry_seeds', ()):
            if best_score == 0 or _time.monotonic() - started > voice.get('retry_budget', 4):
                break
            try:
                voice['seed'] = retry
                take = self._breeze_audio(character, spoken) if voice.get('engine') != 'qwen' else self._qwen_audio(character, spoken)
            finally:
                voice['seed'] = seed
            score = badness(take)
            if score < best_score:
                best, best_score = take, score
        return best

    def render(self, character, text):
        import numpy as np
        generate = self._qwen_audio if self.voices[character].get('engine') == 'qwen' else self._breeze_audio
        spoken = re.sub(r'\bAccio\b', 'Ack-ee-oh', text, flags=re.IGNORECASE)
        if character == 'trogdor':
            spoken = re.sub(r"\b(consummate)\s+v(?:['’]s|s)\b", r"\1 V's", spoken, flags=re.IGNORECASE)
        voice = self.voices[character]
        if voice.get('soften_exclaim'):
            spoken = spoken.replace('!', '.')  # Every "!" pushes this clone's pitch up.
        audio, rate = generate(character, spoken)
        if voice.get('pitch_range'):
            audio, rate = self._steady_take(character, spoken, audio, rate)
        audio = np.asarray(audio, dtype=np.float32)
        if not 0 < len(audio) <= rate * 30 or not np.isfinite(audio).all():
            raise RuntimeError('Invalid generated audio')
        peak = float(np.max(np.abs(audio)))
        if peak <= .001:
            raise RuntimeError('Silent generated audio')
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes((audio / peak * .7 * 32767).astype('<i2').tobytes())
        return buffer.getvalue()


class VoiceHandler(Handler):
    def do_GET(self):
        if not self.authorized():
            return self.send_json(401, {'error': 'Unauthorized'})
        self.send_json(200 if self.path == '/health' else 404,
                       {'ready': self.path == '/health', 'model': 'reference-clones'})

    def do_POST(self):
        if not self.authorized():
            return self.send_json(401, {'error': 'Unauthorized'})
        if self.path != '/tts':
            return self.send_json(404, {'error': 'Not found'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                return self.send_json(413, {'error': 'Request too large'})
            self.connection.settimeout(10)
            fields = parse_qs(self.rfile.read(length).decode())
            requested = fields.get('voice_url', [''])[0]
            character = next((key for key, value in CHARACTERS.items()
                              if requested in (key, value['voice'])), None)
            text = clean_reply(fields.get('text', [''])[0])
            if character is None or not text:
                raise ValueError('Invalid voice or text')
        except (ValueError, OSError):
            return self.send_json(400, {'error': 'Invalid speech request'})
        if not acquire_voice(fields.get('priority', [''])[0] or self.headers.get('X-Priority', '')):
            return self.send_json(429, {'error': 'Busy'})
        try:
            audio = self.server.engine.render(character, text)
            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            profile = self.server.engine.voices[character]
            model = ('qwen3-tts-' + profile.get('qwen_size', '0.6B').lower()
                     if profile.get('engine') == 'qwen' else 'breeze-tts-2')
            self.send_header('X-Voice-Model', model)
            self.send_header('Content-Length', str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            logging.warning('Voice generation failed: %s', type(exc).__name__)
            self.send_json(503, {'error': 'Voice unavailable'})
        finally:
            VOICE_LOCK.release()


def main():
    logging.basicConfig(level=logging.INFO)
    token = Path(os.environ['PUMPKIN_TOKEN_FILE']).read_text().strip()
    if len(token) < 32:
        raise ValueError('Backend token too short')
    engine = VoiceEngine()
    engine.render('patch', 'Boo.')  # Warm CUDA graphs before accepting porch requests.
    for name, profile in engine.voices.items():
        if profile.get('engine') == 'qwen':
            engine.render(name, 'Welcome to the porch.')
    server = ThreadingHTTPServer(('127.0.0.1', 8767), VoiceHandler)
    server.token = token
    server.engine = engine
    logging.info('Original character voice server ready on loopback port 8767')
    server.serve_forever()


if __name__ == '__main__':
    main()
