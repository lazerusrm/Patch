"""Always-on microphone with acoustic echo cancellation and barge-in detection.

One arecord stream from the porch microphone runs through WebRTC's audio processing
(AEC3 echo canceller, noise suppression, high-pass). Everything the speaker bus writes is
the echo reference, delayed by the measured speaker path (swept offline: 0.30 s plus a 40 ms hint; bus buffer plus
Bluetooth). Listening reads the cleaned stream, so the pumpkin can hear a visitor while
it talks or plays music, and a reply can be interrupted.
"""
from collections import deque
import logging
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

FRAME = 160  # 10 ms at 16 kHz, the processing unit.
RATE = 16000


class Resampler:
    """Exact 24 kHz -> 16 kHz linear resampling across chunks (no drift: absolute positions)."""

    def __init__(self):
        self.inputs = 0    # input samples consumed so far
        self.outputs = 0   # output samples produced so far
        self.last = 0.0    # previous chunk's final sample, for interpolation across the boundary

    def __call__(self, samples):
        import numpy as np
        data = np.concatenate([[self.last], samples.astype(np.float32)])
        base = self.inputs - 1  # absolute index of data[0]
        end = self.inputs + len(samples) - 1  # last absolute input index available
        count = int(end // 1.5) - self.outputs + 1 if end >= 0 else 0
        positions = (self.outputs + np.arange(max(0, count))) * 1.5 - base
        out = np.interp(positions, np.arange(len(data)), data).astype(np.int16)
        self.outputs += len(out)
        self.inputs += len(samples)
        if len(samples):
            self.last = float(samples[-1])
        return out


class BargeWatch:
    """Visitor speech on the echo-cancelled stream while the pumpkin is talking."""

    def __init__(self):
        self.window = float(os.environ.get('BARGE_WINDOW_SECONDS', '.45'))
        self.needed = float(os.environ.get('BARGE_SPEECH_SECONDS', '.3'))
        self.over_echo = float(os.environ.get('BARGE_OVER_ECHO', '2.2'))
        self.over_floor = float(os.environ.get('BARGE_OVER_FLOOR', '5'))
        self.grace = float(os.environ.get('BARGE_GRACE_SECONDS', '.8'))  # Let the canceller see the clip start.
        self.frames = deque()
        self.residual = deque(maxlen=200)
        self.started = time.monotonic()
        self.triggered_at = None

    def update(self, t, vad, rms_out, floor):
        if self.triggered_at is not None:
            return True
        # Residual echo level: median of the last 2 s of cleaned output. A visitor talking over the
        # pumpkin is much louder than that and too recent to move the median.
        echo = sorted(self.residual)[len(self.residual) // 2] if self.residual else rms_out
        self.residual.append(rms_out)
        if t - self.started < self.grace:
            return False  # Learn the echo level while the canceller settles on this clip.
        speech = vad and rms_out > max(floor * self.over_floor, echo * self.over_echo)
        self.frames.append((t, speech))
        while self.frames and self.frames[0][0] < t - self.window:
            self.frames.popleft()
        if sum(.01 for _, s in self.frames if s) >= self.needed:
            self.triggered_at = t
            logging.info('Barge-in: visitor speech over playback (out=%.0f echo=%.0f floor=%.0f)', rms_out, echo, floor)
            return True
        return False


class AudioFrontEnd:
    def __init__(self, device, processor=None, vad=None):
        import numpy as np
        self.np = np
        self.device = device
        self.ref_delay = float(os.environ.get('AEC_REF_DELAY', '.24'))  # Swept on live porch capture.
        self.hint_ms = int(os.environ.get('AEC_DELAY_HINT_MS', '40'))
        self.processor = processor if processor is not None else self._webrtc()
        self.vad = vad if vad is not None else self._vad()
        self.reference = deque()  # (due monotonic time, int16 frame)
        self.ref_lock = threading.Lock()
        self.resample = Resampler()
        self.pending = np.zeros(0, dtype=np.int16)
        self.next_due = None
        self.subscribers = []
        self.sub_lock = threading.Lock()
        self.history = deque(maxlen=300)  # 3 s of (t, cleaned frame bytes)
        self.floor = 30.0
        self.stats = deque(maxlen=3000)  # (t, rms_in, rms_out, vad): 30 s for tuning and checks.
        self.barge = None
        self.stop = threading.Event()
        self.thread = None
        self.process = None
        self.alive = False

    @staticmethod
    def _private(path):
        site = str(Path(__file__).resolve().parent / path)
        if site not in sys.path:
            sys.path.insert(0, site)

    def _webrtc(self):
        self._private('.visitor-aec')
        from livekit import rtc
        # Gain control after echo removal brings a voice from the far end of the path up to a level
        # Whisper can read (owner tests: short commands peaked at only 2-5% of full scale without it).
        apm = rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=True, high_pass_filter=True,
                                        auto_gain_control=os.environ.get('AEC_AGC', '1') == '1')

        def process(capture, render_frames):
            for frame in render_frames:
                buffer = rtc.AudioFrame.create(RATE, 1, FRAME)
                self.np.frombuffer(buffer.data, dtype=self.np.int16)[:] = frame
                apm.process_reverse_stream(buffer)
            apm.set_stream_delay_ms(self.hint_ms)
            buffer = rtc.AudioFrame.create(RATE, 1, FRAME)
            self.np.frombuffer(buffer.data, dtype=self.np.int16)[:] = capture
            apm.process_stream(buffer)
            return self.np.frombuffer(buffer.data, dtype=self.np.int16).copy()
        return process

    def _vad(self):
        self._private('.visitor-vad')
        import webrtcvad
        detector = webrtcvad.Vad(2)
        return lambda frame: detector.is_speech(frame.tobytes(), RATE)

    # Reference (what the porch speaker is about to play) -------------------------
    def feed_reference(self, data, written_at):
        """Called by the speaker bus for every 24 kHz chunk it writes."""
        np = self.np
        samples = self.resample(np.frombuffer(data, dtype=np.int16))
        with self.ref_lock:
            due = written_at + self.ref_delay
            if self.next_due is None or abs(self.next_due - due) > .25:
                self.next_due = due  # (Re)anchor after a gap or a bus restart.
            self.pending = np.concatenate([self.pending, samples])
            while len(self.pending) >= FRAME:
                self.reference.append((self.next_due, self.pending[:FRAME]))
                self.pending = self.pending[FRAME:]
                self.next_due += FRAME / RATE
            while len(self.reference) > 400:  # Never hold more than 4 s.
                self.reference.popleft()

    def _due_reference(self, now):
        frames = []
        with self.ref_lock:
            while self.reference and self.reference[0][0] <= now:
                frames.append(self.reference.popleft()[1])
        return frames

    # Capture -----------------------------------------------------------------------
    def set_mic_gain(self):
        """Hardware capture gain of the porch webcam mic (0-15 on the C920; it boots at 5)."""
        gain = os.environ.get('MIC_CAPTURE_GAIN', '9')
        card = self.device.split('CARD=')[-1].split(',')[0] if 'CARD=' in self.device else None
        if card and gain:
            result = subprocess.run(['amixer', '-c', card, 'sset', 'Mic', gain], capture_output=True, text=True)
            if result.returncode == 0:
                logging.info('Porch mic capture gain set to %s', gain)

    def start(self):
        self.set_mic_gain()
        self.process = subprocess.Popen(['arecord', '-q', '-D', self.device, '-f', 'S16_LE', '-r', str(RATE),
                                         '-c', '1', '-t', 'raw', '--buffer-time=40000', '--period-time=10000'],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not self.alive and self.process.poll() is None:
            time.sleep(.05)
        if not self.alive:
            self.close()
            raise RuntimeError('Microphone front end did not start')
        logging.info('Audio front end running: echo cancellation on %s, reference delay %.2fs',
                     self.device, self.ref_delay)

    def close(self):
        self.stop.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
        self.alive = False

    def _run(self):
        np = self.np
        stream = self.process.stdout
        try:
            while not self.stop.is_set():
                raw = stream.read(FRAME * 2)
                if len(raw) < FRAME * 2:
                    break
                self.alive = True
                now = time.monotonic()
                capture = np.frombuffer(raw, dtype=np.int16)
                render = self._due_reference(now) or [np.zeros(FRAME, dtype=np.int16)]
                cleaned = self.processor(capture, render)
                rms_in = math.sqrt(float(np.mean(capture.astype(np.float32) ** 2)))
                rms_out = math.sqrt(float(np.mean(cleaned.astype(np.float32) ** 2)))
                vad = bool(self.vad(cleaned))
                if not vad:
                    self.floor = .995 * self.floor + .005 * min(rms_out, 400)
                frame = cleaned.tobytes()
                self.history.append((now, frame))
                barge = self.barge
                if barge is not None:
                    barge.update(now, vad, rms_out, self.floor)
                self.stats.append((now, rms_in, rms_out, vad))
                with self.sub_lock:
                    for queue in self.subscribers:
                        queue.append(frame)
        except (OSError, ValueError):
            logging.exception('Audio front end failed')
        finally:
            self.alive = False
            if not self.stop.is_set() and not getattr(sys, 'is_finalizing', lambda: False)():
                logging.warning('Audio front end stopped; listening falls back to direct capture')

    # Consumers ---------------------------------------------------------------------
    def subscribe(self, since=None):
        """A queue of cleaned 10 ms frames; optionally pre-filled from history after `since`."""
        queue = deque(maxlen=1500)
        if since is not None:
            queue.extend(frame for t, frame in list(self.history) if t >= since)
        with self.sub_lock:
            self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue):
        with self.sub_lock:
            if queue in self.subscribers:
                self.subscribers.remove(queue)

    def watch(self):
        """Start watching for barge-in during a playback; returns the watch."""
        self.barge = BargeWatch()
        return self.barge

    def unwatch(self, watch):
        if self.barge is watch:
            self.barge = None
