import subprocess
import tempfile
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import wave

from idle_music import IdleMusic


def write_wav(path, channels=1, sample_width=2, sample_rate=24000, frames=24):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(sample_width)
        output.setframerate(sample_rate)
        output.writeframes(b"\0" * channels * sample_width * frames)


class ImmediateProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.terminated = False
        self.waited = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        self.waited = True
        return self.returncode


class WaitingProcess(ImmediateProcess):
    def __init__(self):
        super().__init__(returncode=None)

    def terminate(self):
        self.terminated = True
        self.returncode = -15


class IdleMusicTests(unittest.TestCase):
    def test_no_tracks_returns_false_without_starting_player(self):
        with tempfile.TemporaryDirectory() as directory:
            music = IdleMusic(directory, "default")
            with patch("idle_music.subprocess.Popen") as popen:
                self.assertFalse(music.play(lambda: True))
                popen.assert_not_called()

    def test_cancellation_terminates_and_reaps_then_rotates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "trickortreasure.wav"
            second = root / "02-next.wav"
            write_wav(first)
            write_wav(second)
            music = IdleMusic(root, "hw:1,0")
            cancelled_process = WaitingProcess()
            completed_process = ImmediateProcess()
            with patch("idle_music.subprocess.Popen", side_effect=[cancelled_process, completed_process]) as popen, \
                 patch("idle_music.time.sleep", return_value=None):
                current = iter((True, False))
                self.assertFalse(music.play(lambda: next(current)))
                self.assertTrue(cancelled_process.terminated)
                self.assertTrue(cancelled_process.waited)
                self.assertTrue(music.play(lambda: True))

            self.assertEqual(popen.call_count, 2)
            self.assertEqual(popen.call_args_list[0].args[0], [
                "aplay", "-q", "-D", "hw:1,0", str(first),
            ])
            self.assertEqual(popen.call_args_list[1].args[0], [
                "aplay", "-q", "-D", "hw:1,0", str(second),
            ])
            self.assertTrue(completed_process.waited)

    def test_calls_are_serialized_and_rotate_in_sorted_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trick = root / "trickortreasure.wav"
            alpha = root / "01-alpha.wav"
            omega = root / "02-omega.wav"
            for path in (omega, trick, alpha):
                write_wav(path)
            music = IdleMusic(root, "default")
            release_first = threading.Event()
            first_started = threading.Event()
            second_calling = threading.Event()
            second_started = threading.Event()
            commands = []

            class GatedProcess(ImmediateProcess):
                def __init__(self, index):
                    super().__init__()
                    self.index = index

                def poll(self):
                    if self.index == 0 and not release_first.is_set():
                        return None
                    return 0

            def start_player(command, **kwargs):
                commands.append(command)
                index = len(commands) - 1
                if index == 0:
                    first_started.set()
                else:
                    second_started.set()
                return GatedProcess(index)

            results = []
            with patch("idle_music.subprocess.Popen", side_effect=start_player):
                first_thread = threading.Thread(target=lambda: results.append(music.play(lambda: True)))

                def call_second():
                    second_calling.set()
                    results.append(music.play(lambda: True))

                second_thread = threading.Thread(target=call_second)
                first_thread.start()
                self.assertTrue(first_started.wait(1))
                second_thread.start()
                self.assertTrue(second_calling.wait(1))
                try:
                    self.assertFalse(second_started.wait(0.1))
                finally:
                    release_first.set()
                first_thread.join(2)
                second_thread.join(2)

            self.assertFalse(first_thread.is_alive())
            self.assertFalse(second_thread.is_alive())
            self.assertEqual(results, [True, True])
            self.assertEqual([Path(command[-1]).name for command in commands], [
                trick.name, alpha.name,
            ])
            self.assertEqual([path.name for path in music.tracks], [
                trick.name, alpha.name, omega.name,
            ])

    def test_rejects_malformed_unsupported_and_overlong_wavs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malformed = root / "malformed.wav"
            malformed.write_bytes(b"not a WAV")
            unsupported = root / "unsupported.wav"
            write_wav(unsupported, channels=2)
            overlong = root / "overlong.wav"
            write_wav(overlong)
            with overlong.open("r+b") as wav_file:
                wav_file.seek(40)
                wav_file.write((24000 * 2 * 601).to_bytes(4, "little"))

            music = IdleMusic(root, "default")
            self.assertEqual(len(music.tracks), 3)
            with patch("idle_music.subprocess.Popen") as popen:
                for filename in ("malformed.wav", "overlong.wav", "unsupported.wav"):
                    with self.subTest(filename=filename):
                        self.assertFalse(music.play(lambda: True))
                popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
