"""Bounded speech capture with adaptive noise gating and preserved word onsets.

When an audio front end is running (audio_frontend.AudioFrontEnd, set as FRONTEND), the
gate reads its echo-cancelled stream; otherwise it records the microphone directly.
"""
from array import array
import io
import logging
import math
import os
from pathlib import Path
import select
import subprocess
import sys
import time
import wave


FRONTEND = None  # audio_frontend.AudioFrontEnd when echo cancellation is running.


class SpeechGate:
    def __init__(self, threshold=350, end_silence=.7, voice_test=None):
        self.threshold = threshold
        self.end_silence = end_silence
        self.noise = threshold / 3
        self.pre_roll = bytearray()
        self.speech = bytearray()
        self.started = False
        self.quiet = 0
        self.voiced = 0
        self.voice_test = voice_test

    def feed(self, chunk):
        samples = array('h', chunk)
        # Remove DC offset when measuring level (leave the captured PCM untouched).
        mean = sum(samples) / len(samples)
        rms = math.sqrt(sum((s - mean) ** 2 for s in samples) / len(samples))
        duration = len(samples) / 16000
        # Run every frame through VAD, including quiet ones, so its noise model adapts.
        voiced = self.voice_test(chunk) if self.voice_test is not None else True
        level = self.threshold if self.voice_test is not None else max(
            self.threshold, self.noise * (1.2 if self.started else 1.6))
        active = voiced and rms >= level
        if active:
            if not self.started:
                self.speech.extend(self.pre_roll)
                self.started = True
            self.voiced += duration
            self.quiet = 0
        elif not self.started:
            self.noise = .95 * self.noise + .05 * min(rms, self.threshold)
        if self.started:
            self.speech.extend(chunk)
            if not active:
                self.quiet += duration
            return self.quiet >= self.end_silence
        self.pre_roll.extend(chunk)
        del self.pre_roll[:-12800]  # 400 ms retains soft consonants before the gate opens.
        return False

    def wav(self):
        if self.voiced < .12:
            return b''
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(self.speech[:12 * 32000])
        return buffer.getvalue()


def listen(device=None, wait=7, current=None, since=None, end_silence=None):
    device = device or os.environ.get('AUDIO_INPUT', 'plughw:CARD=Device,DEV=0')
    threshold = float(os.environ.get('MIC_THRESHOLD', '350'))
    end_silence = float(end_silence if end_silence is not None else os.environ.get('MIC_END_SILENCE', '.7'))
    if not math.isfinite(threshold) or not 20 <= threshold <= 10000:
        raise ValueError('MIC_THRESHOLD must be 20..10000')
    if not math.isfinite(end_silence) or not .3 <= end_silence <= 1.5:
        raise ValueError('MIC_END_SILENCE must be .3..1.5 seconds')
    mode = os.environ.get('MIC_VAD', 'energy')
    if mode not in ('energy', 'webrtc'):
        raise ValueError('MIC_VAD must be energy or webrtc')
    voice_test = None
    if mode == 'webrtc':
        # Private pinned wheel leaves the Pi's system Python and other services alone.
        site = str(Path(__file__).resolve().parent / '.visitor-vad')
        if site not in sys.path:
            sys.path.insert(0, site)
        import webrtcvad
        vad = webrtcvad.Vad(1)
        voice_test = lambda frame: vad.is_speech(bytes(frame), 16000)
    gate = SpeechGate(threshold, end_silence, voice_test)
    frontend = FRONTEND if FRONTEND is not None and FRONTEND.alive else None
    queue = frontend.subscribe(since) if frontend is not None else None
    process = None if frontend is not None else subprocess.Popen(
        ['arecord', '-q', '-D', device, '-f', 'S16_LE', '-r', '16000', '-c', '1', '-t', 'raw'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if frontend is not None:
        mode += '+aec'
    started = time.monotonic()
    voice_started = None
    blips = 0
    pending = bytearray()
    try:
        while True:
            now = time.monotonic()
            if current is not None and not current():
                return b''
            # A late answer gets a full speaking window instead of being cut off at wait.
            if (voice_started is None and now - started >= wait) or (
                    voice_started is not None and now - voice_started >= 10):
                break
            if queue is not None:
                if not queue:
                    if not frontend.alive:
                        raise RuntimeError('Microphone front end stopped')
                    time.sleep(.01)
                    continue
                chunk = b''.join(queue.popleft() for _ in range(len(queue)))
            else:
                ready, _, _ = select.select([process.stdout], [], [], .1)
                if not ready:
                    if process.poll() is not None:
                        raise RuntimeError('Microphone capture failed')
                    continue
                chunk = os.read(process.stdout.fileno(), 3200)
                if not chunk:
                    raise RuntimeError('Microphone disconnected')
            pending.extend(chunk)
            while len(pending) >= 640:  # 20 ms PCM frames; pipe reads may split a sample.
                done = gate.feed(pending[:640])
                del pending[:640]
                if gate.started and voice_started is None:
                    voice_started = time.monotonic()
                if done and gate.voiced < .12:
                    # A blip (the pumpkin's own tail, a car door) is not an answer: keep listening for
                    # the rest of the window instead of returning nothing after half a second.
                    blips += 1
                    gate = SpeechGate(threshold, end_silence, voice_test)
                    voice_started = None
                    continue
                if done or len(gate.speech) >= 12 * 32000:
                    return gate.wav()
        return gate.wav()
    finally:
        logging.info('Microphone capture: seconds=%.2f voiced=%.2f mode=%s%s',
                     time.monotonic() - started, gate.voiced, mode, ' blips=%d' % blips if blips else '')
        if gate.voiced:
            logging.info('Cadence mic end=%.3f voiced=%.2f', time.time(), gate.voiced)
        if queue is not None:
            frontend.unsubscribe(queue)
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdout.close()
