"""Synchronous, interruptible playback for porch idle music."""
import logging
from pathlib import Path
import subprocess
import threading
import time
import wave


_LOG = logging.getLogger(__name__)
_SAMPLE_RATE = 24000
_MAX_DURATION = 10 * 60
_POLL_INTERVAL = 0.05


class IdleMusic:
    def __init__(self, directory, output):
        self.directory = Path(directory)
        self.output = str(output)
        tracks = [path for path in self.directory.glob("*.wav") if path.is_file()]
        tracks.sort(key=lambda path: (
            path.name.casefold() != "trickortreasure.wav",
            path.name.casefold(),
            path.name,
        ))
        self._tracks = tuple(tracks)
        self._next_track = 0
        self._play_lock = threading.Lock()

    @property
    def tracks(self):
        return self._tracks

    @staticmethod
    def _duration(path):
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            compression = source.getcomptype()
            frames = source.getnframes()
            if (channels, sample_width, sample_rate, compression) != (1, 2, _SAMPLE_RATE, "NONE"):
                raise ValueError("expected mono 16-bit PCM at 24 kHz")
            if frames <= 0:
                raise ValueError("empty WAV track")
            duration = frames / sample_rate
            if duration > _MAX_DURATION:
                raise ValueError("WAV track exceeds 10 minutes")
            if path.stat().st_size < 44 + frames * sample_width * channels:
                raise ValueError("truncated WAV track")
        return duration

    @staticmethod
    def _stop_process(process):
        try:
            if process.poll() is None:
                process.terminate()
        except Exception as exc:
            _LOG.warning("Could not terminate idle music player: %s", exc)
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except Exception as exc:
                _LOG.warning("Could not kill idle music player: %s", exc)
            try:
                process.wait()
            except Exception as exc:
                _LOG.warning("Could not reap idle music player: %s", exc)
        except Exception as exc:
            _LOG.warning("Could not reap idle music player: %s", exc)

    def play(self, current):
        with self._play_lock:
            if not self._tracks:
                return False

            track = self._tracks[self._next_track]
            self._next_track = (self._next_track + 1) % len(self._tracks)
            process = None
            try:
                duration = self._duration(track)
                if not current():
                    return False
                process = subprocess.Popen(
                    ["aplay", "-q", "-D", self.output, str(track)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                deadline = time.monotonic() + duration + 5
                while True:
                    if not current():
                        return False
                    returncode = process.poll()
                    if returncode is not None:
                        if returncode:
                            _LOG.warning("aplay failed for %s with status %s", track.name, returncode)
                        return returncode == 0
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        _LOG.warning("Idle music playback stalled: %s", track.name)
                        return False
                    time.sleep(min(_POLL_INTERVAL, remaining))
            except Exception as exc:
                _LOG.warning("Could not play idle music track %s: %s", track.name, exc)
                return False
            finally:
                if process is not None:
                    self._stop_process(process)
