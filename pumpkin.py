"""Pi camera, Hailo presence, half-duplex voice, and optional SPI lighting."""
import argparse
import atexit
from array import array
import base64
from contextlib import ExitStack, nullcontext
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import random
import signal
import socket
import subprocess
import tempfile
import threading
import time
import wave
import zlib

import requests

from core import CHARACTERS, AUTO_CHARACTERS, AUTO_WEIGHTS, SPECIAL_CHARACTERS, BOO_REPLIES, Encounter, brightness, clean_reply, encode_leds, flame_rgb, HOUSES, SORTING_LINES, person_presence, strong_person
from games import GAMES, CONTROL_ACTIONS, MODE_ACTIONS, SONGS, benched, choose_game, intent
from controls import Controls, CONTROL_LINES, WAKE_LINE, LOUDER_LINE, QUIETER_LINE
from entertainment import Library, story_chunks
from loudness import normalize_wav
from idle_music import IdleMusic
from voice_input import listen
import voice_input
from routine_audio import trim_quiet_edges, split_internal_voice
from vision_frames import visitor_image
from unifi_client import UniFiBridge
from visitor_motion import VisitorMotion, WebcamDeparture
from porch_crossing import PorchCrossing
from alert_light import AlertLight
from garage_fire import FireLights
from wled_strip import WledStrip
from porch_bits import (AUTHORED_LINES, DOORBELL_BITS, RING_AGAIN_BITS, RING_THIRD_BITS, DOORSTEP_BITS,
                        PREMATURE_RING_BITS, DANCE_DOORBELL, DANCE_DOORBELL_STILL, FILLER_BITS, INTERACTIVE, NEEDS_BULBS, NO_INSIDE_FILLERS, SPELL_BIT,
                        SPELL_REPLIES, host_text, LINGERING, OVERSTAY_BITS, OVERSTAY_ORDER, POSE_GAMES, HAND_CALLS, HINTS,
                        TROGDOR_BITS, TROGDOR_ROUTINES, uses_inside,
                        RING_FALLBACK, RING_INTERRUPTED, INSIDE_ACTOR, choose, farewell, heckle, lure, quick_reply, reaction, resolve)
from porch_zones import PorchZones
import pose
from speaker_bus import SpeakerBus, sample_chunks
from sorting_ceremonies import (AUTHORED_SORTING, LOOKING, NOT_FOUND, NUDGE, POSITION, UNSURE, house_line,
                                opening as sorting_opening, verdict as sorting_verdict)

ROOT = Path(__file__).resolve().parent
COLORS = {'patch': (255, 70, 0), 'boo': (80, 130, 255), 'nibbles': (70, 255, 10),
          'trogdor': (255, 35, 0), 'sorting_hat': (255, 170, 25), 'dobby': (70, 190, 255), 'voldemort': (25, 255, 55)}
COLORS['voldemort_pumpkin'] = COLORS['patch']


# WiZ porch bulbs (local UDP, no cloud). Voldemort inside the pumpkin glows green on the porch.
WIZ_COLORS = {**COLORS, 'patch': (255, 80, 0), 'voldemort_pumpkin': COLORS['voldemort'], 'doorbell': (150, 190, 255)}
FIRE = (255, 45, 0)
DRAGON_EFFECTS = ('roar', 'chomp', 'big-chomp', 'burp')


HOUSE_COLORS = {'Gryffindor': (255, 10, 0), 'Ravenclaw': (20, 60, 255), 'Hufflepuff': (255, 190, 0),
                'Slytherin': (0, 255, 60)}
WHITE = (255, 255, 255)
# Named scene light cues: name -> (mode, rgb).
LIGHT_CUES = {'blackout': ('off', None), 'lightning': ('strobe', WHITE), 'fire': ('flicker', FIRE),
              'green': ('solid', COLORS['voldemort']), 'ghost': ('flicker', COLORS['boo']),
              'houses': ('cycle', None), 'lumos': ('solid', WHITE), 'lastcall': ('blink', (255, 170, 60)),
              **{house.lower(): ('solid', rgb) for house, rgb in HOUSE_COLORS.items()}}


def wiz_pilot(lights, now, rng=random):
    """setPilot params for the porch bulbs from the pumpkin's current light state."""
    if lights.sleeping:
        return {'temp': 2700, 'dimming': lights.wiz_sleep_dimming}
    active = [accent for accent in getattr(lights, 'accents', ()) if accent[0] <= now < accent[1]]
    if active:
        _, _, mode, rgb = max(active, key=lambda accent: accent[0])  # The newest cue wins.
        if mode == 'off':
            return {'state': False}
        dimming = 100
        if mode == 'flicker':
            dimming = rng.randint(45, 100)
        elif mode == 'strobe':
            dimming = 100 if int(now * 8) % 2 == 0 else 10
        elif mode == 'cycle':
            rgb = list(HOUSE_COLORS.values())[int(now * 3) % len(HOUSE_COLORS)]
        elif mode == 'blink':
            dimming = 100 if int(now * 1.5) % 2 == 0 else 10  # Closing time at the bar.
    elif lights.level is None:
        breath = .5 + .5 * math.sin(now * 1.2)
        rgb = (255, 60 + round(30 * breath), 0)
        dimming = 15 + round(35 * breath) + rng.randint(0, 8)
    else:
        rgb = WIZ_COLORS.get(lights.character, WIZ_COLORS['patch'])
        dimming = 30 + round(70 * min(1, max(0, lights.level)))
        if lights.character == 'trogdor':
            dimming = max(10, dimming - rng.randint(0, 30))  # Burninating flicker.
    r, g, b = (max(0, min(255, int(v))) for v in rgb)
    return {'state': True, 'r': r, 'g': g, 'b': max(b, 1 if not (r or g) else b),
            'dimming': max(10, min(100, dimming))}


