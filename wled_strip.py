"""ESP32 WLED light strip that joins the porch show (WLED_HOST, local Wi-Fi, no cloud).

Speech, doorbell lines, dragon effects and scene cues (blackout, lightning, fire, houses...)
stream to the strip as WLED realtime UDP frames (DNRGB, port 21324): the whole strip glows in the
speaking character's colour and swells with the voice, and cues use the whole strip. Between those
moments no frames are sent, so WLED falls back by itself to its own idle effect (a fire by
default, or WLED_IDLE_PRESET). The strip sits in front of the porch, so it also works as a white
work light while the cameras look at a visitor (Lights.work_light). Sleep turns the strip off. When the pumpkin stops, the strip
goes back to exactly what it was doing before. WLED's own brightness and power limit still apply.
"""
from collections import deque
import json
import logging
import os
import random
import socket
import threading
import time
import urllib.request

PORT = 21324
CHUNK = 489  # LEDs per DNRGB packet.
FPS = 25
TIMEOUT = 2  # Seconds WLED keeps the last frame before returning to its own effect.
# Candle Multi: every LED its own candle. Measured on the 290-LED strip at brightness 128:
# ~1.8 A, against ~0.14 A for Fire 2012 and Fire Flicker, which leave most of it dark.
IDLE_FIRE = {'on': True, 'seg': [{'id': 0, 'fx': 102, 'sx': 110, 'ix': 160, 'pal': 0,
                                  'col': [[255, 80, 0], [0, 0, 0], [0, 0, 0]], 'on': True}]}
WHITE = (255, 255, 255)
SPEECH_FLOOR, SPEECH_CURVE = .06, 1.8  # Strip brightness = floor + rest * level**curve.
CHECK_SECONDS = 30  # While idle, look in on WLED this often: a reboot loses the idle effect.
SEG_KEYS = ('id', 'start', 'stop', 'on', 'bri', 'col', 'fx', 'sx', 'ix', 'pal', 'c1', 'c2', 'c3', 'frz')


def scale(rgb, level):
    level = max(0.0, min(1.0, level))
    return tuple(int(v * level) for v in rgb)


