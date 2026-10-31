"""Whitelisted speaker and sleep controls; no account/model tools involved."""
import json
import logging
import os
from pathlib import Path
import re
import subprocess
from core import SPECIAL_CHARACTERS

WAKE_LINE = 'Boo! Awake, accounted for, and mostly hollow. What mischief shall we get up to?'
LOUDER_LINE = 'A little more thunder.'
QUIETER_LINE = 'A smaller helping of spooky. There we go.'
CONTROL_LINES = (WAKE_LINE, LOUDER_LINE, QUIETER_LINE)
MAX_VOLUME = 90  # Speaker USB reset observed at 95%; retain the confirmed 90% test ceiling.
MIN_VOLUME = 50


class Controls:
    def __init__(self, path):
        self.path = Path(path)
        self.sleeping = False
        self.mode = 'normal'
        self.volume = None
        self.mixer = os.environ.get('AUDIO_MIXER', 'hw:CARD=UACDemoV10')
        self.control = os.environ.get('AUDIO_VOLUME_CONTROL', 'PCM')
        self.max_volume = 100 if self.mixer.split(':', 1)[0] == 'bluealsa' else MAX_VOLUME
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict):
                raise ValueError('Invalid controls state')
            self.sleeping = data.get('sleeping') is True
            self.mode = data.get('mode') if data.get('mode') in SPECIAL_CHARACTERS else 'normal'
            volume = data.get('volume')
            if type(volume) is int and 0 <= volume <= 100:
                self.volume = volume
        except FileNotFoundError:
            pass
        except (ValueError, OSError):
            logging.warning('Ignoring invalid saved controls state')
        self.speaker_connected = False
        try:
            if self.volume is not None:
                self.set_volume(self.volume)
            else:
                self.set_volume(100 if self.max_volume == 100 else self.read_volume())
            self.speaker_connected = True
        except (subprocess.SubprocessError, OSError, ValueError):
            # Speaker not connected yet (e.g. right after a reboot): start anyway, keep the saved level.
            logging.warning('Speaker volume unavailable at startup; keeping saved level')
            if self.volume is None:
                self.volume = 100 if self.max_volume == 100 else MAX_VOLUME

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'volume': self.volume, 'sleeping': self.sleeping, 'mode': self.mode}))
        temporary.replace(self.path)

    def set_volume(self, value):
        value = max(MIN_VOLUME, min(self.max_volume, int(value)))
        subprocess.run(['amixer', '-D', self.mixer, 'sset', self.control, str(value) + '%'],
                       check=True, capture_output=True, text=True, timeout=3)
        self.volume = value
        self.save()
        return value

    def sync_speaker(self):
        """Re-apply the saved volume only when the speaker (re)connects, so the physical knob stays in charge."""
        try:
            self.read_volume()
        except (subprocess.SubprocessError, OSError, RuntimeError):
            self.speaker_connected = False
            return False
        if not self.speaker_connected:
            try:
                self.set_volume(self.volume if self.volume is not None else self.max_volume)
                logging.info('Speaker connected; volume restored to %d%%', self.volume)
            except (subprocess.SubprocessError, OSError, ValueError):
                return False
            self.speaker_connected = True
        return True

    def read_volume(self):
        result = subprocess.run(['amixer', '-D', self.mixer, 'sget', self.control],
                                check=True, capture_output=True, text=True, timeout=3)
        match = re.search(r'\[(\d+)%\]', result.stdout)
        if not match:
            raise RuntimeError('Cannot read speaker volume')
        return int(match.group(1))

    def adjust(self, delta):
        return self.set_volume(self.read_volume() + delta)

    def set_sleep(self, sleeping):
        self.sleeping = sleeping
        self.save()

    def set_mode(self, mode):
        if mode not in ('normal', *SPECIAL_CHARACTERS):
            raise ValueError('Unknown character mode')
        self.mode = mode
        self.save()
