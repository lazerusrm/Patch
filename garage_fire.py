"""Garage WiZ bulbs as fire, driven from here so every bulb burns in sync.

One flame model, sent to all the bulbs about 8 times a second: an irregular flicker that chases
random targets, sudden gust dips, deep red embers when low and yellow tips when high. It burns
calm when nobody is around, livelier while someone is out front, and blazes on arrival, doorbell
presses and Trogdor. Restored to the household setting when the pumpkin sleeps or stops.
Packets lost on weak Wi-Fi do not matter: the next frame follows 120 ms later.
"""
import logging
import os
import random
import socket
import time

from alert_light import AlertLight

# (mean level, spread, flicker speed) for each mood.
MOODS = {'calm': (.55, .35, 1.0), 'roused': (.75, .3, 1.5), 'blaze': (.95, .15, 2.5)}


def flame_color(level):
    """Deep red embers when low, orange body, a touch of yellow at the tips."""
    level = max(0.0, min(1.0, level))
    return {'state': True, 'r': 255, 'g': int(22 + 120 * level ** 1.4), 'b': 0,
            'dimming': max(10, min(100, int(12 + 88 * level)))}


class FireLights(AlertLight):
    def __init__(self, macs=None, sender=None, rng=None):
        super().__init__(macs=os.environ.get('WIZ_FIRE_LIGHTS', '') if macs is None else macs, sender=sender)
        self.label = 'Garage fire'
        self.flare_until = float('-inf')
        self.frame_seconds = float(os.environ.get('WIZ_FIRE_FRAME_SECONDS', '.12'))
        self.rng = rng or random.Random()
        self.level = self.goal = .5
        self.next_goal = 0.0
        self.flame_at = None
        self.mood_logged = None

    def update(self, present=False, ring=False, awake=True, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            self.awake = awake
            if present or ring:
                if self.visitor_since is None:  # Arrival: the fire jumps up.
                    self.visitor_since = now
                    self.flare_until = max(self.flare_until, now + 4)
                self.last_present = now
            elif self.visitor_since is not None and now - self.last_present >= self.clear_seconds:
                self.visitor_since = None
            if ring and now - self.last_ring > 10:
                self.last_ring = now
                self.flare_until = max(self.flare_until, now + 3)

    def flare(self, seconds, now=None):
        """Trogdor: burninate the garage for a moment."""
        if self.enabled:
            with self.lock:
                self.flare_until = max(self.flare_until, (time.monotonic() if now is None else now) + seconds)

    def mood(self, now):
        with self.lock:
            if not self.awake:
                return None
            return 'blaze' if now < self.flare_until else 'roused' if self.visitor_since is not None else 'calm'

    def target(self, now):
        mood = self.mood(now)
        if mood is None:
            return None
        mean, spread, speed = MOODS[mood]
        dt = 0.0 if self.flame_at is None else min(.5, now - self.flame_at)
        self.flame_at = now
        if now >= self.next_goal:
            # A new flicker target around the mood's level; now and then a gust knocks the flame down.
            self.goal = mean + spread * (self.rng.random() * 2 - 1)
            if self.rng.random() < .06 * speed:
                self.goal = mean - spread * 1.6
            self.next_goal = now + self.rng.uniform(.08, .4) / speed
        self.level += (self.goal - self.level) * min(1.0, dt * 9 * speed)
        return flame_color(self.level)

    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(.3)
        searched = float('-inf')
        try:
            while not self.stop.is_set():
                now = time.monotonic()
                if now - searched > (300 if self.macs <= set(self.known) else 15):
                    self._discover(sock)
                    searched = time.monotonic()
                mood = self.mood(now)
                if mood != self.mood_logged:
                    logging.info('Garage fire: %s', mood or 'handed back')
                    self.mood_logged = mood
                params = self.target(now)
                if params is None:
                    if self.saved:
                        self._hand_back(sock)
                    self.stop.wait(.5)
                    continue
                for ip in self.known.values():
                    if ip not in self.saved:
                        self.saved[ip] = self._ask(sock, ip, 'getPilot', {}) or {'state': True, 'temp': 2700, 'dimming': 100}
                self._push(sock, params)  # The same frame to every bulb at once: they burn in sync.
                sock.settimeout(0)
                try:
                    while True:
                        sock.recvfrom(1024)
                except OSError:
                    pass
                finally:
                    sock.settimeout(.3)
                self.stop.wait(max(0.0, self.frame_seconds - (time.monotonic() - now)))
        except Exception:
            logging.exception('Garage fire lights failed')
        finally:
            try:
                self._hand_back(sock)
            finally:
                sock.close()
