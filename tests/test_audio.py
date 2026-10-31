import io
import unittest
import wave


class AudioTests(unittest.TestCase):
    def test_pi_pcm_wav_decodes_for_transcription(self):
        from faster_whisper.audio import decode_audio
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(bytes(32000))
        buffer.seek(0)
        decoded = decode_audio(buffer, sampling_rate=16000)
        self.assertEqual(len(decoded), 16000)
        self.assertEqual(float(abs(decoded).max()), 0)
