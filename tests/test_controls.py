import unittest
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class ControlTests(unittest.TestCase):
    def test_volume_is_clamped_and_sleep_survives_restart(self):
        from controls import Controls
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            path = Path(directory) / 'controls.json'
            with patch('controls.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'Playback [95%]')):
                c = Controls(path)
                self.assertEqual(c.adjust(10), 90)
                self.assertEqual(c.adjust(-200), 50)
                c.set_sleep(True)
                saved = json.loads(path.read_text())
                self.assertEqual(saved, {'volume': 50, 'sleeping': True, 'mode': 'normal'})
                restored = Controls(path)
                self.assertTrue(restored.sleeping)

    def test_corrupt_saved_state_does_not_stop_startup(self):
        from controls import Controls
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            path = Path(directory) / 'controls.json'
            path.write_text('broken')
            with patch('controls.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'Playback [95%]')):
                c = Controls(path)
            self.assertFalse(c.sleeping)
            self.assertEqual(c.volume, 90)

    def test_bluetooth_defaults_to_full_output_and_remembers_adjustments(self):
        import os
        from controls import Controls
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            path = Path(directory) / 'controls.json'
            with patch.dict(os.environ, {'AUDIO_MIXER': 'bluealsa'}), \
                 patch('controls.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'Playback [100%]')):
                control = Controls(path)
                self.assertEqual(control.volume, 100)
                self.assertEqual(control.adjust(10), 100)
                self.assertEqual(Controls(path).volume, 100)
                control.set_volume(80)
                self.assertEqual(Controls(path).volume, 80)


class StartupWithoutSpeakerTests(unittest.TestCase):
    def test_controls_start_when_the_speaker_is_not_connected(self):
        import json, subprocess, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from controls import Controls
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'controls.json'
            path.write_text(json.dumps({'volume': 80, 'sleeping': False, 'mode': 'normal'}))
            failure = subprocess.CalledProcessError(1, ['amixer'])
            with patch('controls.subprocess.run', side_effect=failure), \
                 patch.dict('os.environ', {'AUDIO_MIXER': 'bluealsa'}):
                controls = Controls(path)
            self.assertEqual(controls.volume, 80)

    def test_volume_is_restored_once_when_the_speaker_reconnects(self):
        import json, subprocess, tempfile
        from pathlib import Path
        from unittest.mock import patch, MagicMock
        from controls import Controls
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'controls.json'
            path.write_text(json.dumps({'volume': 80, 'sleeping': False, 'mode': 'normal'}))
            down = subprocess.CalledProcessError(1, ['amixer'])
            with patch('controls.subprocess.run', side_effect=down), patch.dict('os.environ', {'AUDIO_MIXER': 'bluealsa'}):
                controls = Controls(path)
                self.assertFalse(controls.sync_speaker())
            calls = []
            def amixer(args, **kwargs):
                calls.append(args[3])
                return MagicMock(stdout='Playback 64 [50%]')
            with patch('controls.subprocess.run', side_effect=amixer):
                self.assertTrue(controls.sync_speaker())
                self.assertTrue(controls.sync_speaker())
            self.assertEqual(calls.count('sset'), 1)  # Restored on connect only; the knob stays in charge after.
            self.assertEqual(controls.volume, 80)

