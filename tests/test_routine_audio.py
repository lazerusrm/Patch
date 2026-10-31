from array import array
from pathlib import Path
from types import SimpleNamespace
import math
import os
import tempfile
import unittest
from unittest.mock import MagicMock,patch
import wave

from routine_audio import trim_quiet_edges,split_internal_voice


class RoutineAudioTests(unittest.TestCase):
    def test_trim_removes_dead_air_but_keeps_soft_onset_and_release(self):
        quiet=array('h',[0])*4800
        soft=array('h',(int(90*math.sin(i*.3)) for i in range(1200)))
        voice=array('h',(int(12000*math.sin(i*.3)) for i in range(7200)))
        original=(quiet+soft+voice+array('h',[0])*9600).tobytes()
        trimmed=array('h',trim_quiet_edges(original))
        self.assertLess(len(trimmed),len(original)//2-8000)
        self.assertIn(soft.tobytes(),trimmed.tobytes())
        self.assertEqual(trimmed[-2400:],array('h',[0])*2400)

    def test_routed_tracks_sum_to_original_without_duplicate_voices(self):
        original=array('h',[1000])*24000
        outer,inner=split_internal_voice(original,[(0,'dobby'),(.25,'voldemort_pumpkin'),(.75,'dobby')],24000)
        self.assertEqual(inner[:6000],array('h',[0])*6000)
        self.assertEqual(outer[6000:18000],array('h',[0])*12000)
        self.assertEqual(array('h',(a+b for a,b in zip(outer,inner))),original)

    def test_usb_route_caps_hardware_volume_and_uses_two_continuous_streams(self):
        from pumpkin import Speech
        with tempfile.TemporaryDirectory(dir='/dev/shm') as directory:
            path=Path(directory)/'scene.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setparams((1,2,24000,0,'NONE','not compressed'))
                wav.writeframes((array('h',[1000])*24000).tobytes())
            with patch.dict(os.environ,{'AUDIO_OUTPUT':'bluealsa:DEV=porch','SPEAKER_BUS':'0','AUDIO_PREROLL_SECONDS':'0',
                                       'INTERNAL_AUDIO_OUTPUT':'plughw:CARD=UACDemoV10,DEV=0',
                                       'INTERNAL_AUDIO_DELAY_SECONDS':'0'}):
                speech=Speech(SimpleNamespace(level=None,character='dobby'))
            tracks={}
            def start(command,**kwargs):
                with wave.open(command[-1]) as wav:tracks[command[3]]=array('h',wav.readframes(wav.getnframes()))
                p=MagicMock();p.poll.return_value=0;p.returncode=0;p.stderr.read.return_value=b''
                return p
            with patch('pumpkin.subprocess.Popen',side_effect=start) as playback, \
                 patch('pumpkin.subprocess.run') as mixer,patch('pumpkin.time.sleep'):
                speech.play(path,'dobby',cues=[(0,'dobby'),(.5,'voldemort_pumpkin')])
            self.assertEqual(playback.call_count,2)
            self.assertEqual(mixer.call_args.args[0][-1],'90%')
            self.assertEqual(tracks['bluealsa:DEV=porch'][12000:],array('h',[0])*12000)
            self.assertEqual(tracks['plughw:CARD=UACDemoV10,DEV=0'][:12000],array('h',[0])*12000)