class Lights:
    def __init__(self):
        self.level = None
        self.character = 'patch'
        self.sleeping = False
        self.accents = []  # (start, end, mode, rgb) monotonic: doorbell lines, dragon effects, scene cues.
        self.wiz_delay = float(os.environ.get('WIZ_DELAY_SECONDS', '0'))  # Calibrate bulbs against the speakers.
        if not 0 <= self.wiz_delay <= 2:
            raise ValueError('WIZ_DELAY_SECONDS must be 0..2')
        # Entries are IP addresses or bulb MACs (found by broadcast, so DHCP changes do not matter).
        self.wiz_ids = [item.strip().lower().replace(':', '') for item in os.environ.get('WIZ_LIGHTS', '').split(',') if item.strip()]
        self.wiz = [item for item in self.wiz_ids if '.' in item]
        self.wiz_sleep_dimming = int(os.environ.get('WIZ_SLEEP_DIMMING', '30'))
        self.wiz_thread = None
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
        if self.wiz_ids:
            self.wiz_thread = threading.Thread(target=self.run_wiz, daemon=True)
            self.wiz_thread.start()
            atexit.register(self.restore_wiz)
        # ESP32 WLED strip on the local Wi-Fi (WLED_HOST): follows the porch show.
        self.wled = WledStrip(self, WIZ_COLORS, HOUSE_COLORS)
        if self.wled.enabled:
            self.wled.start()
            atexit.register(self.wled.close)

    def flash(self, rgb, seconds, flicker=False, start=0, mode=None):
        now = time.monotonic()
        begin = now + max(0, min(30, start))
        self.accents = [a for a in self.accents if a[1] > now][-8:] + [
            (begin, begin + max(0, min(20, seconds)), mode or ('flicker' if flicker else 'solid'), rgb)]

    def cue(self, name, seconds, start=0):
        """A named scene light cue such as blackout, lightning, fire or a house colour."""
        mode, rgb = LIGHT_CUES[name]
        self.flash(rgb, seconds, start=start, mode=mode)

    def send_wiz(self, sock, params):
        message = json.dumps({'method': 'setPilot', 'params': params}).encode()
        for ip in self.wiz:
            try:
                sock.sendto(message, (ip, 38899))  # Fire and forget: porch Wi-Fi replies are slow.
            except OSError:
                pass

    def find_wiz(self):
        """Broadcast getSystemConfig; map configured MACs to their current IP addresses."""
        macs = {item for item in self.wiz_ids if '.' not in item}
        if not macs:
            return True
        # A fresh socket: errors from bulbs that went offline must not cut the listen short.
        found = {}
        known = self.__dict__.setdefault('wiz_known', {})  # mac -> last address; a missed reply keeps it
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(.2)
            deadline = time.monotonic() + 2.5  # Bulbs answer slowly over porch Wi-Fi.
            next_ask = 0
            while time.monotonic() < deadline and len(found) < len(macs):
                if time.monotonic() >= next_ask:  # Ask three times: weak bulbs miss single broadcasts.
                    next_ask = time.monotonic() + .8
                    targets = ['255.255.255.255', os.environ.get('WIZ_BROADCAST', '192.168.0.255')]
                    targets += [ip for mac, ip in known.items() if mac not in found]
                    for target in targets:
                        try:
                            sock.sendto(b'{"method":"getSystemConfig","params":{}}', (target, 38899))
                        except OSError:
                            pass
                try:
                    data, (ip, _) = sock.recvfrom(2048)
                    mac = json.loads(data).get('result', {}).get('mac', '')
                except (OSError, ValueError, AttributeError):
                    continue
                if mac in macs:
                    found[mac] = ip
        known.update(found)
        self.wiz = sorted({*(item for item in self.wiz_ids if '.' in item), *(known[m] for m in macs if m in known)})
        if (len(found), len(known)) != getattr(self, 'wiz_found', None):
            missing = sorted(macs - set(found))
            logging.info('Porch bulbs found: %d of %d%s', len(known), len(macs),
                         ' (no reply this scan: %s)' % ', '.join(missing) if missing else '')
        self.wiz_found = (len(found), len(known))
        return len(found) == len(macs)

    def run_wiz(self):
        try:
            self._run_wiz()
        except Exception:
            logging.exception('Porch bulb control stopped')

    def _run_wiz(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        last, sent_at, searched, complete = None, 0, float('-inf'), False
        while not self.stop.is_set():
            now = time.monotonic()
            if now - searched > (120 if complete else 10):
                complete = self.find_wiz()
                searched, last = time.monotonic(), None
            # Show the state from WIZ_DELAY_SECONDS ago so the bulbs land with the speakers.
            params = self.delayed_pilot(now) if self.wiz_delay else wiz_pilot(self, now)
            changed = last is None or set(params) != set(last) or any(
                abs(params[k] - last[k]) > (6 if k == 'dimming' else 12) for k in params)
            if changed or now - sent_at > 5:
                self.send_wiz(sock, params)
                last, sent_at = params, now
            try:
                while True:
                    sock.recvfrom(1024)  # Discard replies.
            except (BlockingIOError, OSError):
                pass
            time.sleep(.1 if self.wiz_delay else .2)

    def delayed_pilot(self, now):
        history = self.__dict__.setdefault('wiz_history', deque(maxlen=40))
        history.append((now, wiz_pilot(self, now)))
        due = [params for stamp, params in history if stamp <= now - self.wiz_delay]
        return due[-1] if due else history[0][1]

    def restore_wiz(self):
        self.stop.set()
        if self.wiz_thread is not None:
            self.wiz_thread.join(timeout=2)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for _ in range(2):
            self.send_wiz(sock, {'temp': 2700, 'dimming': 100})
            time.sleep(.1)
        sock.close()

    def run(self):
        while not self.stop.is_set():
            level = self.level
            if self.sleeping:
                rgb = (0, 0, 0)
            elif level is None:
                rgb = flame_rgb(time.monotonic())
            else:
                # Cap speech lighting to 15%, including spell flourishes.
                rgb = tuple(round(v * min(.15, max(0, level * .15))) for v in COLORS.get(self.character, COLORS['patch']))
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


class SimpleResponse:
    def __init__(self, content, headers):
        self.content, self.headers = content, headers


def wake_tone(frames, rate=24000):
    """Faint 180 Hz signal that wakes a speaker amp without being noticed."""
    return array('h', (int(300 * math.sin(2 * math.pi * 180 * i / rate)) for i in range(max(0, frames))))


DOORBELL_VOICE_CHAIN = ('highpass=f=350,lowpass=f=6000,equalizer=f=2500:t=q:w=1.2:g=5,'
                        'acompressor=threshold=-30dB:ratio=10:attack=2:release=60:makeup=8,volume=12dB,'
                        'alimiter=limit=0.6:attack=1:release=30:level=false')
DOORBELL_EFFECT_CHAIN = ('highpass=f=300,acompressor=threshold=-24dB:ratio=4:attack=2:release=200:makeup=4,volume=8dB,'
                         'alimiter=limit=0.6:attack=1:release=60:level=false')


class LineGuard:
    """A line under way finishes when its visit ends (a visitor turning back, a brief dropout, a new
    arrival); only a hard stop or a long remainder cuts it. Lines not yet started are still dropped."""

    def __init__(self, current, duration, hard_stop=None, preempt=None, on_preempt=None):
        self.current = current
        self.duration = duration
        self.hard_stop = hard_stop or (lambda: False)
        self.preempt = preempt or (lambda: False)  # A doorbell press: cut immediately, even mid-line.
        self.on_preempt = on_preempt
        self.finish = float(os.environ.get('FINISH_LINE_SECONDS', '6'))
        self.started = None
        self.kept = False

    def __call__(self):
        if self.preempt():
            if self.started is not None and self.on_preempt is not None:
                self.on_preempt()
            return False
        if self.current is None or self.current():
            return True
        if self.started is None or self.hard_stop():
            return False
        remaining = self.duration - (time.monotonic() - self.started)
        if remaining > self.finish:
            return False
        if not self.kept:
            self.kept = True
            logging.info('Finishing the line under way (%.1fs left) instead of cutting it off', max(0, remaining))
        return True


class Speech:
    def __init__(self, lights):
        self.lights = lights
        self.cache = ROOT / 'cache'
        self.cache.mkdir(exist_ok=True)
        self.output = os.environ.get('AUDIO_OUTPUT', 'plughw:CARD=UACDemoV10,DEV=0')
        self.internal_output = os.environ.get('INTERNAL_AUDIO_OUTPUT', '')
        self.internal_delay = float(os.environ.get('INTERNAL_AUDIO_DELAY_SECONDS', '.4'))
        if not math.isfinite(self.internal_delay) or not 0 <= self.internal_delay <= 2:
            raise ValueError('INTERNAL_AUDIO_DELAY_SECONDS must be0..2')
        self.preroll = float(os.environ.get('AUDIO_PREROLL_SECONDS',
                                           '3' if 'bluealsa' in self.output.lower() else '0'))
        self.warm_preroll = float(os.environ.get('AUDIO_WARM_PREROLL_SECONDS', '0'))
        self.last_output_end = None
        self.hard_stop = lambda: False  # The controller sets this: stop, sleep, or a raised hand.
        self.preempt = lambda: False    # ... and this: a doorbell press waiting to be answered.
        self.ring_cut_at = float('-inf')
        self.last_music_signal = None
        self.prepared_at = None
        self.detection_at = None
        self.bridge = None
        # One always-open Bluetooth stream: no per-line warm-up, ~0.4 s to sound.
        self.bus = (SpeakerBus(self.output, warm_seconds=self.preroll)
                    if 'bluealsa' in self.output.lower() and os.environ.get('SPEAKER_BUS', '1') != '0' else None)
        self.internal_bus_delay = float(os.environ.get('INTERNAL_BUS_DELAY_SECONDS', '.39'))
        # The small amp inside the pumpkin clips the first syllable when it wakes from silence.
        self.inside_lead = float(os.environ.get('INSIDE_LEAD_SECONDS', '.45'))
        if not math.isfinite(self.preroll) or not 0 <= self.preroll <= 5:
            raise ValueError('AUDIO_PREROLL_SECONDS must be 0..5')
        if not math.isfinite(self.warm_preroll) or not 0 <= self.warm_preroll <= 5:
            raise ValueError('AUDIO_WARM_PREROLL_SECONDS must be 0..5')
        library = ROOT / 'entertainment.json'
        self.authored_jokes = ({item['text'] for item in Library(library).data['jokes']}
                               if library.exists() else set())

    def cached(self, character, text):
        """Already rendered, so playing it needs no voice server request."""
        return self.cache_path(character, clean_reply(text)).exists()

    def cache_path(self, character, text):
        version = os.environ.get('VOICE_CACHE_VERSION', 'pocket-v1')
        if CHARACTERS[character].get('voice_revision'):
            version += ':' + CHARACTERS[character]['voice_revision']
        key = hashlib.sha256((version + ':' + character + ':' + text).encode()).hexdigest()[:24]
        authored = ([line for scene in GAMES.values() for line in scene['lines']]
                    + list(CONTROL_LINES) + BOO_REPLIES[character] + list(SORTING_LINES.values()))
        fixed = (text in CHARACTERS[character]['greetings'] or text == CHARACTERS[character]['fallback']
                 or text in authored or text in self.authored_jokes or text in AUTHORED_LINES or text in AUTHORED_SORTING)
        return (self.cache if fixed else Path('/dev/shm')) / ('pumpkin-' + key + '.wav')

    def render(self, character, text, prefetched=None):
        started = time.monotonic()
        text = clean_reply(text)
        path = self.cache_path(character, text)
        if path.exists():
            logging.info('Voice cache hit: actor=%s', character)
            return path
        local = 'http://127.0.0.1:8765/tts'
        preferred = os.environ.get('TTS_URL', local)
        # A different synthesizer changes the character; never silently substitute one.
        token = Path(os.environ.get('PUMPKIN_TOKEN_FILE', str(ROOT / 'backend.token'))).read_text().strip()
        if prefetched is not None:
            # Reply audio rendered by the backend in the same request as the text.
            response = SimpleResponse(prefetched[0], {'X-Voice-Model': prefetched[1],
                                                      'X-Loudness': prefetched[2] if len(prefetched) > 2 else ''})
        else:
            data = {'text': text, 'voice_url': CHARACTERS[character]['voice'],
                    'priority': os.environ.get('TTS_PRIORITY', '')}  # warm_porch sends 'low'.
            for attempt in range(2):
                with self.bridge.audio_priority() if self.bridge is not None else nullcontext():
                    response = requests.post(preferred, data=data,
                                             headers={'Authorization': 'Bearer ' + token}, timeout=(3, 45))
                if getattr(response, 'status_code', 200) not in (429, 503) or attempt:
                    break
                time.sleep(.4)  # Voice server busy: one quick retry.
            response.raise_for_status()
        if preferred != local and response.headers.get('X-Voice-Model') not in (
                'qwen3-tts-0.6b', 'qwen3-tts-1.7b', 'breeze-tts-2'):
            raise ValueError('Expected the selected character voice renderer')
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
            if original and response.headers.get('X-Loudness') == 'matched':
                # The backend already matched loudness (and Voldemort's boost); just decode.
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(raw), '-ar', '24000',
                                '-ac', '1', '-c:a', 'pcm_s16le', str(cooked)], check=True, capture_output=True, timeout=10)
            else:
                normalize_wav(raw, cooked, boost_db=3 if character == 'voldemort' else 0)
            tempo = CHARACTERS[character].get('tempo')
            shaping = CHARACTERS[character].get('audio_filter')
            if tempo or shaping:
                # Faster delivery without a pitch change (long pauses shortened first), and per-voice EQ.
                filters = []
                if tempo:
                    filters += ['silenceremove=stop_periods=-1:stop_duration=0.35:stop_threshold=-45dB:stop_silence=0.25',
                                f'atempo={float(tempo):.2f}']
                if shaping:
                    filters.append(shaping)
                paced = Path(directory) / 'paced.wav'
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(cooked), '-af', ','.join(filters),
                                '-ar', '24000', '-ac', '1', '-c:a', 'pcm_s16le', str(paced)],
                               check=True, capture_output=True, timeout=20)
                cooked = paced
            path.write_bytes(cooked.read_bytes())
        logging.info('Voice rendered: actor=%s model=%s seconds=%.2f', character,
                     response.headers.get('X-Voice-Model', 'local'), time.monotonic() - started)
        return path

    def _ring_cut(self):
        if time.monotonic() - self.ring_cut_at > 2:
            logging.info('Doorbell press: cutting off the line under way')
        self.ring_cut_at = time.monotonic()

    def say(self, character, text, current=None):
        if current is None or current():
            try:
                path = self.render(character, text)
            except (requests.RequestException, ValueError, OSError, subprocess.SubprocessError) as exc:
                # A line that cannot be voiced is skipped; it must not end the whole visit.
                logging.warning('Line skipped: %s could not be voiced (%s)', character, type(exc).__name__)
                return
            self.play(path, character, text, current=current)

    def doorbell_effect(self, name):
        """A doorbell-speaker version of a sound effect: as loud as the doorbell voice (-11 LUFS)."""
        source = ROOT / 'assets/effects' / (name + '.wav')
        path = self.cache / ('doorbell-fx-v1-' + name + '.wav')
        if path.exists() and path.stat().st_mtime >= source.stat().st_mtime:
            return path
        temporary = path.with_suffix('.tmp.wav')
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source), '-af', DOORBELL_EFFECT_CHAIN,
                        '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', str(temporary)],
                       check=True, capture_output=True, timeout=10)
        temporary.replace(path)
        return path

    def render_doorbell(self, text):
        """Explicit clear narrator for the small speaker; never a character fallback."""
        text = clean_reply(text)
        key = hashlib.sha256(('doorbell-clear-alba-v3:' + text).encode()).hexdigest()[:24]
        path = self.cache / ('doorbell-' + key + '.wav')
        if path.exists():
            return path
        response = requests.post('http://127.0.0.1:8765/tts',
                                 data={'text': text, 'voice_url': 'alba'}, timeout=(2, 45))
        response.raise_for_status()
        if not 44 < len(response.content) < 2000000:
            raise ValueError('Invalid clear doorbell voice')
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            raw, matched, clear = (Path(directory) / name for name in ('raw.wav', 'matched.wav', 'clear.wav'))
            raw.write_bytes(response.content)
            normalize_wav(raw, matched)
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(matched),
                # Loud for a noisy porch: small-speaker band, presence lift, heavy compression into a
                # limiter. About -12 LUFS with peaks near -2.6 dBFS after both Opus hops (was -15).
                '-af', DOORBELL_VOICE_CHAIN,
                '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', str(clear)],
                check=True, capture_output=True, timeout=10)
            with wave.open(str(clear)) as wav:
                if not 0 < wav.getnframes() / wav.getframerate() <= 15:
                    raise ValueError('Doorbell line is too long')
            path.write_bytes(clear.read_bytes())
        return path

    def prepare_output(self, current):
        """Overlap the known Bluetooth preparation tone with the doorbell's cue."""
        if 'bluealsa' not in self.output.lower() or self.preroll < 3 or not current() or getattr(self, 'bus', None) is not None:
            return
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            path = Path(directory) / 'prepare.wav'
            samples = array('h', (int(300 * math.sin(2 * math.pi * 180 * i / 24000))
                                  for i in range(round(24000 * self.preroll))))
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                wav.writeframes(samples.tobytes())
            self.play(path, self.lights.character, current=current, preroll=0)
        if current():
            self.prepared_at = time.monotonic()

    def render_lines(self, character, lines, current):
        parts = []
        permanent = True
        for line in lines:
            if not current():
                return None
            path = self.render(character, line)
            permanent = permanent and path.parent == self.cache
            try:
                with wave.open(str(path)) as audio:
                    if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 24000):
                        raise ValueError('Unexpected ceremony audio format')
                    parts.append(bytes(trim_quiet_edges(array('h', audio.readframes(audio.getnframes())), 24000)))
            finally:
                if path.parent == Path('/dev/shm'):
                    path.unlink(missing_ok=True)
        joined = bytes(12000).join(parts)  #250ms reply beat in the same output stream.
        if not joined or len(joined) > 60 * 48000:
            raise ValueError('Ceremony exceeded duration limit')
        key = hashlib.sha256(b'ceremony-v1:' + character.encode() + joined).hexdigest()[:24]
        target = (self.cache if permanent else Path('/dev/shm')) / ('ceremony-' + key + '.wav')
        if not target.exists():
            with wave.open(str(target), 'wb') as audio:
                audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                audio.writeframes(joined)
        return target

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
        return self.render_routine(key, current, start, start + 2)

    def render_routine(self, key, current, start=0, stop=None):
        scene = GAMES[key]
        stop = min(stop if stop is not None else len(scene['lines']), len(scene['lines']))
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
            actor, _, place = actor.partition(':')
            if actor == 'fx':
                path = ROOT / 'assets/effects' / (text + '.wav')
            else:
                path = self.render(actor, text)
            temporary_part = path.parent == Path('/dev/shm')
            cacheable = cacheable and not temporary_part
            try:
                with wave.open(str(path)) as part:
                    if (part.getnchannels(), part.getsampwidth(), part.getframerate()) != (1, 2, 24000):
                        raise ValueError('Unexpected routine audio format')
                    data = trim_quiet_edges(part.readframes(part.getnframes()))
            finally:
                if temporary_part:
                    path.unlink(missing_ok=True)
            light_actor = ('voldemort_pumpkin' if place == 'inside' or (actor == 'voldemort'
                           and index >= scene.get('inside_from', scene.get('snap_before', len(scene['lines'])))) else
                           (next((c for _, c in reversed(cues) if c != 'voldemort_pumpkin'), 'patch')
                            if actor == 'fx' else actor))
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

    def enforce_internal_volume(self):
        # The USB amp resets at high settings; preserve the proven 90% ceiling (owner max 92%).
        subprocess.run(['amixer', '-D', 'hw:CARD=UACDemoV10', 'sset', 'PCM', '90%'],
                       check=True, capture_output=True, timeout=3)

    def _led(self, elapsed, samples, rate, channels, character, text, cues):
        actor, actor_elapsed = character, elapsed
        for cue_time, cue_actor in cues or ():
            if elapsed >= cue_time:
                actor, actor_elapsed = cue_actor, elapsed - cue_time
        self.lights.character = actor
        offset = int(elapsed * rate) * channels
        self.lights.level = (1 if ((text.lower().startswith('boo!') and elapsed < .25)
                                   or (actor == 'voldemort' and actor_elapsed < .6))
                             else brightness(samples[offset:offset + int(rate * .04) * channels]))

    def _play_bus(self, path, character, text, current, cues):
        """Play on the always-open Bluetooth stream. Returns False if the bus cannot take it."""
        if self.bus is None or not self.bus.open():
            return False
        with wave.open(str(path)) as wav:
            rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
            params = wav.getparams()
            if (rate, channels, width) != (24000, 1, 2):
                return False
            samples = array('h', wav.readframes(wav.getnframes()))
        playback = samples
        inside_path = None
        inside_head_start = 0
        if self.internal_output and any(actor == 'voldemort_pumpkin' for _, actor in cues or ()):
            self.enforce_internal_volume()
            playback, inside = split_internal_voice(samples, cues, rate)
            lead = getattr(self, 'inside_lead', .45)
            first = min((at for at, actor in cues if actor == 'voldemort_pumpkin'), default=0)
            start = max(0, round((first - lead) * rate))
            stop = round(first * rate)
            inside[start:stop] = wake_tone(stop - start, rate)
            extra = max(0, round((lead - first) * rate))
            inside = wake_tone(extra, rate) + inside
            inside_head_start = extra / rate
            with tempfile.NamedTemporaryFile(dir='/dev/shm', prefix='pumpkin-inside-',
                                             suffix='.wav', delete=False) as temporary:
                inside_path = Path(temporary.name)
            with wave.open(str(inside_path), 'wb') as output:
                output.setparams(params)
                output.writeframes(inside.tobytes())
        self.lights.character = character
        state = {}
        children = []
        head_start = inside_head_start
        current = LineGuard(current, len(samples) / rate, self.hard_stop, self.preempt, self._ring_cut)
        stale = lambda: not current()

        def launch_inside():
            if not stale():
                try:
                    children.append(subprocess.Popen(['aplay', '-q', '-D', self.internal_output, str(inside_path)],
                                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                    logging.info('Cadence inside at=%.3f', time.time())
                except OSError:
                    logging.warning('Inside speaker unavailable for this scene')

        def on_start(job):
            state['start'] = job.start_time
            current.started = job.start_time
            # Wall clock of the first sample reaching the speaker bus, for cadence analysis.
            logging.info('Cadence bus actor=%s at=%.3f dur=%.2f', character,
                         time.time() + job.start_time - time.monotonic(), len(samples) / rate)
            if self.detection_at is not None:
                logging.info('Detection to player open: %.3fs (speaker bus, heard ~%.2fs later)',
                             time.monotonic() - self.detection_at, self.bus.latency)
                self.detection_at = None
            if inside_path:
                timer = threading.Timer(max(0, self.internal_bus_delay - head_start), launch_inside)
                timer.daemon = True
                timer.start()
                state['timer'] = timer

        logging.info('Voice playback on speaker bus: actor=%s duration=%.2f', character, len(samples) / rate)
        # A clip can never hold the porch longer than itself plus a margin, even if the stream stalls.
        limit = time.monotonic() + len(samples) / rate + 5
        outer = current
        current = lambda: (outer is None or outer()) and time.monotonic() < limit
        worker = threading.Thread(target=lambda: state.__setitem__(
            'job', self.bus.play(sample_chunks(playback), current=current, on_start=on_start)), daemon=True)
        worker.start()
        try:
            while worker.is_alive():
                start = state.get('start')
                now = time.monotonic()
                if start is None or now < start:
                    self.lights.level = None
                    time.sleep(.02)
                    continue
                self._led(now - start, samples, rate, channels, character, text, cues)
                time.sleep(.04)
            worker.join()
            deadline = time.monotonic() + 3
            for child in children:
                while child.poll() is None and not stale() and time.monotonic() < deadline:
                    time.sleep(.02)
            self.last_output_end = time.monotonic()
            return True
        finally:
            if state.get('timer'):
                state['timer'].cancel()
            for child in children:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        child.kill()
            if inside_path is not None:
                inside_path.unlink(missing_ok=True)
            self.lights.level = None
            if state.get('job') is not None and path.parent == Path('/dev/shm'):
                path.unlink(missing_ok=True)

    def play(self, path, character, text='', current=None, cues=None, device=None, preroll=None):
        device = device or self.output
        if device == self.output and getattr(self, 'bus', None) is not None:
            if current is not None and not current():
                return
            if self._play_bus(path, character, text, current, cues):
                time.sleep(.12)  # Speaker tail before the microphone opens.
                return
        if device == self.internal_output and device:
            self.enforce_internal_volume()
        if preroll is None:
            preroll = self.preroll
            recent = max((stamp for stamp in (self.last_music_signal, self.prepared_at)
                          if stamp is not None), default=float('-inf'))
            if (device == self.output and 'bluealsa' in device.lower()
                    and recent != float('-inf') and 0 <= time.monotonic() - recent < .75):
                preroll = min(preroll, self.warm_preroll)
        self.lights.character = character
        padded = None
        internal_path = None
        try:
            if current is not None and not current():
                return
            with wave.open(str(path)) as wav:
                rate, channels = wav.getframerate(), wav.getnchannels()
                params = wav.getparams()
                samples = array('h', wav.readframes(wav.getnframes()))
            internal = self.internal_output if (device == self.output and channels == 1 and
                        any(actor == 'voldemort_pumpkin' for _, actor in cues or ())) else ''
            playback_samples = samples
            if internal:
                # The USB amp resets at high settings; preserve the proven90% ceiling (<92%).
                subprocess.run(['amixer', '-D', 'hw:CARD=UACDemoV10', 'sset', 'PCM', '90%'],
                               check=True, capture_output=True, timeout=3)
                playback_samples, inside_samples = split_internal_voice(samples, cues, rate)
                with tempfile.NamedTemporaryFile(dir='/dev/shm', prefix='pumpkin-inside-',
                                                 suffix='.wav', delete=False) as temporary:
                    internal_path = Path(temporary.name)
                with wave.open(str(internal_path), 'wb') as output:
                    output.setparams(params)
                    output.writeframes(bytes(round(rate * (preroll + self.internal_delay)) * 2))
                    output.writeframes(inside_samples.tobytes())
            playback = path
            if preroll or internal:
                # A separate silent aplay would close the stream and wake the speaker again.
                with tempfile.NamedTemporaryFile(dir='/dev/shm', prefix='pumpkin-play-',
                                                 suffix='.wav', delete=False) as temporary:
                    padded = Path(temporary.name)
                with wave.open(str(padded), 'wb') as output:
                    output.setparams(params)
                    frames = round(rate * preroll)
                    if 'bluealsa' in device.lower() or device == self.internal_output:
                        # This quiet preparation signal restored initial syllables in field tests.
                        warmup = array('h', (int(300 * math.sin(2 * math.pi * 180 * (i // channels) / rate))
                                             for i in range(frames * channels))).tobytes()
                    else:
                        warmup = bytes(frames * channels * params.sampwidth)
                    output.writeframes(warmup)
                    output.writeframes(playback_samples.tobytes())
                playback = padded
            deadline = preroll + len(samples) / (rate * channels) + 5
            process = subprocess.Popen(['aplay', '-q', '-D', device, str(playback)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            logging.info('Voice playback opened: actor=%s preroll=%.2f duration=%.2f',
                         character, preroll, len(samples) / (rate * channels))
            logging.info('Cadence device=%s actor=%s at=%.3f dur=%.2f', 'inside' if device == self.internal_output else 'other',
                         character, time.time() + preroll, len(samples) / (rate * channels))
            if self.detection_at is not None:
                logging.info('Detection to player open: %.3fs (plus %.2fs preparation)',
                             time.monotonic() - self.detection_at, preroll)
                self.detection_at = None
            processes = [process]
            if internal_path:
                try:
                    processes.append(subprocess.Popen(['aplay', '-q', '-D', internal, str(internal_path)],
                                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE))
                except Exception:
                    process.terminate()
                    process.wait(timeout=2)
                    raise
            start = time.monotonic()
            if current is not None:
                current = LineGuard(current, len(samples) / (rate * channels), self.hard_stop, self.preempt, self._ring_cut)
                current.started = start + preroll
            elapsed = 0
            while any(child.poll() is None for child in processes):
                elapsed = time.monotonic() - start
                stale = current is not None and not current()
                if stale or elapsed > deadline:
                    for child in processes:
                        child.terminate()
                        try:
                            child.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
                    if stale:
                        return
                    raise TimeoutError('Speaker playback stalled')
                elapsed -= preroll
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
            for child in processes:
                diagnostics = child.stderr.read()
                if isinstance(diagnostics, bytes) and any(word in diagnostics.lower() for word in (b'underrun', b'overrun')):
                    logging.warning('ALSA reported a playback underrun or overrun')
                if child.returncode:
                    raise RuntimeError('Speaker playback failed')
            if device == self.output:
                self.last_output_end = start + max(0, elapsed + preroll)
        finally:
            self.lights.level = None
            if padded is not None:
                padded.unlink(missing_ok=True)
            if internal_path is not None:
                internal_path.unlink(missing_ok=True)
            if path.parent == Path('/dev/shm'):
                path.unlink(missing_ok=True)
        if device != self.internal_output:
            time.sleep(.3)  # Allow the Bluetooth speaker's acoustic tail to clear before listening.


class Detector:
    def __init__(self):
        from hailo_platform import (HEF, VDevice, ConfigureParams, HailoStreamInterface,
                                    InputVStreamParams, OutputVStreamParams, FormatType, InferVStreams)
        self.stack = ExitStack()
        try:
            self.device = self.stack.enter_context(VDevice())
            # YOLOv8s-pose gives the same person boxes plus 17 keypoints (hand raises, pose games).
            pose_model = ROOT / 'models/yolov8s_pose.hef'
            self.pose = os.environ.get('POSE', '1') == '1' and pose_model.exists()
            hef = HEF(str(pose_model if self.pose else ROOT / 'models/yolov8s.hef'))
            logging.info('Person detector: %s', 'yolov8s-pose (keypoints)' if self.pose else 'yolov8s')
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

    def count(self, frame, min_score=.3):
        import cv2
        import numpy as np
        height, width, _ = self.input.shape
        image = cv2.cvtColor(cv2.resize(frame, (width, height)), cv2.COLOR_BGR2RGB)
        output = self.infer.infer({self.input.name: np.expand_dims(image, 0)})
        if self.pose:
            self.people = pose.decode(output, min_score=min_score)
            people = np.array([person['box'] for person in self.people], dtype=np.float32).reshape(-1, 5)
        else:
            self.people = []
            people = next(iter(output.values()))[0][0]
        self.boxes = people
        count, self.possible_person = person_presence(people)
        return count


class Pumpkin:
    def __init__(self):
        self.lights = Lights()
        self.alert = AlertLight()  # Living-room bulb: someone's out front (WIZ_ALERT_LIGHTS).
        self.fire = FireLights()   # Garage bulbs: fireplace, flaring for Trogdor (WIZ_FIRE_LIGHTS).
        self.speech = Speech(self.lights)
        self.speech.hard_stop = lambda: (self.stop.is_set() or self.controls.sleeping
                                         or bool(getattr(self, 'hand_waiting', lambda: False)()))
        self.speech.preempt = lambda: self.ring_waiting()
        self.ringing = False
        self.frontend = self.start_frontend()
        # Webcam feet height (box bottom, 0 top .. 1 bottom): visitors on the path vs passers-by on the
        # sidewalk. Measured on the 2026-10-25 camera position: path start ~.57, sidewalk ~.30-.45.
        self.webcam_visitor_feet = float(os.environ.get('WEBCAM_VISITOR_FEET', '.52'))
        # The corner where the path meets the sidewalk is the frame's left edge, and the plants hide the
        # legs there: a box ending a little higher still counts (night walk 2026-10-26: bottoms .50-.51).
        self.webcam_corner_x = float(os.environ.get('WEBCAM_CORNER_X', '.15'))
        self.webcam_corner_feet = float(os.environ.get('WEBCAM_CORNER_FEET', '.45'))
        self.webcam_sidewalk_feet = float(os.environ.get('WEBCAM_SIDEWALK_FEET', '.25'))
        self.webcam_visitor_score = float(os.environ.get('WEBCAM_VISITOR_SCORE', '.40'))
        # At night the camera is at full gain and people are dim: the scene is static, so a weaker
        # sighting on the path is still a visitor.
        self.webcam_night_score = float(os.environ.get('WEBCAM_NIGHT_SCORE', '.28'))
        self.webcam_night = False
        self.webcam_brightness_at = float('-inf')
        self.webcam_departure = WebcamDeparture(sidewalk=self.webcam_visitor_feet)
        music_gain = float(os.environ.get('MUSIC_GAIN', '1.2'))
        if not math.isfinite(music_gain) or not .5 <= music_gain <= 2:
            raise ValueError('MUSIC_GAIN must be .5..2')
        self.music = IdleMusic(ROOT / 'music', self.speech.output, bus=self.speech.bus, gain=music_gain,
                               songs=sorted((ROOT / 'songs').glob('*.wav')))
        self.controls = Controls(ROOT / 'controls.json')
        self.lights.sleeping = self.controls.sleeping
        self.encounter = Encounter(arrival_delay=.15)
        self.first_detection_at = None
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
        self.bridge = UniFiBridge()
        self.speech.bridge = self.bridge
        self.chime_output = os.environ.get('CHIME_AUDIO_OUTPUT', '')
        self.chime_preroll = float(os.environ.get('CHIME_PREROLL_SECONDS', '.25'))
        if not math.isfinite(self.chime_preroll) or not 0 <= self.chime_preroll <= 5:
            raise ValueError('CHIME_PREROLL_SECONDS must be0..5')
        self.motion = VisitorMotion(allow_retreat=os.environ.get('DEPARTURE_MOTION_ENABLED') == '1')
        gate = [float(value) for value in os.environ.get('PORCH_GATE', '.48,.74,.78').split(',')]
        if len(gate) != 3:
            raise ValueError('PORCH_GATE must contain x1,x2,y')
        self.crossing = PorchCrossing(*gate)
        self.crossing_enabled = os.environ.get('PORCH_CROSSING_ENABLED') == '1'
        self.doorbell_observed = float('-inf')
        self.doorbell_people = 0
        self.doorbell_near = 0
        self.webcam_seen = float('-inf')
        self.farewell_generation = None
        self.last_farewell = {}
        self.last_bit = None
        self.history = []
        self.zones = PorchZones()
        self.doorstep_dwell = float(os.environ.get('DOORSTEP_DWELL_SECONDS', '4'))
        self.last_doorstep_at = float('-inf')
        self.doorstep_generation = None
        self.last_heard = float('-inf')
        self.engaged_generation = None
        self.fillers = {'generation': None, 'count': 0, 'at': float('-inf'), 'show': False}
        self.last_filler = None
        self.sidewalk_frames = 0
        self.sidewalk_seen = float('-inf')
        self.last_lure_at = float('-inf')
        self.last_lure = None
        self.lures_enabled = os.environ.get('LURES_ENABLED', '1') == '1'
        self.reply_timeout = float(os.environ.get('REPLY_TIMEOUT_SECONDS', '7'))

    def bridge_pending(self):
        return bool(getattr(self, 'bridge', None) and self.bridge.pending())

    def ring_waiting(self):
        """A press nobody is answering yet: it pre-empts whatever the porch is doing."""
        return (not getattr(self, 'ringing', False) and not getattr(self.controls, 'sleeping', False)
                and self.bridge_pending())

    def departing(self):
        # A fresh doorbell/person cue covers the area outside the webcam view.
        bridge = getattr(self, 'bridge', None)
        now = time.monotonic()
        zones = getattr(self, 'zones', None)
        webcam = getattr(self, 'webcam_departure', None)
        if zones is not None and getattr(bridge, 'enabled', False) and zones.fresh(now):
            # The G4 loses people past the pumpkin; the path webcam watches them walk away.
            # Somebody still at the door means the visit is not over. (A kid at the pumpkin reads as
            # 'porch' on the G4, so only the door vetoes the webcam's walk-away.)
            if webcam is not None and webcam.departing and not (zones.present(now) and zones.zone == 'door'):
                return True
            return zones.departing(now) and not zones.near(now)
        if webcam is not None and webcam.departing:
            return True
        if now - getattr(self, 'doorbell_observed', float('-inf')) <= 3 and getattr(self, 'doorbell_near', 0):
            return False
        if getattr(self, 'crossing_enabled', False):
            # The G4 sees the doorstep. This webcam sees departing people down
            # the path too, so its generic person presence cannot veto an exit.
            return now - self.doorbell_observed <= 3 and self.crossing.departing
        if now < getattr(bridge, 'presence_until', 0):
            return False
        if getattr(bridge, 'enabled', False):
            return False  # Camera pair is in calibration; absence is not a measured exit.
        return bool(getattr(self, 'motion', None) and self.motion.departing
                    and now >= getattr(bridge, 'presence_until', 0))

    def observe_doorbell(self, detector, now):
        result = self.bridge.latest_frame()
        if result is not None and result[0] > self.doorbell_observed:
            stamp, frame = result
            detector.count(frame)  # Reuse the one Hailo instance, on this thread only.
            # Doorbell poses (about 1 per second): a visitor at the door can raise a hand too.
            self.doorbell_pose = (time.monotonic(), [p for p in getattr(detector, 'people', []) if p['box'][4] >= .5])
            nearest = max(self.doorbell_pose[1], key=lambda p: p['box'][2] - p['box'][0], default=None)
            self.__dict__.setdefault('doorbell_pose_history', deque(maxlen=30)).append((self.doorbell_pose[0], nearest))
            points = self.crossing.people(detector.boxes)
            if points or self.doorbell_people:
                logging.info('Porch geometry: feet=%s frame_age=%.2f',
                             [(round(x, 3), round(y, 3)) for x, y, _ in points], now - stamp)
            self.doorbell_people = len(points)
            self.doorbell_near = sum(y > self.crossing.y - self.crossing.margin for _, y, _ in points)
            events = self.crossing.observe(detector.boxes, stamp)
            for event in (self.zones.observe(points, stamp) if getattr(self, 'zones', None) else ()):
                logging.info('Porch zone: %s (zone=%s)', event, self.zones.zone)
            self.doorbell_observed = stamp
            for direction in events:
                logging.info('Doorbell crossing: %s (actions=%s)', direction, self.crossing_enabled)
        fresh = now - self.doorbell_observed <= 3
        self.set_status(doorbell_people=self.doorbell_people if fresh else 0,
                        doorbell_camera_fresh=fresh, crossing_actions=self.crossing_enabled,
                        doorstep_people=self.doorbell_near if fresh else None,
                        porch_state=self.crossing.state if fresh else 'unknown',
                        porch_zone=self.zones.zone if fresh and getattr(self, 'zones', None) else None,
                        tracking_uncertain=self.crossing.uncertain if fresh else True)
        return self.doorbell_people if fresh else 0

    def on_path(self, box):
        """Webcam box (y1, x1, y2, x2, score) of somebody on the walkway rather than the sidewalk."""
        corner = getattr(self, 'webcam_corner_x', 0)
        return box[2] >= self.webcam_visitor_feet or (
            (box[1] + box[3]) / 2 <= corner and box[2] >= getattr(self, 'webcam_corner_feet', 1))

    def night_view(self, frame):
        """Dark webcam picture (checked every 2 s, with hysteresis): use the night confidence."""
        now = time.monotonic()
        if now - getattr(self, 'webcam_brightness_at', float('-inf')) >= 2:
            self.webcam_brightness_at = now
            level = float(frame[::8, ::8].mean())
            dark, light = (float(os.environ.get(k, d)) for k, d in (('NIGHT_BRIGHTNESS', '55'), ('DAY_BRIGHTNESS', '75')))
            night = level < dark or (getattr(self, 'webcam_night', False) and level < light)
            if night != getattr(self, 'webcam_night', False):
                logging.info('Webcam %s mode (brightness %.0f): visitor confidence %.2f', 'night' if night else 'day',
                             level, self.webcam_night_score if night else self.webcam_visitor_score)
            self.webcam_night = night
        return getattr(self, 'webcam_night', False)

    def audio_settled(self):
        return time.monotonic() >= getattr(getattr(self, 'bridge', None), 'quiet_until', 0)

    def chime_available(self):
        return bool(getattr(self, 'chime_output', '') or
                    (getattr(self, 'bridge', None) and self.bridge.available('chime')))

    def play_chime(self, path, character, current):
        if getattr(self, 'chime_output', ''):
            try:
                self.speech.play(path, character, current=current, device=self.chime_output,
                                 preroll=self.chime_preroll)
                return current()
            except (OSError, RuntimeError, subprocess.SubprocessError):
                logging.warning('Indoor chime speaker unavailable; skipping its cue')
                return False
        return self.bridge.play('chime', path, current)

    def inside_allowed(self, character):
        return bool(getattr(self.speech, 'internal_output', '')) and character != INSIDE_ACTOR

    def doorstep_due(self):
        now = time.monotonic()
        if getattr(self, 'zones', None) is None:
            return False
        return (getattr(getattr(self, 'bridge', None), 'enabled', False) and self.zones.fresh(now)
                and self.zones.at_door_for(now) >= self.doorstep_dwell
                and now - self.last_doorstep_at > 60
                and self.doorstep_generation != self.encounter.generation
                and now - getattr(self.bridge, 'last_ring', float('-inf')) > 20
                and now - self.last_heard > 6)

    def porch_cue(self):
        if self.bridge_pending():
            return 'ring'
        if self.doorstep_due():
            return 'doorstep'
        return None

    def perform_bit(self, character, current, spell=False, kind='ring'):
        """Called only by the worker holding busy; microphones/music stay stopped."""
        doorbell = self.bridge.available('doorbell')
        if spell:
            key, steps = 'spell', resolve(SPELL_BIT, character)
        else:
            bank = DOORBELL_BITS if kind == 'ring' else DOORSTEP_BITS
            if kind == 'ring':
                # Rang again within 15 s: the doorbell escalates.
                now = time.monotonic()
                presses = getattr(self.bridge, 'press_times', None)
                if presses:
                    self.ring_times = [t for t in presses if now - t < 15]  # Counted when pressed, even mid-bit.
                else:
                    self.ring_times = [t for t in getattr(self, 'ring_times', []) if now - t < 15] + [now]
                rings = len(self.ring_times)
                bank = RING_THIRD_BITS if rings >= 3 else RING_AGAIN_BITS if rings == 2 else DOORBELL_BITS
                if rings > 1:
                    logging.info('Doorbell rung %d times in 15 s', rings)
                elif (getattr(self, 'engaged_generation', None) != self.encounter.generation
                      and random.random() < float(os.environ.get('PREMATURE_RING_CHANCE', '.7'))):
                    bank = PREMATURE_RING_BITS  # Rang without a word to the host: the host takes it personally.
            if kind == 'doorstep':
                self.last_doorstep_at = time.monotonic()
                self.doorstep_generation = self.encounter.generation
                if (self.pose_ready() or getattr(self, 'doorbell_people', 0)) and random.random() < float(
                        os.environ.get('DOORSTEP_DANCE_CHANCE', '.3')):
                    logging.info('Porch bit: kind=doorstep key=dance host=%s', character)
                    return self.interactive_bit('dance', character, current)
                if self.engaged_generation == self.encounter.generation:
                    bank = {k: v for k, v in bank.items() if k in ('fake_ring', 'trapped_tip')}
            key = choose(bank, self.last_bit, character, inside=self.inside_allowed(character), doorbell=doorbell)
            if key is None:
                if kind == 'ring':
                    self.speech.say(character, RING_FALLBACK, current=current)
                    return [{'role': 'assistant', 'text': RING_FALLBACK}]
                return []
            self.last_bit = key
            steps = resolve(bank[key], character)
        deadline = time.monotonic() + 30
        valid = lambda: current() and time.monotonic() < deadline
        logging.info('Porch bit: kind=%s key=%s host=%s', 'spell' if spell else kind, key, character)
        self.set_status(state='porch_bit', game=key)
        return self.perform_scene(steps, character, valid)

    def scene_path(self, kind, value, actor):
        if kind == 'effect' and actor == 'doorbell':
            return self.speech.doorbell_effect(value)
        return (ROOT / 'assets/effects' / (value + '.wav') if kind == 'effect'
                else self.speech.render_doorbell(value) if actor == 'doorbell'
                else self.speech.render(actor, value))

    def bus_delay(self):
        """Same reference as the speech light envelope (the bus's latency); WIZ_DELAY_SECONDS adds the rest."""
        bus = getattr(self.speech, 'bus', None)
        return getattr(bus, 'latency', 0) if bus is not None else 0

    def light_accent(self, target, kind, value, path):
        """Porch bulbs: blue while the doorbell talks, fire flicker for dragon noises."""
        lights = getattr(getattr(self, 'speech', None), 'lights', None)
        if lights is None or not hasattr(lights, 'flash'):
            return
        if target == 'doorbell' or (kind == 'effect' and value in DRAGON_EFFECTS):
            try:
                with wave.open(str(path)) as audio:
                    seconds = audio.getnframes() / audio.getframerate()
            except (wave.Error, EOFError, OSError):
                seconds = 2
            if kind == 'effect' and value in DRAGON_EFFECTS:
                lights.flash(FIRE, seconds + .3, flicker=True, start=self.bus_delay() if target == 'porch' else 0)
                if getattr(self, 'fire', None) is not None:
                    self.fire.flare(seconds + 3)  # The garage burninates too.
            else:
                lights.flash(WIZ_COLORS['doorbell'], seconds + 2)  # Covers the bridge's start delay.

    def perform_scene(self, steps, character, valid):
        """Play scene steps; a doorbell step is launched early so it lands on its cue."""
        spoken = []
        steps = list(steps)
        resolved = []
        for target, kind, value, actor in steps:
            if target == 'chime' and not self.chime_available():
                target = 'doorbell'
            if target == 'doorbell' and not self.bridge.available('doorbell'):
                target = 'porch'
            if target == 'inside' and not getattr(self.speech, 'internal_output', ''):
                target = 'porch'
            resolved.append((target, kind, value, actor))
        # Measured 2026-10-25: doorbell request -> sound 0.80 s median (max 1.12). Launching 1.2 s early
        # made it talk over the end of the porch line; 0.65 s lands it just after.
        lead = float(os.environ.get('DOORBELL_LEAD_SECONDS', '.65'))
        early = None  # (index, thread, result) for a doorbell clip already in flight
        for index, (target, kind, value, actor) in enumerate(resolved):
            if not valid():
                break
            if early is not None and early[0] == index:
                early[1].join(timeout=25)
                ok = early[2].get('ok', False)
                early = None
                if not ok:
                    break  # A missing cue must not be followed by its unrelated punchline.
                if kind == 'text':
                    spoken.append({'role': 'assistant', 'text': 'The doorbell: ' + value})
                continue
            if kind == 'pause':
                end = time.monotonic() + min(10, float(value))
                while valid() and time.monotonic() < end:
                    time.sleep(.05)
                continue
            if kind == 'light':
                name, _, seconds = value.partition(':')
                lights = getattr(self.speech, 'lights', None)
                if hasattr(lights, 'cue') and name in LIGHT_CUES:
                    lights.cue(name, float(seconds or 2), start=self.bus_delay())
                continue
            try:
                path = self.scene_path(kind, value, actor)
            except (requests.RequestException, ValueError, OSError, subprocess.SubprocessError):
                logging.warning('Scene step could not be voiced; ending this bit')
                break
            try:
                if not path.exists():
                    break
                following = resolved[index + 1] if index + 1 < len(resolved) else None
                if target in ('porch', 'inside') and following and following[0] == 'doorbell':
                    next_path = self.scene_path(*following[1:])
                    result = {}
                    try:
                        with wave.open(str(path)) as audio:
                            duration = audio.getnframes() / audio.getframerate()
                    except (wave.Error, EOFError):
                        duration = 0
                    if target == 'inside':
                        duration += getattr(self.speech, 'inside_lead', .45)
                    elif not getattr(getattr(self.speech, 'bus', None), 'is_open', False):
                        duration += getattr(self.speech, 'preroll', 0)  # Per-clip fallback adds its preparation.
                    def fire(path=next_path, result=result, delay=max(0, duration - lead), step=following):
                        time.sleep(delay)
                        self.light_accent('doorbell', step[1], step[2], path)
                        result['ok'] = valid() and self.bridge.play('doorbell', path, valid)
                    thread = threading.Thread(target=fire, daemon=True)
                    thread.start()
                    early = (index + 1, thread, result)
                text = value if kind == 'text' else ''
                self.light_accent(target, kind, value, path)
                if target == 'porch':
                    self.speech.play(path, character if actor == 'doorbell' else actor, text=text, current=valid)
                elif target == 'inside':
                    self.speech.play(path, 'voldemort_pumpkin', text=text, current=valid,
                                     device=self.speech.internal_output,
                                     preroll=getattr(self.speech, 'inside_lead', .45))
                elif target == 'chime':
                    if not self.play_chime(path, actor, valid):
                        break
                elif not self.bridge.play(target, path, valid):
                    break  # A missing cue must not be followed by its unrelated punchline.
                if kind == 'text':
                    label = {'doorbell': 'The doorbell: ', 'inside': 'Voldemort, inside the pumpkin: '}.get(target, '')
                    spoken.append({'role': 'assistant', 'text': label + value})
            finally:
                if path.parent == Path('/dev/shm'):
                    path.unlink(missing_ok=True)
        if early is not None:
            early[1].join(timeout=25)
        return spoken

    def filler_due(self, generation):
        if getattr(self, 'zones', None) is None:
            return False
        state = self.fillers
        if state['generation'] != generation:
            state.update(generation=generation, count=0, at=float('-inf'), show=False, used=set())
        now = time.monotonic()
        present = self.status.get('people', 0) or self.zones.near(now)
        return bool(present) and state['count'] < 6 and now - state['at'] >= 5

    def perform_filler(self, character, current, generation):
        """Visitor is standing there quietly: keep the show moving with one short bit."""
        state = self.fillers
        state['count'] += 1
        order = ['scene', 'interactive', 'hint', 'show', 'scene', 'interactive']
        kind = order[(state['count'] - 1) % len(order)]
        auto = character in AUTO_CHARACTERS
        try:
            if kind == 'show' and auto and not state['show']:
                shows = [k for k, v in GAMES.items() if (v.get('show') or v.get('clip')) and k != self.last_game and not benched(k)
                         and (self.speech.internal_output or not any(':inside' in a for a in v['cast']))]
                if shows:
                    state['show'] = True
                    self.play_game(character, current, key=random.choice(shows))
                    return
                kind = 'joke'
            if kind == 'hint':
                line = random.choice([h for h in HINTS if h != getattr(self, 'last_hint', None)])
                self.last_hint = line
                logging.info('Hint: %s', line[:40])
                self.speech.say(character, line, current=current)
                return [{'role': 'assistant', 'text': line}]
            if kind == 'interactive':
                used = state.setdefault('used', set())
                # The dance is judged by the webcam or, at the door, by the doorbell: it needs no pose up front.
                options = [k for k in INTERACTIVE if k not in used
                           and (k != 'lumos' or getattr(self.speech.lights, 'wiz_ids', None))
                           and (k not in POSE_GAMES or k == 'dance' or self.pose_ready())]
                if options:
                    weight = float(os.environ.get('DANCE_WEIGHT', '3'))
                    key = random.choices(options, weights=[weight if k == 'dance' else 1 for k in options])[0]
                    used.add(key)
                    logging.info('Interactive bit: %s host=%s', key, character)
                    return self.interactive_bit(key, character, current)
                kind = 'scene'
            if kind == 'scene':
                bank = FILLER_BITS if self.inside_allowed(character) else {k: FILLER_BITS[k] for k in NO_INSIDE_FILLERS}
                if not getattr(self.speech.lights, 'wiz_ids', None):
                    bank = {k: v for k, v in bank.items() if k not in NEEDS_BULBS}
                doorbell = getattr(self, 'bridge', None) is not None and self.bridge.available('doorbell')
                used = state.setdefault('used', set())
                fresh = {k: v for k, v in bank.items() if k not in used}
                banter = {k: v for k, v in fresh.items() if any(step[0] == 'doorbell' for step in v)}
                if doorbell and banter and self.zones.near(time.monotonic()) and random.random() < .85:
                    fresh = banter  # Someone is on the porch: let the doorbell join in.
                key = choose(fresh or bank, self.last_filler, character,
                             inside=self.inside_allowed(character), doorbell=doorbell)
                if key:
                    used.add(key)
                if key:
                    self.last_filler = key
                    logging.info('Filler bit: %s host=%s', key, character)
                    return self.perform_scene(resolve(bank[key], character), character, current)
            self.entertain('joke', character, current)
        finally:
            state['at'] = time.monotonic()

    def overstay_due(self, generation):
        """Escalating eviction bits for very long visits: first after OVERSTAY_SECONDS, then every OVERSTAY_REPEAT."""
        started = getattr(self, 'visit_started', None)
        if not started or started[0] != generation:
            return None
        done = self.__dict__.setdefault('overstays', {}).get(generation, 0)
        if done >= len(OVERSTAY_ORDER) - (0 if self.inside_allowed(self.status.get('character', 'patch')) else 1):
            return None
        first = float(os.environ.get('OVERSTAY_SECONDS', '120'))
        repeat = float(os.environ.get('OVERSTAY_REPEAT', '60'))
        if time.monotonic() - started[1] < first + done * repeat:
            return None
        self.overstays[generation] = done + 1
        order = [k for k in OVERSTAY_ORDER
                 if k != 'moved_in' or self.inside_allowed(self.status.get('character', 'patch'))]
        return order[done] if done < len(order) else None

    def ask(self, character, line, current, expect=()):
        """Say a line, then return what the visitor said back: '' on silence, '...' if unclear."""
        self.speech.say(character, line, current=current)
        if not current():
            return ''
        audio = listen(current=current)
        if not audio or not current():
            return ''
        try:
            return self.turn(character, [], audio=audio, listen_only=True, expect=expect).get('transcript', '') or '...'
        except (requests.RequestException, ValueError):
            return '...'

    @staticmethod
    def said_spell(heard, spell):
        """After asking for a spell, any short answer counts: it is a porch, not an exam."""
        return bool(heard) and (intent(heard) == spell or len(heard.split()) <= 4)

    def wait_for_view(self, current, seconds=4):
        """The first camera that sees somebody: the webcam on the path, then the doorbell."""
        deadline = time.monotonic() + seconds
        cameras = ['webcam'] + (['doorbell'] if self.sort_camera_available() else [])
        while current() and time.monotonic() < deadline:
            seen = next((name for name in cameras if self.sees_visitor(name)), None)
            if seen:
                return seen
            self.stop.wait(.2)
        return None

    def interactive_bit(self, key, character, current):
        """Tell the visitor to do something urgent and silly, then react to what they actually did."""
        steps = INTERACTIVE[key]
        line = lambda step: host_text(steps[step], character)
        lights = getattr(self.speech, 'lights', None)
        cue = lambda name, seconds: hasattr(lights, 'cue') and lights.cue(name, seconds, start=self.bus_delay())
        spoken = []
        def say(text):
            self.speech.say(character, text, current=current)
            spoken.append({'role': 'assistant', 'text': text})
        if key == 'lumos':
            heard = self.ask(character, line('intro'), current, expect=('Lumos',))
            if not self.said_spell(heard, 'lumos'):
                heard = self.ask(character, line('retry'), current, expect=('Lumos',))
            if self.said_spell(heard, 'lumos'):
                cue('lumos', 30)
                say(line('success'))
            else:
                cue('lumos', 30)
                say(line('giveup'))
            heard = self.ask(character, line('nox_prompt'), current, expect=('Nox',))
            if self.said_spell(heard, 'nox'):
                if hasattr(lights, 'accents'):
                    lights.accents = []
                cue('blackout', 3)
                say(line('nox_done'))
            else:
                say(line('nox_skip'))
            return spoken
        if key == 'hands_up':
            say(line('intro'))
            hands = self.wait_pose(lambda person: pose.hands_raised(person) > 0, 3)
            say(line('zero' if not hands else 'one' if hands == 1 else 'some'))
            return spoken
        if key == 'pumpkin_says':
            say(line('intro'))
            self.stop.wait(.5)
            for step, test in (('s1', lambda person: pose.hands_raised(person) > 0), ('s2', pose.arms_out)):
                say(line(step))
                say(line(step + '_ok') if self.wait_pose(test, 3) else line(step + '_miss'))
            say(line('trick'))
            say(line('caught') if self.wait_pose(pose.hands_on_head, 2.5) else line('safe'))
            return spoken
        if key == 'dance':
            say(line('intro'))
            self.stop.wait(1.5)  # Time to step back onto the walkway.
            start = time.monotonic()
            self.stop.wait(float(os.environ.get('DANCE_SECONDS', '4')))
            end = time.monotonic()
            motion, present = self.dance_motion(start, end)
            # At the door the webcam sees nothing; the doorbell camera (about one frame a second) judges.
            door_motion, door_present = self.dance_motion(start - .5, end + .5, 'doorbell_pose_history')
            if present >= .3:
                outcome = 'great' if motion >= float(os.environ.get('DANCE_MOTION', '.035')) else 'still'
            elif door_present >= .5:
                outcome = 'porch' if door_motion >= float(os.environ.get('DANCE_DOOR_MOTION', '.08')) else 'porch_still'
            else:
                outcome = 'gone'
            logging.info('Dance: webcam motion=%.3f present=%.2f, doorbell motion=%.3f present=%.2f -> %s',
                         motion, present, door_motion, door_present, outcome)
            if outcome == 'porch':  # Danced where only the doorbell could see: the host feels cheated.
                spoken.extend(self.perform_scene([('doorbell', 'text', DANCE_DOORBELL, 'doorbell'),
                                                  ('porch', 'text', line('porch'), character)], character, current))
            elif outcome == 'porch_still':
                spoken.extend(self.perform_scene([('doorbell', 'text', DANCE_DOORBELL_STILL, 'doorbell'),
                                                  ('porch', 'text', line('still'), character)], character, current))
            else:
                say(line(outcome))
            return spoken
        if key == 'flex':
            say(line('intro'))
            say(line('yes') if self.wait_pose(pose.flexing, 3.5) else line('no'))
            return spoken
        # inspection / talent: get them in front of a camera, look, react.
        say(line('intro'))
        seen = self.wait_for_view(current)
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            look = pool.submit(self.turn, character, [], image=True, current=current,
                               purpose='inspection' if key == 'inspection' else 'pose', camera=seen) if seen else None
            if key == 'talent':
                cue('lightning', .5)  # Camera flash.
            say(line('hold' if key == 'inspection' else 'snap'))
            verdict = ''
            if look is not None:
                try:
                    verdict = clean_reply(look.result(timeout=float(os.environ.get('SORT_LOOK_SECONDS', '9'))).get('text', ''))
                except Exception:
                    logging.warning('Interactive look unavailable; using the authored line')
            if 2 < len(verdict.split()) <= 26 and current():
                say(verdict)
                say(line('done'))
            else:
                say(line('unseen'))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return spoken

    def spell(self, kind, character, current):
        """Hidden trick: Lumos or Nox at any time works the porch bulbs."""
        lights = getattr(self.speech, 'lights', None)
        if hasattr(lights, 'cue'):
            lights.accents = []
            lights.cue('lumos' if kind == 'lumos' else 'blackout', 6 if kind == 'lumos' else 3, start=self.bus_delay())
        text = host_text(SPELL_REPLIES[kind], character)
        self.speech.say(character, text, current=current)
        return [{'role': 'assistant', 'text': text}]

    def start_reaction(self, character, current, ready=None):
        """Fill the reply wait with a cached reaction on the always-open speaker."""
        if getattr(self.speech, 'bus', None) is None or os.environ.get('REACTIONS_ENABLED', '1') != '1':
            return None
        line = reaction(character, getattr(self, 'last_reaction', None))
        self.last_reaction = line
        # Only pre-rendered clips: a render now would take the voice server from the real reply.
        if not self.speech.cached(character, line):
            return None
        heckle_line = None
        if self.inside_allowed(character) and random.random() < float(os.environ.get('HECKLE_CHANCE', '.5')):
            candidate = heckle(getattr(self, 'last_heckle', None))
            if self.speech.cached(INSIDE_ACTOR, candidate):
                heckle_line = candidate
        started = time.monotonic()
        def speak():
            try:
                self.speech.say(character, line, current=current)
                # The heckle only fills a long wait; it must never hold up a reply that is ready.
                if (heckle_line and ready is not None and not ready.is_set()
                        and time.monotonic() - started < float(os.environ.get('HECKLE_BEFORE_SECONDS', '3.5'))):
                    self.last_heckle = heckle_line
                    self.perform_scene([('inside', 'text', heckle_line, INSIDE_ACTOR)], character,
                                       lambda: current() and not ready.is_set())
            except Exception:
                logging.exception('Reaction failed')
        thread = threading.Thread(target=speak, daemon=True)
        thread.start()
        return thread

    def speak_reply(self, character, result, voice, current):
        """Play the first sentence as soon as it arrives; the backend is already rendering the rest."""
        first, rest = result.get('voice_text'), result.get('rest')
        if not (isinstance(first, str) and isinstance(rest, str) and first and rest):
            first, rest = result['text'], ''
        pool = ThreadPoolExecutor(max_workers=1) if rest else None
        heard, watch = self.interruptible(current)
        try:
            later = pool.submit(self.speech.render, character, rest) if pool else None
            self.speech.play(self.speech.render(character, first, prefetched=voice), character, first, current=heard)
            if later is not None and not (watch and watch.triggered_at):
                try:
                    path = later.result(timeout=float(os.environ.get('REST_WAIT_SECONDS', '8')))
                except (requests.RequestException, ValueError, OSError, subprocess.SubprocessError, TimeoutError):
                    logging.warning('Rest of reply unavailable; first sentence only')
                    return
                try:
                    self.speech.play(path, character, rest, current=heard)
                finally:
                    if path.parent == Path('/dev/shm'):
                        path.unlink(missing_ok=True)  # Also when the visitor left before the rest.
        finally:
            self.end_interruptible(watch)
            if pool is not None:
                pool.shutdown(wait=False, cancel_futures=True)

    def lure_due(self):
        now = time.monotonic()
        return (getattr(self, 'lures_enabled', False) and now - self.sidewalk_seen < 1.5 and now - self.last_lure_at > 75
                and not self.encounter.active and not self.controls.sleeping)

    def say_lure(self, character, current):
        self.last_lure_at = time.monotonic()
        line = lure(character, self.last_lure)
        self.last_lure = line
        logging.info('Sidewalk lure: host=%s', character)
        self.set_status(state='lure', character=character)
        self.speech.say(character, line, current=current)

    def start_frontend(self):
        """Echo-cancelled always-on microphone; listening falls back to direct capture without it."""
        bus = getattr(self.speech, 'bus', None)
        if os.environ.get('AEC', '1') != '1' or bus is None:
            return None
        try:
            from audio_frontend import AudioFrontEnd
            frontend = AudioFrontEnd(os.environ.get('AUDIO_INPUT', 'plughw:CARD=C920,DEV=0'))
            frontend.start()
        except Exception as exc:
            logging.warning('Echo cancellation unavailable (%s); listening only between lines', type(exc).__name__)
            return None
        bus.tap = frontend.feed_reference
        voice_input.FRONTEND = frontend
        return frontend

    def observe_pose(self, people):
        """Latest path-webcam poses, and whether a hand has been up long enough to count (~0.4 s)."""
        now = time.monotonic()
        self.pose_people = (now, people)
        history = self.__dict__.setdefault('pose_history', deque(maxlen=200))
        history.append((now, max(people, key=lambda p: p['box'][2] - p['box'][0], default=None)))
        stamp, at_door = getattr(self, 'doorbell_pose', (0, []))
        door_hands = sum(1 for person in at_door if pose.hands_raised(person)) if now - stamp < 2 else 0
        hands = sum(1 for person in people if pose.hands_raised(person)) + door_hands
        if hands:
            self.hand_since = getattr(self, 'hand_since', None) or now
        else:
            self.hand_since = None
        self.hand_up = bool(hands) and now - self.hand_since >= float(os.environ.get('HAND_HOLD_SECONDS', '.4'))

    def hand_waiting(self):
        """A raised hand that has not been called on yet: playback yields to it."""
        return (getattr(self, 'hand_up', False)
                and time.monotonic() - getattr(self, 'hand_called_at', float('-inf')) >= 8)

    def take_hand(self):
        """A raised hand to call on (once per raise, with a short cooldown)."""
        now = time.monotonic()
        if not getattr(self, 'hand_up', False) or now - getattr(self, 'hand_called_at', float('-inf')) < 8:
            return False
        self.hand_called_at = now
        return True

    def wait_pose(self, test, seconds):
        """Most path visitors doing a pose at once during the window (pose games)."""
        best, deadline = 0, time.monotonic() + seconds
        while time.monotonic() < deadline:
            stamp, people = getattr(self, 'pose_people', (0, []))
            if time.monotonic() - stamp < 1:
                best = max(best, sum(1 for person in people if test(person)))
            self.stop.wait(.1)
        return best

    def dance_motion(self, start, end, history='pose_history'):
        """(mean keypoint movement per frame, fraction of frames with somebody) for the nearest visitor."""
        frames = [(t, person) for t, person in getattr(self, history, ()) if start <= t <= end]
        if not frames:
            return 0.0, 0.0
        seen = [person for _, person in frames if person is not None]
        steps = [pose.movement(a, b) for a, b in zip(seen, seen[1:])]
        steps = [step for step in steps if step is not None]
        return (sum(steps) / len(steps) if steps else 0.0), len(seen) / len(frames)

    def pose_ready(self):
        stamp, people = getattr(self, 'pose_people', (0, []))
        return bool(people) and time.monotonic() - stamp < 1.5

    def take_barge(self):
        """Capture start for speech that interrupted the last reply (so its first words are kept)."""
        since, self.barge_since = getattr(self, 'barge_since', None), None
        return since

    def interruptible(self, current):
        """(current-with-barge, watch) for a playback a visitor may talk over."""
        frontend = getattr(self, 'frontend', None)
        if frontend is None or not frontend.alive or os.environ.get('BARGE_IN', '0') != '1':  # Off until tuned.
            return current, None
        watch = frontend.watch()
        return (lambda: current() and watch.triggered_at is None), watch

    def end_interruptible(self, watch):
        if watch is None:
            return False
        self.frontend.unwatch(watch)
        if watch.triggered_at is not None:
            self.barge_since = watch.triggered_at - float(os.environ.get('BARGE_PREROLL_SECONDS', '.6'))
            return True
        return False

    def expire_mode(self, now):
        """A special mode lasts for the visit: back to the normal cast once the porch has been empty a while."""
        if (self.controls.mode != 'normal' and not self.busy.locked() and not self.encounter.active
                and now - getattr(self, 'last_seen', now) > float(os.environ.get('MODE_RESET_SECONDS', '300'))):
            logging.info('Mode %s expired after an empty porch; back to normal', self.controls.mode)
            self.controls.set_mode('normal')

    def watch_speaker(self):
        """Restore the saved volume whenever the Bluetooth speaker connects after a power-off or drop."""
        while not self.stop.is_set():
            if hasattr(self.controls, 'sync_speaker'):
                self.controls.sync_speaker()
            self.stop.wait(float(os.environ.get('SPEAKER_CHECK_SECONDS', '10')))

    def external_interact(self, kind):
        if not self.busy.acquire(blocking=False):
            return
        deadline = time.monotonic() + 30
        generation = self.encounter.generation
        was_active = self.encounter.active
        character = self.choose_character(self.status.get('character'))
        def current():
            return (not self.stop.is_set() and not self.controls.sleeping
                    and time.monotonic() < deadline and (kind == 'ring' or not self.ring_waiting())
                    and ((was_active and self.encounter.active and self.encounter.generation == generation)
                         or (not was_active and self.encounter.generation in (generation, generation + 1))))
        try:
            if current() and self.audio_settled():
                if kind == 'ring' and not self.bridge.take():
                    return
                self.ringing = kind == 'ring'
                history = []
                if self.ringing and time.monotonic() - getattr(self.speech, 'ring_cut_at', float('-inf')) < 4:
                    lines = RING_INTERRUPTED.get(character, RING_INTERRUPTED['*'])
                    line = random.choice(lines)
                    self.speech.say(character, line, current=current)
                    history.append({'role': 'assistant', 'text': line})
                self.history = history + self.perform_bit(character, current, kind=kind)
                if self.ringing:
                    self.bridge.drain(keep=1)  # Pressed again during the bit: the next bit escalates once.
                self.set_status(character=character, generation=self.encounter.generation)
                self.encounter.pending = False
        except Exception:
            logging.exception('Porch bit failed')
        finally:
            self.ringing = False
            self.busy.release()
        if current() and self.encounter.active:
            self.interact(generation=self.encounter.generation, resume=True)

    def say_farewell(self, generation):
        if not self.busy.acquire(blocking=False):
            return
        character = self.choose_character(self.status.get('character'))
        deadline = time.monotonic() + 12
        def current():
            return (not self.stop.is_set() and not self.controls.sleeping and self.departing()
                    and self.encounter.generation == generation and not self.bridge_pending()
                    and time.monotonic() < deadline)
        try:
            if current() and self.audio_settled():
                logging.info('Farewell: host=%s', character)
                self.set_status(state='farewell')
                self.farewell_generation = generation  # Spoken (or started): the visitor heard a goodbye.
                if character == 'voldemort' and self.bridge.available('doorbell') and random.random() < .5:
                    self.perform_bit(character, current, spell=True)
                else:
                    line = farewell(character, self.last_farewell.get(character))
                    self.last_farewell[character] = line
                    self.speech.say(character, line, current=current)
        except Exception:
            logging.exception('Farewell failed')
        finally:
            self.busy.release()

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
        return previous if previous in AUTO_CHARACTERS else random.choices(AUTO_CHARACTERS, weights=AUTO_WEIGHTS)[0]

    def idle_music_allowed(self):
        return (bool(self.music.tracks) and not self.stop.is_set() and not self.controls.sleeping
                and self.frame is not None and not self.encounter.active
                and time.monotonic() - self.frame_time < 1.5
                and not self.bridge_pending()
                and time.monotonic() >= getattr(getattr(self, 'bridge', None), 'presence_until', 0)
                and self.audio_settled()
                and not self.status.get('possible_person', False)
                and not self.lure_due()
                and time.monotonic() - self.last_seen >= 8)

    def turn(self, character, history, audio=b'', image=False, text='', listen_only=False, current=None, purpose='conversation', visual_context='', timeout=None, speak=False, split=False, camera=None, expect=()):
        payload = {'character': character, 'history': history, 'text': text,
                   'listen_only': listen_only, 'purpose': purpose}
        if expect:
            payload['expect'] = list(expect)[:5]
        if speak:
            payload['speak'] = True
            if split:
                payload['split'] = True  # Voice for the first sentence only; the rest renders meanwhile.
        if visual_context:
            payload['visual_context'] = visual_context[:300]
        house = self.status.get('house')
        if character == 'sorting_hat' and house in HOUSES and not listen_only:
            payload['history'] = history[-5:] + [{'role': 'assistant', 'text': 'Our pretend sorting result was ' + house + '.'}]
        if audio:
            try:
                compact = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', 'pipe:0',
                    '-ac', '1', '-c:a', 'libopus', '-b:a', '32k', '-application', 'voip',
                    '-f', 'ogg', 'pipe:1'], input=audio, capture_output=True, check=True, timeout=2).stdout
                payload['audio'] = base64.b64encode(compact).decode()
                payload['audio_encoding'] = 'opus'
            except (OSError, subprocess.SubprocessError):
                payload['audio'] = base64.b64encode(zlib.compress(audio, 3)).decode()
                payload['audio_encoding'] = 'zlib'
            logging.info('Microphone upload: codec=%s source_bytes=%d encoded_bytes=%d',
                         payload['audio_encoding'], len(audio), len(payload['audio']))
        if image:
            def snapshot():
                bridge = getattr(self, 'bridge', None)
                if bridge and (camera == 'doorbell' or (camera is None and getattr(self, 'doorbell_people', 0)
                        and not self.status.get('webcam_people', self.status.get('people', 0)))):
                    result = bridge.latest_frame()
                    if result is not None:
                        return result[1].copy()
                with self.frame_lock:
                    if self.frame is None or time.monotonic() - self.frame_time > 1.5:
                        return None
                    return self.frame.copy()
            encoded = visitor_image(snapshot, current or (lambda: True), max_width=384)
            sequence = bool(encoded)
            if not encoded and getattr(self, 'bridge', None) and (current is None or current()):
                encoded = self.bridge.snapshot()
            if current is not None and not current():
                return {'text': ''}
            if not encoded:
                return {'text': ''}
            payload['image'] = encoded
            payload['image_sequence'] = sequence
        started = time.monotonic()
        bridge = getattr(self, 'bridge', None)
        with bridge.audio_priority() if bridge is not None and listen_only else nullcontext():
            response = requests.post(self.backend + '/turn', json=payload,
                                     headers={'Authorization': 'Bearer ' + self.token}, timeout=(3, timeout or (22 if image else 40)))
        response.raise_for_status()
        logging.info('Backend turn: phase=%s seconds=%.2f',
                     'vision' if image else 'asr' if listen_only else 'reply', time.monotonic() - started)
        return response.json()

    def play_game(self, character, current, key=None):
        key = key or choose_game(self.last_game, allow_cast=self.controls.mode == 'normal')
        self.last_game = key
        scene = GAMES[key]
        self.set_status(state='game', game=key)
        if scene.get('cast'):
            with ExitStack() as cleanup:
                rendered = self.speech.render_routine(key, current)
                if rendered is None:
                    return
                path, cues = rendered
                if path.parent == Path('/dev/shm'):
                    cleanup.callback(path.unlink, missing_ok=True)
                if current():
                    self.speech.play(path, cues[0][1], current=current, cues=cues)
            return
        for index, line in enumerate(scene['lines']):
            if not current():
                return
            self.speech.say(character, line, current=current)
            if scene.get('interactive') and index < len(scene['lines']) - 1:
                self.set_status(state='listening', game=key)
                audio = listen(wait=7, current=current)
                if not current():
                    return
                if not audio:
                    self.speech.say(character, 'No candy? That is fine. I cannot eat it anyway. No stomach.', current=current)
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
                    self.speech.say(character, 'Keep it. Honestly, I just wanted to see if you would.', current=current)
                    return
        if scene.get('clip') and current():
            path = ROOT / 'songs' / (scene['clip'] + '.wav')
            if path.exists():
                self.speech.play(path, scene['performer'], current=current)
            else:
                self.speech.say(character, scene['lyrics'], current=current)

    def sort_visitor(self, current=None, observe=False):
        if current is not None and not current():
            return
        if not getattr(self, 'house_bag', None):
            self.house_bag = random.sample(HOUSES, len(HOUSES))
            if self.house_bag[-1] == getattr(self, 'last_house', None):
                self.house_bag[0], self.house_bag[-1] = self.house_bag[-1], self.house_bag[0]
        house = self.house_bag.pop()
        self.last_house = house
        self.set_status(state='sorting', character='sorting_hat', house=house)
        valid = current or (lambda: True)
        intro = sorting_opening(getattr(self, 'last_sorting_intro', None),
                                group=getattr(self, 'status', {}).get('people', 0) > 1)
        self.last_sorting_intro = intro
        pool = ThreadPoolExecutor(max_workers=1) if observe else None
        previous = getattr(self, 'last_sorting_ending', {})
        try:
            if pool:
                # Interactive: place them in front of a camera, look, comment, then sort.
                seen = self.place_visitor(self.sort_camera(), valid)
                look = pool.submit(self.turn, 'sorting_hat', [], image=True, current=valid,
                                   purpose='sorting', camera=seen) if seen else None
                self.speech.say('sorting_hat', random.choice(LOOKING) if seen else NOT_FOUND, current=valid)
                assessment = ''
                if look is not None:
                    try:
                        assessment = clean_reply(look.result(
                            timeout=float(os.environ.get('SORT_LOOK_SECONDS', '9'))).get('text', ''))
                    except Exception:
                        logging.warning('Sorting look unavailable; using the authored line')
                assessment = assessment if 2 < len(assessment.split()) <= 24 else UNSURE
                self.sorting_vision = Future()
                self.sorting_vision.set_result({'text': assessment})  # Context for the conversation after.
                ending_line, ending = house_line(house, previous.get(house))
                parts = [assessment, ending_line]
                line = assessment + ' ' + ending_line
            else:
                line, ending = sorting_verdict(house, previous.get(house))
                parts = [intro, line]
            self.last_sorting_ending = {**previous, house: ending}
            self.last_sorting_line = line
            try:
                path = self.speech.render_lines('sorting_hat', parts, valid)
            except (requests.RequestException, ValueError, OSError, subprocess.SubprocessError):
                logging.warning('Sorting assessment could not be voiced; using the cached verdict')
                line, ending = sorting_verdict(house, previous.get(house))
                parts = [line]
                path = self.speech.render_lines('sorting_hat', parts, valid)
            if path is not None and valid():
                self.sorting_lights(path, house, parts[-1])
                self.speech.play(path, 'sorting_hat', text=line, current=valid)
            if valid() and self.chime_available():
                path = ROOT / 'assets/effects/small-fanfare.wav'
                if path.exists():
                    self.play_chime(path, 'sorting_hat', valid)
            return house
        finally:
            if pool:
                pool.shutdown(wait=False, cancel_futures=True)

    def sorting_lights(self, path, house, ending_text):
        """Porch bulbs cycle the house colours until the announcement, then lock on the house."""
        lights = getattr(self.speech, 'lights', None)
        if not hasattr(lights, 'cue'):
            return
        try:
            ending_path = self.speech.render('sorting_hat', ending_text)  # Cached authored line.
            with wave.open(str(path)) as audio:
                total = audio.getnframes() / audio.getframerate()
            with wave.open(str(ending_path)) as audio:
                at = max(0, total - audio.getnframes() / audio.getframerate())
        except (wave.Error, EOFError, OSError, ValueError, requests.RequestException):
            return
        delay = self.bus_delay()
        lights.cue('houses', at, start=delay)
        lights.cue(house.lower(), total - at + 4, start=delay + at)  # Through the fanfare.

    def sort_camera(self):
        """Which directions to give: back down the path if they are at the door, otherwise toward the webcam."""
        return 'doorbell' if self.sort_camera_available() and self.status.get('doorstep_people') else 'webcam'

    def sees_visitor(self, camera):
        if camera == 'doorbell':
            # On the path, not still standing at the door.
            return bool(getattr(self, 'doorbell_people', 0) or self.status.get('doorbell_people')) and not self.status.get('doorstep_people')
        return bool(self.status.get('webcam_people'))

    def place_visitor(self, camera, valid):
        """Send them to the straight part of the path, then return whichever camera sees them (or None)."""
        self.speech.say('sorting_hat', random.choice(POSITION[camera]), current=valid)
        other = 'webcam' if camera == 'doorbell' else 'doorbell'
        cameras = [camera] + ([other] if other == 'webcam' or self.sort_camera_available() else [])
        deadline, nudged = time.monotonic() + float(os.environ.get('SORT_POSITION_SECONDS', '7')), False
        while valid():
            seen = next((name for name in cameras if self.sees_visitor(name)), None)
            if seen:
                self.stop.wait(.6)  # Let them settle so the picture is not of someone mid-step.
                return seen
            if time.monotonic() >= deadline:
                return None
            if not nudged and time.monotonic() > deadline - 4:
                nudged = True
                self.speech.say('sorting_hat', NUDGE[camera], current=valid)
                deadline = max(deadline, time.monotonic() + 3)  # Time to actually move after hearing it.
            self.stop.wait(.2)
        return None

    def sort_camera_available(self):
        bridge = getattr(self, 'bridge', None)
        return bridge is not None and bridge.available('doorbell')

    def trogdor_scene(self, character, current):
        """A Trogdor scene when somebody says the name. Returns what was spoken, or None during the
        cooldown so a visitor still talking about Trogdor gets a real answer."""
        now = time.monotonic()
        if now - getattr(self, 'last_trogdor_at', float('-inf')) < float(os.environ.get('TROGDOR_COOLDOWN_SECONDS', '45')):
            return None
        inside = self.inside_allowed(character)
        # Doorbell lines fall back to the porch speaker inside perform_scene.
        options = [key for key, scene in TROGDOR_BITS.items() if inside or not uses_inside(scene)]
        options += [key for key in TROGDOR_ROUTINES if not benched(key)
                    and (inside or not any(':inside' in actor for actor in GAMES[key]['cast']))]
        recent = getattr(self, 'recent_trogdor', [])
        key = random.choice([k for k in options if k not in recent] or options)
        self.recent_trogdor = (recent + [key])[-4:]
        self.last_trogdor_at = now
        logging.info('Trogdor scene: %s host=%s', key, character)
        self.set_status(state='trogdor')
        spoken = []
        if key in TROGDOR_BITS:
            spoken = self.perform_scene(resolve(TROGDOR_BITS[key], character), character, current)
        else:
            self.play_game(character, current, key=key)
        self.last_trogdor_at = time.monotonic()
        return spoken

    def entertain(self, kind, character, current):
        if kind == 'pumpkin_scene':
            self.play_game(character, current, key='pumpkin_voldemort')
            return
        if kind == 'routine':
            key = random.choice([name for name, scene in GAMES.items() if scene.get('cast') and name != self.last_game
                                 and not benched(name)])
            self.play_game(character, current, key=key)
            return
        if kind == 'sort':
            self.sort_visitor(current, observe=True)
            return
        if kind == 'boo':
            self.set_status(state='boo')
            if hasattr(self.speech.lights, 'cue'):
                self.speech.lights.cue('lightning', .9, start=self.bus_delay())
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
            character = self.choose_character(None if action == 'normal_mode' else character)
            self.set_status(character=character, character_mode=self.controls.mode)
            if announce:
                line = (CHARACTERS[character]['greetings'][0] if action != 'normal_mode' else
                        'Normal mode. Our special guest has left the porch. Probably through the cat flap.')
                if action == 'sorting_hat_mode':
                    self.sort_visitor(current, observe=True)
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
            return (not self.stop.is_set() and (self.controls.sleeping or not self.encounter.active)
                    and (self.controls.sleeping or not self.status.get('people', 0))
                    and (self.controls.sleeping or not self.bridge_pending()))
        try:
            while current():
                character = self.choose_character(character)
                if not self.audio_settled():
                    self.stop.wait(.1)
                    continue
                if self.lure_due():
                    self.say_lure(character, lambda: current() and not self.status.get('people', 0))
                    continue
                if self.idle_music_allowed():
                    self.set_status(state='idle_music')
                    played = self.music.play(lambda: current() and self.idle_music_allowed())
                    self.speech.last_music_signal = getattr(self.music, 'last_signal_at', None)
                    if not played and current():
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
                    if os.environ.get('DEBUG_TRANSCRIPTS') == '1':  # Owner testing only; off by default.
                        logging.info('Debug heard (idle): %r -> %s', heard, action)
                    if action in CONTROL_ACTIONS:
                        woke = action == 'wake' and self.controls.sleeping
                        self.control(action, character, announce=action == 'wake' or not self.controls.sleeping)
                    elif not self.controls.sleeping and action in ('joke', 'story', 'boo', 'sort', 'routine', 'pumpkin_scene'):
                        self.entertain(action, character, current)
                    elif not self.controls.sleeping and action == 'trogdor_scene':
                        self.trogdor_scene(character, current)
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
        last_spoke = getattr(self.speech, 'last_output_end', None)
        # Someone who just heard a lure, a goodbye or a greeting keeps that same host.
        recent = (last_spoke is not None and time.monotonic() - last_spoke
                  < float(os.environ.get('HOST_CARRY_SECONDS', '30')))
        character = self.choose_character(chosen or (self.status.get('character', 'patch')
                      if resume or self.status.get('generation') == generation or recent else None))
        def alive():
            # Speech already under way finishes even if the visitor turns to leave.
            return (not self.stop.is_set() and not self.controls.sleeping and not self.ring_waiting()
                    and bool(chosen or (self.encounter.active and generation == self.encounter.generation)))
        def current():
            return alive() and not self.departing()
        def yielding():
            # A raised hand cuts the pumpkin off; the listening step then calls on them.
            if self.hand_waiting():
                if getattr(self, 'hand_cut_logged', None) != getattr(self, 'hand_since', None):
                    self.hand_cut_logged = getattr(self, 'hand_since', None)
                    logging.info('Hand raised: interrupting playback')
                return False
            return alive()
        try:
            if not current():
                return
            self.set_status(character=character, generation=generation)
            if getattr(self, 'visit_started', (None,))[0] != generation:
                self.visit_started = (generation, time.monotonic())
            history = list(getattr(self, 'history', []))[-6:] if resume else []
            if (resume and getattr(self, 'farewell_generation', None) == generation
                    and getattr(self, 'lingered', None) != generation):
                # They heard goodbye and did not leave.
                self.lingered = generation
                line = LINGERING.get(character, LINGERING['patch'])
                self.speech.say(character, line, current=alive)
                history = (history + [{'role': 'assistant', 'text': line}])[-6:]
            vision = None
            visual_context = ''
            if not resume:
                self.sorting_vision = None  # A look from an earlier visit is not about this visitor.
                judge = character
                self.set_status(state='greeting', character=character, house=None)
                if judge == 'sorting_hat':
                    character = 'sorting_hat'
                    self.sort_visitor(alive, observe=True)
                    history = [{'role': 'assistant', 'text': getattr(self, 'last_sorting_line', '')}]
                else:
                    greeting = random.choice(CHARACTERS[character]['greetings'])
                    history = [{'role': 'assistant', 'text': greeting}]
                    pool = ThreadPoolExecutor(max_workers=1)
                    try:
                        vision = pool.submit(self.turn, judge, history, image=True, current=alive,
                                             purpose='observation')
                        self.speech.say(character, greeting, current=alive)
                    finally:
                        pool.shutdown(wait=False, cancel_futures=True)
            turns = 0
            quiet = False
            while current():
                if getattr(self, 'sorting_vision', None) is not None:
                    vision = self.sorting_vision
                    self.sorting_vision = None
                selected = self.choose_character(character)
                if selected != character:
                    character, history, turns, quiet = selected, [], 0, False
                    self.set_status(character=character)
                if not current():
                    break
                if not self.audio_settled():
                    self.stop.wait(.1)
                    continue
                overstay = self.overstay_due(generation)
                if overstay:
                    logging.info('Overstay bit: %s host=%s', overstay, character)
                    history = (history + self.perform_scene(resolve(OVERSTAY_BITS[overstay], character), character, alive))[-6:]
                    continue
                cue = self.porch_cue()
                if cue == 'doorstep':
                    history.extend(self.perform_bit(character, alive, kind=cue))
                    history = history[-6:]
                    continue
                patient = False
                if self.take_hand():
                    logging.info('Hand raised: calling on the visitor')
                    line = HAND_CALLS.get(character, HAND_CALLS['patch'])
                    self.speech.say(character, line, current=alive)
                    history = (history + [{'role': 'assistant', 'text': line}])[-6:]
                    patient = True
                self.set_status(state='listening')
                # A raised hand means a question is coming: wait longer and allow pauses.
                patient = patient or getattr(self, 'hand_up', False)
                audio = listen(wait=8 if patient else 5, current=lambda: current() and not self.porch_cue(),
                               since=self.take_barge(), end_silence=.9 if patient else None)
                if not current():
                    break
                if not audio:
                    quiet = True
                    if not self.porch_cue() and self.filler_due(generation):
                        history = (history + (self.perform_filler(character, yielding, generation) or []))[-6:]
                    continue
                self.set_status(state='thinking')
                try:
                    heard = self.turn(character, [], audio=audio, listen_only=True).get('transcript', '')
                    if not current():
                        break
                    if heard and getattr(self, 'zones', None) is not None:
                        self.last_heard = time.monotonic()
                        self.engaged_generation = generation
                    action = intent(heard)
                    if os.environ.get('DEBUG_TRANSCRIPTS') == '1':  # Owner testing only; off by default.
                        logging.info('Debug heard: %r -> %s', heard, action)
                    if action == 'wake' and not self.controls.sleeping:
                        action = None  # Already awake: 'hey pumpkinhead, <question>' is a question.
                    if action in CONTROL_ACTIONS:
                        self.control(action, character, current=alive)
                        turns, quiet = 0, False
                        continue
                    immediate = None if action in ('trogdor_scene', 'game') else quick_reply(character, heard)
                    if immediate:
                        history.extend([{'role':'user','text':heard}, {'role':'assistant','text':immediate}])
                        history = history[-6:]
                        self.speech.say(character, immediate, current=alive)
                        turns, quiet = 0, False
                        continue
                    if action in ('game', 'song'):
                        last_song = getattr(self, 'last_song', None)
                        key = random.choice([k for k in SONGS if k != last_song] or SONGS) if action == 'song' else None
                        self.last_song = key or last_song
                        self.play_game(character, yielding, key=key)
                        turns, quiet = 0, False
                        continue
                    if action in ('lumos', 'nox', 'inspection', 'talent', 'pumpkin_says', 'flex', 'dance'):
                        done = (self.spell(action, character, alive) if action in ('lumos', 'nox')
                                else self.interactive_bit(action, character, alive))
                        history = (history + [{'role': 'user', 'text': heard}] + done)[-6:]
                        turns, quiet = 0, False
                        continue
                    spoken = self.trogdor_scene(character, alive) if action == 'trogdor_scene' else None
                    if spoken is not None:
                        history = (history + [{'role': 'user', 'text': heard}] + spoken)[-6:]
                        turns, quiet = 0, False
                        continue
                    if action in ('joke', 'story', 'boo', 'sort', 'routine', 'pumpkin_scene'):
                        self.entertain(action, character, yielding)
                        if action == 'sort':
                            character = 'sorting_hat'
                            history = [{'role': 'assistant', 'text': getattr(self, 'last_sorting_line', '')}]
                        turns, quiet = 0, False
                        continue
                    if not heard:
                        quiet = True
                        continue
                    if vision is not None and vision.done():
                        try:
                            visual_context = vision.result(timeout=0).get('text', '')[:300]
                        except (requests.RequestException, ValueError, TimeoutError):
                            logging.warning('Visual observation unavailable; continuing conversation')
                        vision = None
                    reply_ready = threading.Event()
                    reacting = self.start_reaction(character, yielding, ready=reply_ready)
                    try:
                        result = self.turn(character, history[-6:], text=heard, visual_context=visual_context,
                                           timeout=getattr(self, 'reply_timeout', None) and self.reply_timeout + 6,
                                           speak=True, split=True)
                    finally:
                        reply_ready.set()
                        if reacting is not None:
                            reacting.join(timeout=6)
                except requests.Timeout:
                    # A slow generated reply is dead air on a porch; fill it with cached material.
                    logging.warning('Generated reply too slow; performing a cached bit instead')
                    if current():
                        self.entertain('joke', character, alive)
                    continue
                except (requests.RequestException, ValueError):
                    if not quiet:
                        self.speech.say(character, CHARACTERS[character]['fallback'], current=alive)
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
                voice = None
                if result.get('voice'):
                    try:
                        voice = (base64.b64decode(result['voice'], validate=True), result.get('voice_model', ''),
                                 result.get('voice_loudness', ''))
                    except ValueError:
                        voice = None
                if voice and voice[1] in ('qwen3-tts-0.6b', 'qwen3-tts-1.7b', 'breeze-tts-2') and len(voice[0]) <= 1000000:
                    self.speak_reply(character, result, voice, yielding)
                else:
                    self.speech.say(character, result['text'], current=yielding)
                turns += 1
        except Exception:
            logging.exception('Encounter failed')
            if current():
                self.encounter.pending = True
                self.retry_after = time.monotonic() + 5
        finally:
            self.history = locals().get('history', [])[-6:]
            if self.departing() and self.encounter.active:
                self.encounter.pending = True  # Resume without another greeting if they turn back.
            self.set_status(state='sleeping' if self.controls.sleeping else 'idle')
            self.busy.release()

    def run(self):
        import cv2
        detector = Detector()
        camera = None
        self.bridge.start()
        self.alert.start()
        self.fire.start()
        threading.Thread(target=self.watch_speaker, daemon=True).start()
        if getattr(self.speech, 'bus', None) is not None and not self.controls.sleeping:
            self.speech.bus.open()
        try:
            while not self.stop.is_set():
                doorbell_count = self.observe_doorbell(detector, time.monotonic())
                cue = self.porch_cue() if not self.busy.locked() and not self.controls.sleeping else None
                if cue and self.audio_settled():
                    threading.Thread(target=self.external_interact, args=(cue,), daemon=True).start()
                elif (self.controls.sleeping or (not self.encounter.active and not self.status.get('people', 0))) and not self.busy.locked() and time.monotonic() >= self.retry_after:
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
                    self.motion.observe([], time.monotonic(), self.encounter.generation, self.encounter.active, camera_ok=False)
                    camera.release()
                    camera = None
                    count, possible, boxes = 0, False, []
                else:
                    night = self.night_view(frame)
                    detector.count(frame, min_score=.2 if night else .3)
                    visitor_score = self.webcam_night_score if night else self.webcam_visitor_score
                    if os.environ.get('PORCH_SURVEY') == '1' and time.monotonic() - getattr(self, 'survey_logged', 0) >= .5:
                        # Mapping walk: every webcam person box as (center x, feet y, height, score).
                        self.survey_logged = time.monotonic()
                        logging.info('Survey webcam: %s', [(round((b[1] + b[3]) / 2, 3), round(b[2], 3), round(b[2] - b[0], 3),
                                                            round(b[4], 2)) for b in detector.boxes if b[4] >= .3])
                    # Street pedestrians are above this walkway boundary in the
                    # current webcam view. G4 covers the actual doorstep.
                    boxes = [box for box in detector.boxes if self.on_path(box)]
                    # On the path itself a lower score is enough: kids run in half-visible at the frame edge.
                    count, possible = person_presence(boxes, visitor_score, possible_score=.22 if night else .30)
                    self.observe_pose([p for p in getattr(detector, 'people', [])
                                       if self.on_path(p['box']) and p['box'][4] >= visitor_score])
                    # Sidewalk passers-by: feet above the walkway boundary, small but confident.
                    sidewalk = hasattr(self, 'sidewalk_frames') and any(self.webcam_sidewalk_feet <= box[2] and not self.on_path(box) and box[4] >= .5
                                   and (box[2] - box[0]) * (box[3] - box[1]) >= .003 for box in detector.boxes)
                    self.sidewalk_frames = getattr(self, 'sidewalk_frames', 0) + 1 if sidewalk else 0
                    if self.sidewalk_frames >= 3:
                        self.sidewalk_seen = time.monotonic()
                now = time.monotonic()
                with self.frame_lock:
                    self.frame = frame if ok else None
                    self.frame_time = now if ok else 0
                if possible:
                    self.webcam_seen = now
                if possible or doorbell_count:
                    self.last_seen = now
                self.expire_mode(now)
                # Overlapping views cannot be summed without double-counting visitors.
                webcam_count = count
                count = max(count, doorbell_count)
                self.set_status(people=count, webcam_people=webcam_count,
                                possible_person=bool(possible or doorbell_count))
                self.alert.update(bool(possible or doorbell_count) or now - getattr(self, 'sidewalk_seen', float('-inf')) < 2,
                                  self.bridge_pending(), not self.controls.sleeping, now)
                self.fire.update(bool(possible or doorbell_count), self.bridge_pending(), not self.controls.sleeping, now)
                if count and not self.encounter.active and self.encounter.seen_since is None:
                    self.first_detection_at = now
                if self.encounter.observe(bool(count), now, immediate=strong_person(boxes)):
                    self.retry_after = 0  # An old idle-listen failure must not delay a cached greeting.
                self.motion.observe(boxes, now, self.encounter.generation, self.encounter.active, camera_ok=ok)
                if ok and self.webcam_departure.observe([b for b in detector.boxes if b[2] >= self.webcam_sidewalk_feet],
                                                         now, self.encounter.generation, self.encounter.active):
                    if not getattr(self, 'webcam_leaving_logged', None) == self.encounter.generation:
                        self.webcam_leaving_logged = self.encounter.generation
                        logging.info('Webcam departure: visitor walking away down the path')
                if (self.encounter.active and self.departing() and not self.busy.locked() and not self.controls.sleeping
                        and self.farewell_generation != self.encounter.generation):
                    threading.Thread(target=self.say_farewell, args=(self.encounter.generation,), daemon=True).start()
                generation = self.encounter.claim() if not cue and not self.departing() and not self.busy.locked() and not self.controls.sleeping and now >= self.retry_after else None
                if generation is not None:
                    resume = self.status.get('generation') == generation
                    self.speech.detection_at = None if resume else self.first_detection_at
                    logging.info('Visitor arrival: %s person detections', count)
                    threading.Thread(target=self.interact, kwargs={'generation': generation,
                                     'resume': resume}, daemon=True).start()
                if not self.busy.locked():
                    self.set_status(state='sleeping' if self.controls.sleeping else 'idle')
                    if self.controls.sleeping and getattr(self.speech, 'bus', None) is not None and self.speech.bus.is_open:
                        self.speech.bus.close()
                time.sleep(.02 if ok else (.1 if doorbell_count else 1))
        finally:
            self.bridge.close()
            self.alert.close()
            self.fire.close()
            if getattr(self.speech, 'bus', None) is not None:
                self.speech.bus.close()
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
