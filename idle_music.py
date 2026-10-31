"""Synchronous, interruptible playback for porch idle music."""
import logging
from array import array
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
    def __init__(self, directory, output, bus=None, gain=1.0, songs=(), every=3):
        self.directory = Path(directory)
        self.output = str(output)
        self.bus = bus
        self.gain = gain
        tracks = [path for path in self.directory.glob("*.wav") if path.is_file()]
        tracks.sort(key=lambda path: (
            path.name.casefold() != "trickortreasure.wav",
            path.name.casefold(),
            path.name,
        ))
        # Between visitors, the pumpkin's own songs rotate in: one after every `every` music tracks.
        songs = [Path(path) for path in songs if Path(path).is_file()]
        mixed = []
        for index, track in enumerate(tracks):
            mixed.append(track)
            if songs and (index + 1) % every == 0:
                mixed.append(songs[(index // every) % len(songs)])
        self._tracks = tuple(mixed)
        self._next_track = 0
        self._play_lock = threading.Lock()
        self.last_started = None
        self.last_signal_at = None

    @staticmethod
    def _last_signal(path, elapsed):
        # Inspect just the recent second, so a silent tail cannot mark the amp warm.
        if elapsed < 3:
            return None
        with wave.open(str(path), 'rb') as source:
            end = min(source.getnframes(), int(elapsed * _SAMPLE_RATE))
            start = max(0, end - _SAMPLE_RATE)
            source.setpos(start)
            samples = array('h', source.readframes(end - start))
        window = _SAMPLE_RATE // 50
        for offset in range(len(samples) - window, -1, -window):
            chunk = samples[offset:offset + window]
            mean = sum(chunk) / window
            if sum((value - mean) ** 2 for value in chunk) / window >= 200 ** 2:
                return (start + offset + window) / _SAMPLE_RATE
        return None

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
            self.last_started = self.last_signal_at = None
            if not self._tracks:
                return False

            track = self._tracks[self._next_track]
            self._next_track = (self._next_track + 1) % len(self._tracks)
            logging.info('Idle music: %s', track.name)
            process = None
            interrupted = False
            try:
                duration = self._duration(track)
                if not current():
                    return False
                if self.bus is not None and self.bus.open():
                    from speaker_bus import wav_chunks
                    job = self.bus.play(wav_chunks(track), current=current, gain=self.gain)
                    if job is not None and job.start_time is not None:
                        self.last_started = job.start_time
                        elapsed = time.monotonic() - job.start_time
                        try:
                            signal = self._last_signal(track, elapsed)
                            if signal is not None:
                                self.last_signal_at = self.last_started + signal
                        except (OSError, ValueError, wave.Error):
                            pass
                    return bool(job is not None and job.completed)
                process = subprocess.Popen(
                    ["aplay", "-q", "-D", self.output, str(track)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.last_started = time.monotonic()
                deadline = time.monotonic() + duration + 5
                while True:
                    if not current():
                        interrupted = True
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
                    elapsed = time.monotonic() - self.last_started if self.last_started is not None else 0
                    self._stop_process(process)
                    if self.last_started is not None and (interrupted or process.poll() == 0):
                        try:
                            signal = self._last_signal(track, elapsed)
                            if signal is not None:
                                self.last_signal_at = self.last_started + signal
                        except (OSError, ValueError, wave.Error):
                            pass
