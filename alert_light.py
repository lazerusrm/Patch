"""Indoor WiZ bulb that shows what is happening out front, separate from the porch show.

Pumpkin running: steady bright green. Someone on the path, porch or sidewalk: a smooth
green -> orange -> green fade (WIZ_ALERT_CYCLE_SECONDS per half). Doorbell press: a short
blue/white strobe, then back to the fade. The fade stops WIZ_ALERT_CLEAR_SECONDS after everyone has
gone. When the pumpkin sleeps or stops, the bulb returns to exactly what it was doing before.
"""
import json
import logging
import math
import os
import socket
import threading
import time

PORT = 38899
GREEN = (0, 255, 40)
ORANGE = (255, 90, 0)
RESTORE_KEYS = ('state', 'r', 'g', 'b', 'c', 'w', 'temp', 'dimming', 'sceneId', 'speed')


def restore_params(pilot):
    """setPilot params that put a bulb back to a getPilot result."""
    if not pilot or not pilot.get('state', True):
        return {'state': False}
    params = {k: pilot[k] for k in RESTORE_KEYS if k in pilot}
    if params.get('sceneId') == 0:
        params.pop('sceneId')
    if 'sceneId' in params:  # A scene carries its own colours.
        params = {k: v for k, v in params.items() if k in ('state', 'sceneId', 'speed', 'dimming')}
    return params


def color(rgb, dimming=100):
    return {'state': True, 'r': int(rgb[0]), 'g': int(rgb[1]), 'b': int(rgb[2]), 'dimming': dimming}


class AlertLight:
    def __init__(self, macs=None, clear_seconds=None, cycle_seconds=None, sender=None):
        raw = os.environ.get('WIZ_ALERT_LIGHTS', '') if macs is None else macs
        self.macs = {m.strip().lower().replace(':', '') for m in raw.split(',') if m.strip()}
        self.clear_seconds = float(os.environ.get('WIZ_ALERT_CLEAR_SECONDS', '20') if clear_seconds is None else clear_seconds)
        self.cycle_seconds = float(os.environ.get('WIZ_ALERT_CYCLE_SECONDS', '3') if cycle_seconds is None else cycle_seconds)
        self.known = {}            # mac -> ip
        self.saved = {}            # ip -> getPilot result from before the pumpkin took the bulb over
        self.awake = False
        self.visitor_since = None  # monotonic start of the current visitor fade
        self.last_present = float('-inf')
        self.ring_until = float('-inf')
        self.last_ring = float('-inf')
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.sender = sender
        self.thread = None
        self.label = 'Indoor alert'

    @property
    def enabled(self):
        return bool(self.macs)

    def start(self):
        if self.enabled:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=5)

    # Called from the detection loop every frame: cheap and non-blocking.
    def update(self, present, ring, awake=True, now=None):
        if not self.enabled:
            return
        now = time.monotonic() if now is None else now
        with self.lock:
            self.awake = awake
            if present or ring:
                self.last_present = now
                if self.visitor_since is None:
                    self.visitor_since = now
                    logging.info('Indoor alert: someone out front')
            elif self.visitor_since is not None and now - self.last_present >= self.clear_seconds:
                self.visitor_since = None
                logging.info('Indoor alert: porch clear')
            if ring and now - self.last_ring > 10:
                self.last_ring = now
                self.ring_until = now + 2
                logging.info('Indoor alert: doorbell ring')

    def target(self, now):
        """What the bulb should show right now, or None to hand it back to the household."""
        with self.lock:
            if not self.awake:
                return None
            if now < self.ring_until:
                return color((0, 60, 255)) if int((now - self.ring_until) * 5) % 2 == 0 else {'state': True, 'temp': 6500, 'dimming': 100}
            if self.visitor_since is None:
                return color(GREEN)
            phase = (now - self.visitor_since) / (2 * self.cycle_seconds)
            mix = .5 - .5 * math.cos(2 * math.pi * phase)  # 0 green -> 1 orange -> 0 green, eased
            return color(tuple(g + (o - g) * mix for g, o in zip(GREEN, ORANGE)))

    # Bulb I/O on its own thread --------------------------------------------------------
    def _discover(self, sock):
        targets = ['255.255.255.255', os.environ.get('WIZ_BROADCAST', '192.168.0.255')]
        deadline = time.monotonic() + 2
        asked = 0
        while time.monotonic() < deadline and self.macs - set(self.known):
            if time.monotonic() >= asked:
                asked = time.monotonic() + .7
                for target in targets:
                    try:
                        sock.sendto(b'{"method":"getSystemConfig","params":{}}', (target, PORT))
                    except OSError:
                        pass
            try:
                data, (ip, _) = sock.recvfrom(2048)
                mac = json.loads(data).get('result', {}).get('mac', '')
            except (OSError, ValueError, AttributeError):
                continue
            if mac in self.macs and self.known.get(mac) != ip:
                self.known[mac] = ip
                logging.info('%s bulb found: %s at %s', self.label, mac, ip)

    def _ask(self, sock, ip, method, params, tries=3):
        message = json.dumps({'method': method, 'params': params}).encode()
        for _ in range(tries):
            try:
                sock.sendto(message, (ip, PORT))
                while True:
                    data, (source, _) = sock.recvfrom(2048)
                    if source == ip:
                        return json.loads(data).get('result')
            except (OSError, ValueError):
                continue
        return None

    def _push(self, sock, params):
        message = json.dumps({'method': 'setPilot', 'params': params}).encode()
        for ip in self.known.values():
            if self.sender is not None:
                self.sender(ip, params)
                continue
            try:
                sock.sendto(message, (ip, PORT))  # Fire and forget: the fade sends ~10 per second.
            except OSError:
                pass

    def _hand_back(self, sock):
        for ip, pilot in list(self.saved.items()):
            self._ask(sock, ip, 'setPilot', restore_params(pilot), tries=3)
        if self.saved:
            logging.info('%s: household light setting restored', self.label)
        self.saved.clear()

    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(.3)
        searched, last, sent_at = float('-inf'), None, 0.0
        try:
            while not self.stop.is_set():
                now = time.monotonic()
                if now - searched > (300 if self.macs <= set(self.known) else 15):
                    self._discover(sock)
                    searched = time.monotonic()
                params = self.target(now)
                if params is None:
                    if self.saved:
                        self._hand_back(sock)
                        last = None
                    self.stop.wait(.5)
                    continue
                for ip in self.known.values():
                    if ip not in self.saved:  # Remember the household setting before taking over.
                        self.saved[ip] = self._ask(sock, ip, 'getPilot', {}) or {'state': True, 'temp': 2700, 'dimming': 100}
                if params != last or now - sent_at > 5:
                    self._push(sock, params)
                    last, sent_at = params, now
                sock.settimeout(0)
                try:
                    while True:
                        sock.recvfrom(1024)  # Discard setPilot replies without waiting.
                except OSError:
                    pass
                finally:
                    sock.settimeout(.3)
                self.stop.wait(.1)
        except Exception:
            logging.exception('Indoor alert light failed')
        finally:
            try:
                self._hand_back(sock)
            finally:
                sock.close()
