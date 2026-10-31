"""Pi camera, Hailo presence, half-duplex voice, and optional SPI lighting."""
import argparse
import atexit
from array import array
import base64
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import random
import select
import signal
import subprocess
import tempfile
import threading
import time
import wave

import requests

from core import CHARACTERS, AUTO_CHARACTERS, SPECIAL_CHARACTERS, BOO_REPLIES, Encounter, brightness, clean_reply, encode_leds, flame_rgb, HOUSES, SORTING_LINES, person_presence
from games import GAMES, CONTROL_ACTIONS, MODE_ACTIONS, choose_game, intent
from controls import Controls, CONTROL_LINES, WAKE_LINE, LOUDER_LINE, QUIETER_LINE
from entertainment import Library, story_chunks
from loudness import normalize_wav
from idle_music import IdleMusic

ROOT = Path(__file__).resolve().parent
COLORS = {'patch': (255, 70, 0), 'boo': (80, 130, 255), 'nibbles': (70, 255, 10),
          'trogdor': (255, 35, 0), 'sorting_hat': (255, 170, 25), 'dobby': (70, 190, 255), 'voldemort': (25, 255, 55)}
COLORS['voldemort_pumpkin'] = COLORS['patch']


class Lights:
    def __init__(self):
        self.level = None
        self.character = 'patch'
        self.sleeping = False
        self.count = int(os.environ.get('LED_COUNT', '0'))
        self.spi = None
        self.stop = threading.Event()
        self.thread = None
        if not 0 <= self.count <= 60:
            raise ValueError('LED_COUNT must be 0..60')
        if self.count:
            import spidev
            self.spi = spidev.SpiDev()
            self.spi.open(0, 0)
            self.spi.max_speed_hz = 2400000
            self.spi.mode = 0
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
            atexit.register(self.close)

    def run(self):
        while not self.stop.is_set():
            level = self.level
            if self.sleeping:
                rgb = (0, 0, 0)
            elif level is None:
                rgb = flame_rgb(time.monotonic())
            else:
                # Cap speech lighting to 15%, including spell flourishes.
                rgb = tuple(round(v * min(.15, max(0, level * .15))) for v in COLORS[self.character])
            try:
                self.spi.xfer2(list(encode_leds(rgb, self.count)))
            except OSError:
                logging.exception('LED output failed; disabling lights')
                return
            time.sleep(.04)

    def close(self):
        if self.spi is None:
            return
        self.stop.set()
        self.thread.join(timeout=2)
        try:
            self.spi.xfer2(list(encode_leds((0, 0, 0), self.count)))
        finally:
            self.spi.close()
            self.spi = None


