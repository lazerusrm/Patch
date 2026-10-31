"""One continuously open speaker stream, so music and lines start without warm-up.

Bluetooth speakers lose the first syllables when a stream opens cold. Keeping a
single aplay process alive and feeding a faint keepalive between clips means
every clip after the first warm-up starts immediately.
"""
from array import array
import fcntl
import logging
import math
import os
import subprocess
import threading
import time
import wave

RATE = 24000
CHUNK = 480  # 20 ms
F_SETPIPE_SZ = 1031


def apply_gain(data, gain):
    try:
        import numpy
        samples = numpy.frombuffer(data, dtype=numpy.int16).astype(numpy.float32) * gain
        return numpy.clip(samples, -32768, 32767).astype(numpy.int16).tobytes()
    except ImportError:
        return array('h', (max(-32768, min(32767, int(v * gain))) for v in array('h', data))).tobytes()


def _tone(frequency, amplitude, frames, phase=0):
    return array('h', (int(amplitude * math.sin(2 * math.pi * frequency * (phase + i) / RATE))
                       for i in range(frames)))


class Job:
    def __init__(self, chunks, gain=1.0):
        self.chunks = chunks
        self.gain = gain
        self.cancel = threading.Event()
        self.done = threading.Event()
        self.started = threading.Event()
        self.start_time = None  # Estimated monotonic time the first sample is heard.
        self.completed = False


def wav_chunks(path, start=0):
    with wave.open(str(path)) as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, RATE):
            raise ValueError('Speaker bus needs mono PCM16 at 24 kHz')
        source.setpos(start)
        while True:
            data = source.readframes(CHUNK)
            if not data:
                return
            yield data


def sample_chunks(samples):
    data = samples.tobytes() if isinstance(samples, array) else bytes(samples)
    step = CHUNK * 2
    for offset in range(0, len(data), step):
        yield data[offset:offset + step]


class SpeakerBus:
    def __init__(self, device, warm_seconds=3.0, latency=None, keepalive_hz=None, keepalive_amplitude=None):
        self.device = device
        self.warm_seconds = warm_seconds
        self.latency = float(os.environ.get('SPEAKER_BUS_LATENCY', '.12') if latency is None else latency)
        self.keepalive_hz = float(os.environ.get('SPEAKER_BUS_KEEPALIVE_HZ', '180') if keepalive_hz is None else keepalive_hz)
        self.keepalive_amplitude = int(os.environ.get('SPEAKER_BUS_KEEPALIVE_AMPLITUDE', '120')
                                       if keepalive_amplitude is None else keepalive_amplitude)
        self.buffer_us = int(os.environ.get('SPEAKER_BUS_BUFFER_US', '160000'))
        # Pace writes to real time with a small lead so the driver buffer stays short.
        self.lead = float(os.environ.get('SPEAKER_BUS_LEAD', '.2'))
        self.lock = threading.Lock()
        self.process = None
        self.thread = None
        self.job = None
        self.opened_at = None
        self.failed_at = float('-inf')
        self.last_audio_end = None
        self.stopping = threading.Event()
        self.tap = None  # Called with (chunk, write time) for everything written: the echo reference.

    @property
    def is_open(self):
        return self.process is not None and self.process.poll() is None and self.thread is not None and self.thread.is_alive()

    def warm(self):
        return self.is_open and time.monotonic() - self.opened_at >= self.warm_seconds

    def open(self):
        with self.lock:
            if self.is_open:
                return True
            if time.monotonic() - self.failed_at < 5:
                return False
            self._close_locked()
            try:
                self.process = subprocess.Popen(
                    ['aplay', '-q', '-D', self.device, '-t', 'raw', '-f', 'S16_LE', '-r', str(RATE), '-c', '1',
                     '--buffer-time=' + str(self.buffer_us), '--period-time=' + str(self.buffer_us // 4)],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    fcntl.fcntl(self.process.stdin.fileno(), F_SETPIPE_SZ, 4096)
                except OSError:
                    pass  # Larger pipe only adds a little latency.
            except OSError:
                self.failed_at = time.monotonic()
                self.process = None
                return False
            self.opened_at = time.monotonic()
            self.stopping.clear()
            self.thread = threading.Thread(target=self._run, args=(self.process,), daemon=True)
            self.thread.start()
            logging.info('Speaker bus opened')
            return True

    def close(self):
        with self.lock:
            self._close_locked()

    def _close_locked(self):
        self.stopping.set()
        job = self.job
        if job:
            job.cancel.set()
        process, self.process = self.process, None
        if process is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        self.thread = None

    def _run(self, process):
        phase = 0
        written = 0
        clock = time.monotonic()
        try:
            while not self.stopping.is_set():
                ahead = written / RATE - (time.monotonic() - clock)
                if ahead > self.lead:
                    time.sleep(min(.01, ahead - self.lead))
                    continue
                if ahead < -.5:
                    clock = time.monotonic() - written / RATE  # Resynchronize after a stall.
                job = self.job
                data = None
                if job is not None:
                    if job.cancel.is_set():
                        self._finish(job)
                        continue
                    data = next(job.chunks, None)
                    if data is None:
                        job.completed = True
                        self._finish(job)
                        continue
                    if job.gain != 1:
                        data = apply_gain(data, job.gain)
                    if not job.started.is_set():
                        job.start_time = time.monotonic() + self.latency
                        job.started.set()
                if data is None:
                    warming = time.monotonic() - self.opened_at < self.warm_seconds
                    data = _tone(self.keepalive_hz, 300 if warming else self.keepalive_amplitude, CHUNK, phase).tobytes()
                    phase = (phase + CHUNK) % RATE
                process.stdin.write(data)
                written += len(data) // 2
                tap = self.tap
                if tap is not None:
                    try:
                        tap(data, time.monotonic())
                    except Exception:
                        logging.exception('Speaker bus tap failed; echo reference disabled')
                        self.tap = None
        except (OSError, ValueError, BrokenPipeError):
            if not self.stopping.is_set():
                logging.warning('Speaker bus stream ended; falling back to per-clip playback')
                self.failed_at = time.monotonic()
        finally:
            job = self.job
            if job is not None:
                self._finish(job)

    def _finish(self, job):
        if self.job is job:
            self.job = None
        if job.started.is_set():
            self.last_audio_end = time.monotonic() + self.latency
        job.started.set()
        job.done.set()

    def play(self, chunks, current=None, gain=1.0, on_start=None):
        """Queue one clip (replacing nothing) and block until heard, cancelled, or failed."""
        if not self.open():
            return None
        job = Job(chunks, gain)
        deadline = time.monotonic() + 2
        while self.job is not None:  # Callers are serialized; tolerate a finishing clip.
            if time.monotonic() > deadline:
                self.job.cancel.set()
            if time.monotonic() > deadline + 3:
                logging.warning('Speaker bus stuck on a previous clip; reopening')
                self.close()
                return None
            time.sleep(.005)
        self.job = job
        while not job.started.wait(.02):
            if (current is not None and not current()) or not self.is_open:
                job.cancel.set()
                return job
        if on_start is not None and job.start_time is not None:
            on_start(job)
        while not job.done.wait(.02):
            if (current is not None and not current()) or not self.is_open:
                job.cancel.set()
                job.done.wait(1)
                return job
        # The stream buffer still holds the tail; wait until it has been heard.
        if job.completed:
            remaining = (self.last_audio_end or 0) - time.monotonic()
            while remaining > 0 and (current is None or current()):
                time.sleep(min(.02, remaining))
                remaining = (self.last_audio_end or 0) - time.monotonic()
        return job