def strip_frame(lights, now, count, colors, houses, rng=random):
    """Per-LED colours from the pumpkin's light state, or None to leave the strip to WLED."""
    from_cue = [accent for accent in getattr(lights, 'accents', ()) if accent[0] <= now < accent[1]]
    if lights.sleeping or count <= 0:
        return None
    if getattr(lights, 'work_until', 0) > now:  # Porch work light: white so the cameras can see.
        return [WHITE] * count
    if from_cue:
        _, _, mode, rgb = max(from_cue, key=lambda accent: accent[0])  # The newest cue wins.
        if mode == 'off':
            return [(0, 0, 0)] * count
        if mode == 'cycle':  # Four house bands marching along the strip.
            bands = list(houses.values())
            shift = int(now * 3)
            return [bands[(i * len(bands) // count + shift) % len(bands)] for i in range(count)]
        if mode == 'flicker':  # The whole strip flickers together, with a little shimmer.
            gust = rng.uniform(.55, 1)
            return [scale(rgb, gust * rng.uniform(.85, 1)) for _ in range(count)]
        if mode == 'strobe':
            return [scale(rgb, 1 if int(now * 8) % 2 == 0 else .05)] * count
        if mode == 'blink':
            return [scale(rgb, 1 if int(now * 1.5) % 2 == 0 else .05)] * count
        return [tuple(rgb)] * count
    if lights.level is None:
        return None
    rgb = colors.get(lights.character, colors['patch'])
    level = max(0.0, min(1.0, lights.level))
    if lights.character == 'trogdor':
        level *= rng.uniform(.6, 1)  # Burninating flicker.
    # Every LED lit; the whole strip pulses hard with the voice: near-dark between syllables, full on
    # peaks. The curve keeps quiet sounds dim so loud ones stand out (owner: more accentuated).
    return [scale(rgb, SPEECH_FLOOR + (1 - SPEECH_FLOOR) * level ** SPEECH_CURVE)] * count


def packets(frame, timeout=TIMEOUT):
    """DNRGB packets: [4, timeout, start hi, start lo, r, g, b, ...]."""
    for start in range(0, len(frame), CHUNK):
        body = bytes(v for rgb in frame[start:start + CHUNK] for v in rgb)
        yield bytes((4, timeout, start >> 8, start & 255)) + body


class WledStrip:
    def __init__(self, lights, colors, houses, host=None, delay=None):
        self.lights, self.colors, self.houses = lights, colors, houses
        self.host = (os.environ.get('WLED_HOST', '') if host is None else host).strip()
        self.delay = float(os.environ.get('WLED_DELAY_SECONDS', os.environ.get('WIZ_DELAY_SECONDS', '0'))
                           if delay is None else delay)
        if not 0 <= self.delay <= 2:
            raise ValueError('WLED_DELAY_SECONDS must be 0..2')
        preset = os.environ.get('WLED_IDLE_PRESET', '').strip()
        self.idle = {'on': True, 'ps': int(preset)} if preset else IDLE_FIRE
        # WLED boots dim (its own boot brightness) so the start-up surge cannot brown it out while
        # Wi-Fi connects; once it answers here, WLED_BRIGHTNESS brings it up to full.
        brightness = os.environ.get('WLED_BRIGHTNESS', '').strip()
        if brightness:
            if not 1 <= int(brightness) <= 255:
                raise ValueError('WLED_BRIGHTNESS must be 1..255')
            self.idle = {**self.idle, 'bri': int(brightness)}
        self.count = 0
        self.saved = None
        self.base = None  # 'idle' or 'off': the state last given to WLED itself.
        self.uptime, self.checked = 0, 0.0
        self.history = deque()
        self.stop = threading.Event()
        self.thread = None

    @property
    def enabled(self):
        return bool(self.host)

    def request(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request('http://%s%s' % (self.host, path), data=data,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.loads(response.read() or b'{}')

    def connect(self):
        """Learn the LED count and remember WLED's own state to restore later."""
        info = self.request('/json/info')
        self.count = int(info['leds']['count'])
        self.uptime, self.checked = int(info.get('uptime', 0)), time.monotonic()
        if self.saved is None:
            state = self.request('/json/state')
            self.saved = {'on': state.get('on', True), 'bri': state.get('bri', 128),
                          'seg': [{k: seg[k] for k in SEG_KEYS if k in seg} for seg in state.get('seg', [])]}
        logging.info('WLED strip %s: %d LEDs (%s)', self.host, self.count, info.get('name', 'WLED'))

    def delayed(self, now):
        """The frame from WLED_DELAY_SECONDS ago, so the strip lands with the speakers."""
        frame = strip_frame(self.lights, now, self.count, self.colors, self.houses)
        if not self.delay:
            return frame
        self.history.append((now, frame))
        while len(self.history) > 1 and self.history[1][0] <= now - self.delay:
            self.history.popleft()
        return self.history[0][1]

    def start(self):
        if self.enabled and self.thread is None:
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        retry = 0.0
        while not self.stop.is_set():
            now = time.monotonic()
            try:
                if not self.count:
                    if now < retry:
                        self.stop.wait(1)
                        continue
                    self.connect()
                frame = self.delayed(now)
                if frame is None and now - self.checked > CHECK_SECONDS:
                    uptime = int(self.request('/json/info').get('uptime', 0))
                    if uptime < self.uptime:
                        logging.info('WLED strip %s restarted; setting it up again', self.host)
                        self.base = None
                    self.uptime, self.checked = uptime, now
                # WLED's own state underneath: the idle effect while awake (live frames need the
                # strip on, and it returns there after TIMEOUT), off while asleep.
                want = 'off' if frame is None and self.lights.sleeping else 'idle'
                if self.base != want:
                    self.request('/json/state', {'on': False} if want == 'off' else self.idle)
                    self.base = want
                for packet in packets(frame or ()):
                    sock.sendto(packet, (self.host, PORT))
            except (OSError, ValueError, KeyError) as error:
                if self.count or retry == 0:
                    logging.warning('WLED strip %s unreachable (%s); retrying in 30 s', self.host, error)
                self.count, self.base, retry = 0, None, now + 30
            self.stop.wait(max(0.0, 1 / FPS - (time.monotonic() - now)))
        sock.close()

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        if self.saved is not None:
            try:
                self.request('/json/state', {**self.saved, 'live': False})
            except (OSError, ValueError):
                logging.warning('Could not restore WLED strip %s', self.host)