class Speech:
    def __init__(self, lights):
        self.lights = lights
        self.cache = ROOT / 'cache'
        self.cache.mkdir(exist_ok=True)
        self.output = os.environ.get('AUDIO_OUTPUT', 'plughw:CARD=UACDemoV10,DEV=0')
        self.preroll = float(os.environ.get('AUDIO_PREROLL_SECONDS',
                                           '3' if 'bluealsa' in self.output.lower() else '0'))
        if not math.isfinite(self.preroll) or not 0 <= self.preroll <= 5:
            raise ValueError('AUDIO_PREROLL_SECONDS must be 0..5')
        library = ROOT / 'entertainment.json'
        self.authored_jokes = ({item['text'] for item in Library(library).data['jokes']}
                               if library.exists() else set())

    def render(self, character, text):
        text = clean_reply(text)
        version = os.environ.get('VOICE_CACHE_VERSION', 'pocket-v1')
        if CHARACTERS[character].get('voice_revision'):
            version += ':' + CHARACTERS[character]['voice_revision']
        key = hashlib.sha256((version + ':' + character + ':' + text).encode()).hexdigest()[:24]
        authored = ([line for scene in GAMES.values() for line in scene['lines']]
                    + list(CONTROL_LINES) + BOO_REPLIES[character] + list(SORTING_LINES.values()))
        fixed = (text in CHARACTERS[character]['greetings'] or text == CHARACTERS[character]['fallback']
                 or text in authored or text in self.authored_jokes)
        path = (self.cache if fixed else Path('/dev/shm')) / ('pumpkin-' + key + '.wav')
        if path.exists():
            return path
        local = 'http://127.0.0.1:8765/tts'
        preferred = os.environ.get('TTS_URL', local)
        urls = [preferred] if preferred == local else [preferred, local]
        token = Path(os.environ.get('PUMPKIN_TOKEN_FILE', str(ROOT / 'backend.token'))).read_text().strip()
        for url in urls:
            try:
                response = requests.post(url, data={'text': text, 'voice_url': CHARACTERS[character]['voice']},
                                         headers={'Authorization': 'Bearer ' + token}, timeout=(3, 45))
                response.raise_for_status()
                break
            except requests.RequestException:
                if url == urls[-1]:
                    raise
        if url != preferred:
            path = Path('/dev/shm') / ('pumpkin-' + key + '.wav')
        with tempfile.TemporaryDirectory(dir='/dev/shm', prefix='pumpkin-tts-') as directory:
            raw = Path(directory) / 'raw.wav'
            cooked = Path(directory) / 'cooked.wav'
            raw.write_bytes(response.content)
            original = response.headers.get('X-Voice-Model') in ('qwen3-tts-0.6b', 'qwen3-tts-1.7b', 'breeze-tts-2')
            effects = [] if original else ['pitch', str(CHARACTERS[character]['pitch'])]
            if character == 'boo' and not original:
                effects.extend(['reverb', '30', '30', '40'])
            if effects:
                acted = Path(directory) / 'acted.wav'
                subprocess.run(['sox', str(raw), '-b', '16', str(acted), *effects],
                               check=True, capture_output=True, timeout=20)
                raw = acted
            normalize_wav(raw, cooked, boost_db=3 if character == 'voldemort' else 0)
            path.write_bytes(cooked.read_bytes())
        return path

    def say(self, character, text, current=None):
        if current is None or current():
            self.play(self.render(character, text), character, text, current=current)

    def render_story(self, character, text, current=None):
        version = os.environ.get('VOICE_CACHE_VERSION', 'pocket-v1')
        if CHARACTERS[character].get('voice_revision'):
            version += ':' + CHARACTERS[character]['voice_revision']
        key = hashlib.sha256((version + ':story:' + character + ':' + text).encode()).hexdigest()[:24]
        target = self.cache / ('story-' + key + '.wav')
        if target.exists():
            return target
        with tempfile.TemporaryDirectory(dir='/dev/shm', prefix='pumpkin-story-') as directory:
            joined = Path(directory) / 'joined.wav'
            with wave.open(str(joined), 'wb') as output:
                output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                for chunk in story_chunks(text):
                    if current is not None and not current():
                        return None
                    path = self.render(character, chunk)
                    try:
                        with wave.open(str(path)) as part:
                            if (part.getnchannels(), part.getsampwidth(), part.getframerate()) != (1, 2, 24000):
                                raise ValueError('Unexpected story audio format')
                            output.writeframes(part.readframes(part.getnframes()))
                        output.writeframes(bytes(7200))
                    finally:
                        if path.parent == Path('/dev/shm'):
                            path.unlink(missing_ok=True)
            with wave.open(str(joined)) as wav:
                duration = wav.getnframes() / wav.getframerate()
            if duration > 59:
                bounded = Path(directory) / 'bounded.wav'
                subprocess.run(['sox', str(joined), str(bounded), 'tempo', str(duration / 58)],
                               check=True, capture_output=True, timeout=30)
                joined = bounded
            temporary = target.with_suffix('.part.wav')
            temporary.write_bytes(joined.read_bytes())
            temporary.replace(target)
        return target

    def render_routine_pair(self, key, start, current):
        scene = GAMES[key]
        stop = min(start + 2, len(scene['lines']))
        parts, cues = [], []
        cacheable = True
        reply_gap_frames = 4320
        frames = 0
        for index in range(start, stop):
            if not current():
                return None
            if index == scene.get('snap_before'):
                with wave.open(str(ROOT / 'assets/effects/finger-snap.wav')) as sound:
                    if (sound.getnchannels(), sound.getsampwidth(), sound.getframerate()) != (1, 2, 24000):
                        raise ValueError('Unexpected effect audio format')
                    snap = sound.readframes(sound.getnframes())
                cues.append((frames / 24000, 'voldemort'))
                parts.append(snap)
                frames += len(snap) // 2
            actor, text = scene['cast'][index], scene['lines'][index]
            path = self.render(actor, text)
            temporary_part = path.parent == Path('/dev/shm')
            cacheable = cacheable and not temporary_part
            try:
                with wave.open(str(path)) as part:
                    if (part.getnchannels(), part.getsampwidth(), part.getframerate()) != (1, 2, 24000):
                        raise ValueError('Unexpected routine audio format')
                    data = part.readframes(part.getnframes())
            finally:
                if temporary_part:
                    path.unlink(missing_ok=True)
            light_actor = ('voldemort_pumpkin' if actor == 'voldemort'
                           and index >= scene.get('snap_before', len(scene['lines'])) else actor)
            cues.append((frames / 24000, light_actor))
            parts.append(data)
            frames += len(data) // 2
            if index + 1 < stop:
                parts.append(bytes(reply_gap_frames * 2))  # 180 ms for a quick reply.
                frames += reply_gap_frames
        if not current():
            return None
        version = os.environ.get('VOICE_CACHE_VERSION', 'pocket-v1')
        lines = list(zip(scene['cast'][start:stop], scene['lines'][start:stop]))
        fingerprint = hashlib.sha256((version + json.dumps({'lines': lines, 'gap_frames': reply_gap_frames})).encode())
        for data in parts:
            fingerprint.update(data)
        digest = fingerprint.hexdigest()[:24]
        # A temporary fallback must not become a permanent replacement voice.
        directory = self.cache if cacheable else Path('/dev/shm')
        target = directory / ('routine-' + digest + '.wav')
        if not cacheable or not target.exists():
            temporary = target.with_suffix('.part.wav')
            with wave.open(str(temporary), 'wb') as output:
                output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                for data in parts:
                    output.writeframes(data)
            temporary.replace(target)
        return target, cues

    def play(self, path, character, text='', current=None, cues=None):
        self.lights.character = character
        padded = None
        try:
            if current is not None and not current():
                return
            with wave.open(str(path)) as wav:
                rate, channels = wav.getframerate(), wav.getnchannels()
                params = wav.getparams()
                samples = array('h', wav.readframes(wav.getnframes()))
            playback = path
            if self.preroll:
                # A separate silent aplay would close the stream and wake the speaker again.
                with tempfile.NamedTemporaryFile(dir='/dev/shm', prefix='pumpkin-play-',
                                                 suffix='.wav', delete=False) as temporary:
                    padded = Path(temporary.name)
                with wave.open(str(padded), 'wb') as output:
                    output.setparams(params)
                    frames = round(rate * self.preroll)
                    if 'bluealsa' in self.output.lower():
                        # This quiet preparation signal restored initial syllables in field tests.
                        warmup = array('h', (int(300 * math.sin(2 * math.pi * 180 * (i // channels) / rate))
                                             for i in range(frames * channels))).tobytes()
                    else:
                        warmup = bytes(frames * channels * params.sampwidth)
                    output.writeframes(warmup)
                    output.writeframes(samples.tobytes())
                playback = padded
            deadline = self.preroll + len(samples) / (rate * channels) + 5
            process = subprocess.Popen(['aplay', '-q', '-D', self.output, str(playback)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            start = time.monotonic()
            while process.poll() is None:
                elapsed = time.monotonic() - start
                stale = current is not None and not current()
                if stale or elapsed > deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    if stale:
                        return
                    raise TimeoutError('Speaker playback stalled')
                elapsed -= self.preroll
                if elapsed < 0:
                    self.lights.level = None
                    time.sleep(.04)
                    continue
                actor, actor_elapsed = character, elapsed
                for cue_time, cue_actor in cues or ():
                    if elapsed >= cue_time:
                        actor, actor_elapsed = cue_actor, elapsed - cue_time
                self.lights.character = actor
                offset = int(elapsed * rate) * channels
                self.lights.level = (1 if ((text.lower().startswith('boo!') and elapsed < .25)
                                           or (actor == 'voldemort' and actor_elapsed < .6))
                                     else brightness(samples[offset:offset + int(rate * .04) * channels]))
                time.sleep(.04)
            diagnostics = process.stderr.read()
            if isinstance(diagnostics, bytes) and any(word in diagnostics.lower() for word in (b'underrun', b'overrun')):
                logging.warning('ALSA reported a playback underrun or overrun')
            if process.returncode:
                raise RuntimeError('Speaker playback failed')
        finally:
            self.lights.level = None
            if padded is not None:
                padded.unlink(missing_ok=True)
            if path.parent == Path('/dev/shm'):
                path.unlink(missing_ok=True)
        time.sleep(.5)


def listen(device=None, wait=7, current=None):
    device = device or os.environ.get('AUDIO_INPUT', 'plughw:CARD=Device,DEV=0')
    process = subprocess.Popen(['arecord', '-q', '-D', device, '-f', 'S16_LE',
                                '-r', '16000', '-c', '1', '-t', 'raw'],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    started = time.monotonic()
    last_voice = None
    speech = bytearray()
    pre_roll = bytearray()
    threshold = float(os.environ.get('MIC_THRESHOLD', '350'))
    try:
        while time.monotonic() - started < wait:
            if current is not None and not current():
                return b''
            ready, _, _ = select.select([process.stdout], [], [], .2)
            if not ready:
                if process.poll() is not None:
                    raise RuntimeError('Microphone capture failed')
                continue
            chunk = os.read(process.stdout.fileno(), 3200)
            if not chunk:
                raise RuntimeError('Microphone disconnected')
            samples = array('h', chunk[:len(chunk) // 2 * 2])
            rms = math.sqrt(sum(float(s) ** 2 for s in samples) / max(1, len(samples)))
            now = time.monotonic()
            if rms >= threshold:
                if last_voice is None:
                    speech.extend(pre_roll)
                last_voice = now
            if last_voice is not None:
                speech.extend(chunk)
                if now - last_voice >= .9:
                    break
            else:
                pre_roll.extend(chunk)
                del pre_roll[:-9600]
        if len(speech) < 9600:
            return b''
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(speech)
        return buffer.getvalue()
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdout.close()


class Detector:
    def __init__(self):
        from hailo_platform import (HEF, VDevice, ConfigureParams, HailoStreamInterface,
                                    InputVStreamParams, OutputVStreamParams, FormatType, InferVStreams)
        self.stack = ExitStack()
        try:
            self.device = self.stack.enter_context(VDevice())
            hef = HEF(str(ROOT / 'models/yolov8s.hef'))
            params = ConfigureParams.create_from_hef(hef, interface=HailoStreamInterface.PCIe)
            self.group = self.device.configure(hef, params)[0]
            self.input = hef.get_input_vstream_infos()[0]
            inp = InputVStreamParams.make_from_network_group(self.group, quantized=True, format_type=FormatType.UINT8)
            out = OutputVStreamParams.make_from_network_group(self.group, quantized=False, format_type=FormatType.FLOAT32)
            self.infer = self.stack.enter_context(InferVStreams(self.group, inp, out))
            self.stack.enter_context(self.group.activate(self.group.create_params()))
        except Exception:
            self.stack.close()
            raise

    def count(self, frame):
        import cv2
        import numpy as np
        height, width, _ = self.input.shape
        image = cv2.cvtColor(cv2.resize(frame, (width, height)), cv2.COLOR_BGR2RGB)
        output = self.infer.infer({self.input.name: np.expand_dims(image, 0)})
        people = next(iter(output.values()))[0][0]
        count, self.possible_person = person_presence(people)
        return count


class Pumpkin:
    def __init__(self):
        self.lights = Lights()
        self.speech = Speech(self.lights)
        self.music = IdleMusic(ROOT / 'music', self.speech.output)
        self.controls = Controls(ROOT / 'controls.json')
        self.lights.sleeping = self.controls.sleeping
        self.encounter = Encounter()
        self.busy = threading.Lock()
        self.frame_lock = threading.Lock()
        self.status_lock = threading.Lock()
        self.frame = None
        self.frame_time = 0
        self.last_seen = 0
        self.last_game = None
        self.library = Library(ROOT / 'entertainment.json')
        self.retry_after = 0
        self.token = Path(os.environ.get('PUMPKIN_TOKEN_FILE', str(ROOT / 'backend.token'))).read_text().strip()
        self.backend = os.environ.get('PUMPKIN_BACKEND', 'http://127.0.0.1:8766')
        self.stop = threading.Event()
        self.status = {'state': 'starting', 'people': 0, 'leds_enabled': bool(self.lights.count)}

    def set_status(self, **values):
        with self.status_lock:
            self.status.update(values)
            target = ROOT / 'status.json'
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.status))
            temporary.replace(target)

    def choose_character(self, previous=None):
        if self.controls.mode in SPECIAL_CHARACTERS:
            return self.controls.mode
        return previous if previous in AUTO_CHARACTERS else random.choices(AUTO_CHARACTERS, weights=(3, 3, 3, 1, 1))[0]

    def idle_music_allowed(self):
        return (bool(self.music.tracks) and not self.stop.is_set() and not self.controls.sleeping
                and self.frame is not None and not self.encounter.active
                and time.monotonic() - self.frame_time < 1.5
                and not self.status.get('possible_person', False)
                and time.monotonic() - self.last_seen >= 8)

    def turn(self, character, history, audio=b'', image=False, text='', listen_only=False):
        payload = {'character': character, 'history': history, 'text': text,
                   'listen_only': listen_only}
        house = self.status.get('house')
        if character == 'sorting_hat' and house in HOUSES and not listen_only:
            payload['history'] = history[-5:] + [{'role': 'assistant', 'text': 'Our pretend sorting result was ' + house + '.'}]
        if audio:
            payload['audio'] = base64.b64encode(audio).decode()
        if image:
            import cv2
            with self.frame_lock:
                frame = None if self.frame is None else self.frame.copy()
            if frame is not None:
                ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok:
                    payload['image'] = base64.b64encode(jpeg).decode()
        response = requests.post(self.backend + '/turn', json=payload,
                                 headers={'Authorization': 'Bearer ' + self.token}, timeout=(3, 40))
        response.raise_for_status()
        return response.json()

    def play_game(self, character, current, key=None):
        key = key or choose_game(self.last_game, allow_cast=self.controls.mode == 'normal')
        self.last_game = key
        scene = GAMES[key]
        self.set_status(state='game', game=key)
        if scene.get('cast'):
            with ExitStack() as cleanup:
                pairs = []
                for start in range(0, len(scene['lines']), 2):
                    rendered = self.speech.render_routine_pair(key, start, current)
                    if rendered is None:
                        return
                    if rendered[0].parent == Path('/dev/shm'):
                        cleanup.callback(rendered[0].unlink, missing_ok=True)
                    pairs.append(rendered)
                for pair_index, (path, cues) in enumerate(pairs):
                    if not current():
                        return
                    self.speech.play(path, cues[0][1], current=current, cues=cues)
                    if pair_index + 1 < len(pairs) and current():
                        self.set_status(state='listening', game=key)
                        audio = listen(wait=3, current=current)
                        if not current():
                            return
                        if audio:
                            actor = scene['cast'][min(pair_index * 2 + 1, len(scene['cast']) - 1)]
                            heard = self.turn(actor, [], audio=audio, listen_only=True).get('transcript', '')
                            action = intent(heard)
                            if action in CONTROL_ACTIONS:
                                self.control(action, actor, current=current)
                                return
            return
        for index, line in enumerate(scene['lines']):
            if not current():
                return
            self.speech.say(character, line, current=current)
            if scene.get('interactive') and index < len(scene['lines']) - 1:
                self.set_status(state='listening', game=key)
                audio = listen(wait=7)
                if not current():
                    return
                if not audio:
                    self.speech.say(character, 'No offering required. Keep your chocolate! A pumpkin can dream.', current=current)
                    return
                heard = self.turn(character, [], audio=audio, listen_only=True).get('transcript', '')
                action = intent(heard)
                if action in CONTROL_ACTIONS:
                    self.control(action, character, current=current)
                    return
                if action in ('joke', 'story', 'boo', 'sort', 'routine', 'pumpkin_scene'):
                    self.entertain(action, character, current)
                    return
                if not heard or any(word in heard.lower().split() for word in ('no', 'none', 'nope')):
                    self.speech.say(character, 'Keep your chocolate! I shall accept an imaginary biscuit instead. Deliciously invisible.', current=current)
                    return
        if scene.get('clip') and current():
            path = ROOT / 'songs' / (scene['clip'] + '.wav')
            if path.exists():
                self.speech.play(path, scene['performer'], current=current)
            else:
                self.speech.say(character, scene['lyrics'], current=current)

    def sort_visitor(self, current=None):
        if current is not None and not current():
            return
        if not getattr(self, 'house_bag', None):
            self.house_bag = random.sample(HOUSES, len(HOUSES))
            if self.house_bag[-1] == getattr(self, 'last_house', None):
                self.house_bag[0], self.house_bag[-1] = self.house_bag[-1], self.house_bag[0]
        house = self.house_bag.pop()
        self.last_house = house
        self.set_status(state='sorting', character='sorting_hat', house=house)
        self.speech.say('sorting_hat', SORTING_LINES[house], current=current)
        return house

    def entertain(self, kind, character, current):
        if kind == 'pumpkin_scene':
            self.play_game(character, current, key='pumpkin_voldemort')
            return
        if kind == 'routine':
            key = random.choice([name for name, scene in GAMES.items() if scene.get('cast') and name != self.last_game])
            self.play_game(character, current, key=key)
            return
        if kind == 'sort':
            self.sort_visitor(current)
            return
        if kind == 'boo':
            self.set_status(state='boo')
            self.speech.say(character, random.choice(BOO_REPLIES[character]), current=current)
            return
        item = self.library.draw(kind, character)
        self.set_status(state=kind, title=item['title'])
        if kind == 'joke':
            self.speech.say(character, item['text'], current=current)
        else:
            path = self.speech.render_story(character, item['text'], current=current)
            if path is not None:
                deadline = time.monotonic() + self.speech.preroll + 60
                self.speech.play(path, character,
                                 current=lambda: current() and time.monotonic() < deadline)

    def control(self, action, character, announce=True, current=None):
        if action in MODE_ACTIONS:
            self.controls.set_mode(MODE_ACTIONS[action])
            character = self.choose_character(character)
            self.set_status(character=character, character_mode=self.controls.mode)
            if announce:
                line = (CHARACTERS[character]['greetings'][0] if action != 'normal_mode' else
                        'Normal mode. Our special guest has left the porch. Probably through the cat flap.')
                if action == 'sorting_hat_mode':
                    self.sort_visitor(current)
                else:
                    self.speech.say(character, line, current=current)
        elif action == 'sleep':
            self.controls.set_sleep(True)
            self.lights.sleeping = True
            self.set_status(state='sleeping')
        elif action == 'wake':
            self.controls.set_sleep(False)
            self.lights.sleeping = False
            self.encounter.pending = False
            if announce:
                self.speech.say(character, WAKE_LINE, current=current)
        elif action in ('volume_up', 'volume_down'):
            volume = self.controls.adjust(10 if action == 'volume_up' else -10)
            self.set_status(volume=volume)
            if announce:
                self.speech.say(character, LOUDER_LINE if action == 'volume_up' else QUIETER_LINE, current=current)

    def sleep_loop(self):
        if not self.busy.acquire(blocking=False):
            return
        character = self.status.get('character', 'patch')
        woke = False
        def current():
            return not self.stop.is_set() and (self.controls.sleeping or not self.encounter.active)
        try:
            while current():
                character = self.choose_character(character)
                if self.idle_music_allowed():
                    self.set_status(state='idle_music')
                    if not self.music.play(lambda: current() and self.idle_music_allowed()):
                        self.stop.wait(.2)
                    continue
                self.set_status(state='sleeping' if self.controls.sleeping else 'waiting_for_keyword')
                audio = listen(current=current)
                if not audio or not current():
                    continue
                try:
                    heard = self.turn(character, [], audio=audio, listen_only=True).get('transcript', '')
                    if not current():
                        continue
                    action = intent(heard)
                    if action in CONTROL_ACTIONS:
                        woke = action == 'wake' and self.controls.sleeping
                        self.control(action, character, announce=action == 'wake' or not self.controls.sleeping)
                    elif not self.controls.sleeping and action in ('joke', 'story', 'boo', 'sort', 'routine', 'pumpkin_scene'):
                        self.entertain(action, character, current)
                    elif not self.controls.sleeping and action == 'game':
                        self.play_game(character, current)
                    elif not self.controls.sleeping and self.controls.mode in SPECIAL_CHARACTERS and heard:
                        result = self.turn(character, [], text=heard)
                        if result.get('text'):
                            self.speech.say(character, result['text'], current=current)
                except (requests.RequestException, ValueError):
                    time.sleep(1)
        except Exception:
            logging.exception('Wake listening failed')
            self.retry_after = time.monotonic() + 5
        finally:
            self.set_status(state='sleeping' if self.controls.sleeping else 'idle')
            self.busy.release()
        if woke and not self.controls.sleeping and self.encounter.active and not self.stop.is_set():
            self.interact(generation=self.encounter.generation, resume=True)

    def interact(self, chosen=None, generation=None, resume=False):
        if not self.busy.acquire(blocking=False):
            return
        character = self.choose_character(chosen or (self.status.get('character', 'patch')
                      if resume or self.status.get('generation') == generation else None))
        def current():
            return not self.stop.is_set() and not self.controls.sleeping and (chosen or (
                self.encounter.active and generation == self.encounter.generation))
        try:
            if not current():
                return
            self.set_status(character=character, generation=generation)
            history = []
            if not resume:
                self.set_status(state='greeting', character=character, house=None)
                greeting = random.choice(CHARACTERS[character]['greetings'])
                history = [{'role': 'assistant', 'text': greeting}]
                with ThreadPoolExecutor(max_workers=1) as pool:
                    judge = ('sorting_hat' if self.controls.mode == 'normal' and random.random() < .25 else character)
                    vision = pool.submit(self.turn, judge, history, image=True)
                    self.speech.say(character, greeting, current=current)
                    try:
                        self.set_status(state='looking', character=character)
                        result = vision.result()
                        if result.get('text') and current():
                            self.speech.say(judge, result['text'], current=current)
                            history.append({'role': 'assistant', 'text': result['text']})
                            if judge == 'sorting_hat' and current():
                                self.sort_visitor(current)
                    except (requests.RequestException, ValueError):
                        logging.warning('Vision unavailable; continuing with local character')
            turns = 0
            quiet = False
            while current():
                selected = self.choose_character(character)
                if selected != character:
                    character, history, turns, quiet = selected, [], 0, False
                    self.set_status(character=character)
                if not current():
                    break
                self.set_status(state='waiting_for_keyword' if quiet else 'listening')
                audio = listen()
                if not current():
                    break
                if not audio:
                    quiet = True
                    continue
                self.set_status(state='thinking')
                try:
                    heard = self.turn(character, [], audio=audio, listen_only=True).get('transcript', '')
                    if not current():
                        break
                    action = intent(heard)
                    if action in CONTROL_ACTIONS:
                        self.control(action, character, current=current)
                        turns, quiet = 0, False
                        continue
                    if action == 'game':
                        self.play_game(character, current)
                        turns, quiet = 0, False
                        continue
                    if action in ('joke', 'story', 'boo', 'sort', 'routine', 'pumpkin_scene'):
                        self.entertain(action, character, current)
                        turns, quiet = 0, False
                        continue
                    if not heard or ((quiet or turns >= 3) and self.controls.mode not in SPECIAL_CHARACTERS):
                        quiet = True
                        continue
                    result = self.turn(character, history[-6:], text=heard)
                except (requests.RequestException, ValueError):
                    if not quiet:
                        self.speech.say(character, CHARACTERS[character]['fallback'], current=current)
                    quiet = True
                    time.sleep(1)
                    continue
                if not result.get('text'):
                    break
                if not current():
                    break
                history.extend([{'role': 'user', 'text': heard},
                                {'role': 'assistant', 'text': result['text']}])
                history = history[-6:]
                self.speech.say(character, result['text'], current=current)
                turns += 1
        except Exception:
            logging.exception('Encounter failed')
            if current():
                self.encounter.pending = True
                self.retry_after = time.monotonic() + 5
        finally:
            self.set_status(state='sleeping' if self.controls.sleeping else 'idle')
            self.busy.release()

    def run(self):
        import cv2
        detector = Detector()
        camera = None
        try:
            while not self.stop.is_set():
                if (self.controls.sleeping or not self.encounter.active) and not self.busy.locked() and time.monotonic() >= self.retry_after:
                    threading.Thread(target=self.sleep_loop, daemon=True).start()
                if camera is None:
                    camera = cv2.VideoCapture(os.environ.get('CAMERA', '/dev/video0'), cv2.CAP_V4L2)
                    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                ok, frame = camera.read()
                if not ok:
                    self.set_status(state='camera_unavailable', people=0)
                    with self.frame_lock:
                        self.frame = None
                    self.encounter.observe(False, time.monotonic())
                    camera.release()
                    camera = None
                    time.sleep(2)
                    continue
                count = detector.count(frame)
                now = time.monotonic()
                with self.frame_lock:
                    self.frame = frame
                    self.frame_time = now
                if detector.possible_person:
                    self.last_seen = now
                self.set_status(people=count, possible_person=detector.possible_person)
                self.encounter.observe(bool(count), now)
                generation = self.encounter.claim() if not self.busy.locked() and not self.controls.sleeping and now >= self.retry_after else None
                if generation is not None:
                    logging.info('Visitor arrival: %s person detections', count)
                    threading.Thread(target=self.interact, kwargs={'generation': generation}, daemon=True).start()
                if not self.busy.locked():
                    self.set_status(state='sleeping' if self.controls.sleeping else 'idle')
                time.sleep(.2)
        finally:
            if camera is not None:
                camera.release()
            detector.stack.close()


def main():
    controller = None
    def shutdown(*_):
        if controller is not None:
            controller.stop.set()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, shutdown)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    parser = argparse.ArgumentParser()
    parser.add_argument('--say', choices=CHARACTERS)
    parser.add_argument('--text')
    parser.add_argument('--interact', choices=CHARACTERS)
    parser.add_argument('--check-camera', action='store_true')
    parser.add_argument('--boo', action='store_true')
    parser.add_argument('--game', choices=GAMES)
    args = parser.parse_args()
    if args.check_camera:
        import cv2
        detector = Detector()
        camera = cv2.VideoCapture('/dev/video0', cv2.CAP_V4L2)
        try:
            ok, frame = camera.read()
            if not ok:
                raise RuntimeError('No webcam frame')
            started = time.monotonic()
            count = detector.count(frame)
            print(json.dumps({'camera': list(frame.shape), 'people': count,
                              'inference_ms': round((time.monotonic() - started) * 1000, 1)}))
        finally:
            camera.release()
            detector.stack.close()
    elif args.game:
        Pumpkin().play_game('patch', lambda: True, key=args.game)
    elif args.boo:
        Speech(Lights()).say('boo', 'Boo! Just kidding. Happy Halloween!')
    elif args.say:
        Speech(Lights()).say(args.say, args.text or CHARACTERS[args.say]['greetings'][0])
    elif args.interact:
        Pumpkin().interact(args.interact)
    else:
        controller = Pumpkin()
        controller.run()


if __name__ == '__main__':
    main()
