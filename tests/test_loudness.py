import io
import json
import math
import os
from array import array
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from pumpkin import Speech


class LoudnessTests(unittest.TestCase):
    def test_character_boost_adds_three_db_without_exceeding_peak_ceiling(self):
        from loudness import normalize_wav
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            directory=Path(directory)
            source=directory/'source.wav'
            samples=array('h',(int(12000*math.sin(i*2*math.pi*220/24000)) for i in range(24000*3)))
            with wave.open(str(source),'wb') as wav:
                wav.setparams((1,2,24000,0,'NONE','not compressed'));wav.writeframes(samples.tobytes())
            levels=[]
            for boost in (0,3):
                target=directory/f'boost-{boost}.wav'
                normalize_wav(source,target,boost_db=boost)
                with wave.open(str(target)) as wav:output=array('h',wav.readframes(wav.getnframes()))
                self.assertLessEqual(max(abs(x) for x in output),16426)
                levels.append(math.sqrt(sum(float(x)**2 for x in output)/len(output)))
            self.assertAlmostEqual(20*math.log10(levels[1]/levels[0]),3,delta=.1)

    def test_different_voice_dynamics_have_loudness_within_one_lu_and_safe_peaks(self):
        levels = []
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            directory = Path(directory)
            token = directory / 'token'
            token.write_text('test-only')
            speech = Speech(SimpleNamespace())
            speech.cache = directory
            for dynamic in (False, True):
                samples = array('h', (int(24000 * math.sin(i * 2 * math.pi * 220 / 24000)
                    * (1 if not dynamic or i % 24000 < 1200 else .1)) for i in range(24000 * 5)))
                source = io.BytesIO()
                with wave.open(source, 'wb') as wav:
                    wav.setparams((1, 2, 24000, 0, 'NONE', ''))
                    wav.writeframes(samples.tobytes())
                response = SimpleNamespace(content=source.getvalue(),
                    headers={'X-Voice-Model': 'breeze-tts-2'}, raise_for_status=lambda: None)
                with patch.dict(os.environ, {'PUMPKIN_TOKEN_FILE': str(token)}), \
                     patch('pumpkin.requests.post', return_value=response):
                    path = speech.render('patch', 'Boo, a loudness calibration ' + str(dynamic))
                try:
                    with wave.open(str(path)) as wav:
                        output = array('h', wav.readframes(wav.getnframes()))
                        self.assertEqual(wav.getframerate(), 24000)
                    self.assertLessEqual(max(abs(x) for x in output), 16426)
                    result = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(path), '-af',
                        'loudnorm=print_format=json', '-f', 'null', '-'], capture_output=True, check=True)
                    stats, _ = json.JSONDecoder().raw_decode('{' + result.stderr.decode().rsplit('{', 1)[1])
                    levels.append(float(stats['input_i']))
                finally:
                    path.unlink(missing_ok=True)
        self.assertLess(abs(levels[0] - levels[1]), 1, levels)
        for level in levels:
            self.assertLess(abs(level + 20), 1, levels)
