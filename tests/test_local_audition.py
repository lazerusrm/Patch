from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

import audition_local


class LocalAuditionTests(unittest.TestCase):
    def test_active_audacity_capture_blocks_playback(self):
        import json
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            directory = Path(directory)
            with wave.open(str(directory / 'sample.wav'), 'wb') as audio:
                audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                audio.writeframes(bytes(480))
            def run(command, **kwargs):
                if command[0] != 'pactl':
                    self.fail('Audio must not start while Audacity captures playback')
                data = ('desktop-sink\n' if command[-1] == 'get-default-sink' else
                        json.dumps([{'properties': {'application.name': 'PipeWire ALSA [audacity.bin]'}}]))
                return subprocess.CompletedProcess(command, 0, data)
            with patch.object(audition_local, 'CLIPS', directory), \
                 patch.object(audition_local, 'GROUPS', {'dobby': [('A', 'sample')]}), \
                 patch('sys.argv', ['audition_local.py', 'dobby']), \
                 patch.object(audition_local.subprocess, 'run', side_effect=run):
                with self.assertRaisesRegex(SystemExit, 'recording or monitoring'):
                    audition_local.main()

    def test_invalid_clip_stops_before_any_audio_is_played(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            directory = Path(directory)
            for name, channels in [('first', 1), ('second', 2)]:
                with wave.open(str(directory / (name + '.wav')), 'wb') as audio:
                    audio.setparams((channels, 2, 24000, 0, 'NONE', 'not compressed'))
                    audio.writeframes(bytes(480 * channels))
            calls = []
            def run(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, 'desktop-sink\n')
            with patch.object(audition_local, 'CLIPS', directory), \
                 patch.object(audition_local, 'GROUPS', {'dobby': [('A', 'first'), ('B', 'second')]}), \
                 patch('sys.argv', ['audition_local.py', 'dobby']), \
                 patch.object(audition_local.subprocess, 'run', side_effect=run):
                with self.assertRaises(ValueError):
                    audition_local.main()
            self.assertTrue(all(command[0] == 'pactl' for command in calls))
