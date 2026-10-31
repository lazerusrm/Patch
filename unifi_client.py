"""Bounded client for the local Protect bridge; never owns character dialogue."""
from array import array
from collections import deque
from contextlib import contextmanager
import base64
from datetime import datetime, timezone
import io
import logging
import math
import os
import subprocess
from pathlib import Path
import threading
import time
from urllib.parse import quote
import uuid
import wave

import requests


def doorbell_lead(seconds, amplitude, rate=24000):
    """Lead-in PCM16: silence, or a faint 180 Hz tone that keeps the talkback stream open."""
    frames = round(seconds * rate)
    if not amplitude:
        return bytes(frames * 2)
    return array('h', (int(amplitude * math.sin(2 * math.pi * 180 * i / rate))
                       for i in range(frames))).tobytes()


class UniFiBridge:
    def __init__(self):
        self.url = os.environ.get('PUMPKIN_UNIFI_URL', 'http://127.0.0.1:8768').rstrip('/')
        path = os.environ.get('PUMPKIN_UNIFI_TOKEN_FILE')
        try:
            self.token = Path(path).read_text().strip() if path else ''
        except OSError:
            self.token = ''
        self.enabled = bool(self.token)
        self.health = {}
        self.events = deque(maxlen=8)
        self.seen = deque(maxlen=128)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = None
        self.camera_thread = None
        self.camera_frame = None  # Immutable (monotonic capture time, BGR frame).
        self.last_camera_fetch = float('-inf')
        self.audio_requests = 0
        self.presence_until = 0
        self.last_ring = float('-inf')
        self.press_times = deque(maxlen=20)  # Every counted press, for 'rang twice / three times'.
        self.ring_debounce = float(os.environ.get('RING_DEBOUNCE_SECONDS', '2'))
        self.quiet_until = 0
        self.lead_seconds = float(os.environ.get('DOORBELL_LEAD_IN_SECONDS', '.25'))
        self.lead_amplitude = int(os.environ.get('DOORBELL_LEAD_AMPLITUDE', '0'))
        if not 0 <= self.lead_seconds <= 2 or not 0 <= self.lead_amplitude <= 1000:
            raise ValueError('Doorbell lead-in must be 0..2 s at amplitude 0..1000')

    def request(self, method, path, **kwargs):
        response = requests.request(method, self.url + path,
            headers={'Authorization': 'Bearer ' + self.token, **kwargs.pop('headers', {})},
            timeout=(1, 3), **kwargs)
        response.raise_for_status()
        return response

    def start(self):
        if self.enabled:
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
            self.camera_thread = threading.Thread(target=self.watch_camera, daemon=True)
            self.camera_thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        if self.camera_thread:
            self.camera_thread.join(timeout=5)

    def available(self, target):
        caps = self.health.get('capabilities', {})
        return bool(self.health.get('ready') and
                    caps.get('audio' if target == 'doorbell' else 'chime_audio'))

    def pending(self):
        with self.lock:
            return any(time.monotonic() - event['_received'] < 15 for event in self.events)

    def drain(self, keep=0):
        """Drop queued presses except the newest `keep` (all still count in press_times); returns how many were queued."""
        with self.lock:
            count = len(self.events)
            while len(self.events) > keep:
                self.events.popleft()
        return count

    def take(self):
        with self.lock:
            while self.events:
                event = self.events.popleft()
                if time.monotonic() - event['_received'] < 15:
                    return event
        return None

    def ingest(self, events):
        if not isinstance(events, list):
            return
        for event in events[:32]:
            if not isinstance(event, dict):
                continue
            event_id = event.get('id')
            if not isinstance(event_id, str) or not event_id or len(event_id) > 200:
                continue
            try:
                stamp = datetime.fromisoformat(event['occurred_at'].replace('Z', '+00:00'))
                if stamp.tzinfo is None:
                    continue
                age = (datetime.now(timezone.utc) - stamp).total_seconds()
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
            if not -5 <= age < 15 or event_id in self.seen:
                continue
            self.seen.append(event_id)
            now = time.monotonic()
            if event.get('type') in ('person.detected', 'doorbell.ring'):
                self.presence_until = now + 8
            if event.get('type') == 'doorbell.ring':
                if now - self.last_ring < self.ring_debounce:
                    logging.info('Doorbell ring: repeat press within %.0fs ignored', self.ring_debounce)
                    continue
                self.last_ring = now
                self.press_times.append(now)
                logging.info('Doorbell ring received (%.2fs after the press)', max(0, age))
                with self.lock:
                    self.events.append({**event, '_received': now})

    def run(self):
        cursor = None
        instance = None
        while not self.stop.is_set():
            try:
                health = self.request('GET', '/health').json()
                if not isinstance(health, dict) or not health.get('ready'):
                    raise ValueError('Bridge unavailable')
                self.health = health
                if health.get('instance_id') != instance:
                    cursor = None
                    instance = health.get('instance_id')
                    with self.lock:
                        self.events.clear()
                batch = self.request('GET', '/events', params={'after': cursor or 'latest'}).json()
                next_cursor = batch.get('cursor')
                if not isinstance(next_cursor, str) or len(next_cursor) > 200:
                    raise ValueError('Invalid bridge cursor')
                if cursor is not None and not batch.get('reset'):
                    self.ingest(batch.get('events', []))
                cursor = None if batch.get('reset') else next_cursor
            except (requests.RequestException, ValueError, TypeError, AttributeError):
                self.health = {}
                cursor = None  # Reconnect at the tail; never replay an old performance.
                with self.lock:
                    self.events.clear()
                self.stop.wait(3)
            self.stop.wait(.5)

    def fetch_frame(self, width=640):
        """Fetch a timestamp-checked frame; only the camera worker polls this."""
        if not self.health.get('ready') or not self.health.get('capabilities', {}).get('snapshot'):
            return None
        import cv2
        import numpy as np
        try:
            response = self.request('GET', '/snapshot', params={'width': width})
            stamp = datetime.fromisoformat(response.headers['X-Captured-At'].replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc) - stamp).total_seconds() if stamp.tzinfo else 999
            if not -1 <= age <= 3:
                return None
            if len(response.content) > 5000000:
                return None
            frame = cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                return None
            return time.monotonic() - max(0, age), frame
        except (requests.RequestException, ValueError, KeyError, cv2.error):
            return None

    def watch_camera(self):
        while not self.stop.is_set():
            with self.lock:
                paused = self.audio_requests > 0
            if paused and time.monotonic() - self.last_camera_fetch < 2:
                self.stop.wait(.1)
                continue
            started = time.monotonic()
            self.last_camera_fetch = started
            self.camera_frame = self.fetch_frame(width=320 if paused else 640)
            self.stop.wait(max(.05, 1 - (time.monotonic() - started)))

    @contextmanager
    def audio_priority(self):
        # Keep small presence frames alive while giving audio most of the radio.
        with self.lock:
            self.audio_requests += 1
        try:
            yield
        finally:
            with self.lock:
                self.audio_requests -= 1

    def latest_frame(self):
        result = self.camera_frame
        return result if result is not None and 0 <= time.monotonic() - result[0] <= 3 else None

    def snapshot(self):
        """Encode the shared fresh frame without issuing another camera request."""
        import cv2
        result = self.latest_frame()
        if result is None:
            return ''
        _, frame = result
        try:
            height, width = frame.shape[:2]
            scale = min(1, 1280 / max(width, height))
            frame = cv2.resize(frame, (round(width * scale), round(height * scale)))
            for quality in (70, 45, 25):
                ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
                if ok and len(encoded) <= 375000:
                    return base64.b64encode(encoded).decode()
        except (ValueError, cv2.error):
            return ''
        return ''

    def play(self, target, path, current):
        if not self.available(target) or not current():
            return False
        raw = Path(path).read_bytes()
        with wave.open(io.BytesIO(raw)) as audio:
            duration = audio.getnframes() / audio.getframerate()
            if ((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 24000)
                    or audio.getcomptype() != 'NONE' or not 0 < duration <= 20 or len(raw) > 1000000):
                raise ValueError('Doorbell audio must be bounded mono PCM16 at24kHz')
            if target == 'doorbell':
                # Let the speaker open before speech and drain before RTP closes. A faint tone
                # (not digital silence, which the codec path can gate) carries the opening.
                samples = (doorbell_lead(self.lead_seconds, self.lead_amplitude)
                           + audio.readframes(audio.getnframes()) + bytes(14400))  # 0.3 s drain
                duration = len(samples) / 48000
                if duration > 20:
                    raise ValueError('Doorbell clip plus playback silence exceeds20seconds')
                padded = io.BytesIO()
                with wave.open(padded, 'wb') as output:
                    output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                    output.writeframes(samples)
                raw = padded.getvalue()
        content_type = 'audio/wav'
        if self.health.get('capabilities', {}).get('audio_compact'):
            try:
                raw = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', 'pipe:0',
                    '-ac', '1', '-c:a', 'libopus', '-b:a', '64k', '-application', 'audio',
                    '-f', 'ogg', 'pipe:1'], input=raw, capture_output=True, check=True, timeout=3).stdout
                if not raw or len(raw) > 1000000:
                    return False
                content_type = 'audio/ogg'
            except (OSError, subprocess.SubprocessError):
                return False
        playback_id = uuid.uuid4().hex
        complete = False
        requested = time.time()
        self.quiet_until = time.monotonic() + duration + 8
        try:
            with self.audio_priority():
                reply = self.request('POST', '/audio', data=raw,
                    headers={'Content-Type': content_type, 'X-Target': target,
                             'X-Loudness': 'raw',  # Source clips are already normalized; avoid double compression.
                             'X-Request-ID': playback_id}).json()
            returned_id = reply.get('id')
            if not isinstance(returned_id, str) or not returned_id or len(returned_id) > 200:
                raise ValueError('Invalid playback ID')
            playback_id = returned_id
            deadline = time.monotonic() + duration + 8
            while current() and time.monotonic() < deadline:
                state = self.request('GET', '/audio/' + quote(playback_id, safe='')).json().get('state')
                if state == 'finished':
                    complete = True
                    logging.info('Cadence doorbell request=%.3f finished=%.3f dur=%.2f',
                                 requested, time.time(), duration)
                    self.quiet_until = time.monotonic() + .6
                    self.stop.wait(.05)  # RTP-send completion; the 0.3 s drain pad covers device jitter.
                    return True
                if state in ('failed', 'cancelled'):
                    return False
                if state not in ('queued', 'playing'):
                    return False
                self.stop.wait(.15)
            return False
        except (requests.RequestException, ValueError):
            return False
        finally:
            if playback_id and not complete:
                self.quiet_until = time.monotonic() + .6  # Never hold the porch quiet for a failed clip.
                try:
                    self.request('DELETE', '/audio/' + quote(playback_id, safe=''))
                except requests.RequestException:
                    pass
