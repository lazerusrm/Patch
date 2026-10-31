"""Bounded porch audition with listening gaps and the normal voice controls."""
import logging
import math
import os
from pathlib import Path
import random
import signal
import subprocess
import time

from core import CHARACTERS, AUTO_CHARACTERS, SPECIAL_CHARACTERS
from games import CONTROL_ACTIONS, intent
from pumpkin import Pumpkin, listen


def dispatch(pumpkin, text, alive):
    action = intent(text)
    character = pumpkin.status.get('character', 'patch')
    if action in CONTROL_ACTIONS:
        pumpkin.control(action, character, current=alive,
                        announce=action == 'wake' or not pumpkin.controls.sleeping)
    elif not pumpkin.controls.sleeping and action in ('joke', 'story', 'boo', 'sort', 'routine', 'pumpkin_scene'):
        pumpkin.entertain(action, character, alive)
    elif not pumpkin.controls.sleeping and action == 'game':
        pumpkin.play_game(character, alive)
    elif not pumpkin.controls.sleeping and pumpkin.controls.mode in SPECIAL_CHARACTERS and text:
        result = pumpkin.turn(character, [], text=text)
        if result.get('text'):
            pumpkin.speech.say(character, result['text'], current=alive)
    return action


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    until = float(os.environ['PUMPKIN_AUDITION_UNTIL'])
    if not math.isfinite(until) or until - time.time() > 7200:
        raise ValueError('Audition must be bounded to at most two hours')
    if until <= time.time():
        return
    p = Pumpkin()
    alive = lambda: not p.stop.is_set() and time.time() < until
    playing = lambda: alive() and not p.controls.sleeping
    def stop(*_):
        p.stop.set()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    root = Path(__file__).resolve().parent
    monitor = subprocess.Popen(['/usr/bin/python3', str(root / 'camera_monitor.py'), str(until)])
    index = 0
    try:
        while alive():
            character = p.choose_character(AUTO_CHARACTERS[index % len(AUTO_CHARACTERS)])
            if not p.controls.sleeping:
                p.set_status(mode='audition', until=until, character=character, state='sample', title='')
                try:
                    if index % 4 == 3:
                        p.entertain('story', character, playing)
                    elif index % 2:
                        p.entertain('joke', character, playing)
                    else:
                        p.speech.say(character, random.choice(CHARACTERS[character]['greetings']), current=playing)
                    index += 1
                except Exception:
                    logging.exception('Sample failed; retaining the audition schedule')
                    time.sleep(2)
            p.set_status(state='sleeping' if p.controls.sleeping else 'listening', mode='audition')
            try:
                audio = listen(wait=6, current=alive)
                if audio and alive():
                    heard = p.turn(character, [], audio=audio, listen_only=True).get('transcript', '')
                    action = dispatch(p, heard, alive)
                    if action:
                        logging.info('Audition voice action: %s', action)
            except Exception:
                logging.exception('Audition listening failed')
                time.sleep(2)
    finally:
        p.stop.set()
        if monitor.poll() is None:
            monitor.terminate()
        try:
            monitor.wait(timeout=5)
        except subprocess.TimeoutExpired:
            monitor.kill()
            monitor.wait()
        p.lights.close()
        p.set_status(state='idle', mode='normal')


if __name__ == '__main__':
    main()
