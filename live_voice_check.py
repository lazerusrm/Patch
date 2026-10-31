"""Temporary guided porch check. Raw speech lives only in /dev/shm until scored."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import subprocess
import time
import wave

import numpy as np
from voice_input import SpeechGate
from vision_frames import visitor_image

ROOT = Path('/home/pi/pumpkintalk')
CHECK = Path('/dev/shm/pumpkin-voice-check')


def play(name):
    subprocess.run(['aplay', '-q', '-D', 'bluealsa:DEV=B1:2E:84:76:00:D9,PROFILE=a2dp',
                    str(CHECK / (name + '.wav'))], check=True, timeout=30)


def capture(card):
    return subprocess.run(['arecord', '-q', '-D', f'plughw:CARD={card},DEV=0', '-f', 'S16_LE',
                           '-r', '16000', '-c', '1', '-d', '9', '-t', 'raw'],
                          capture_output=True, check=True, timeout=13).stdout


def main():
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        state = json.loads((ROOT / 'status.json').read_text())
        if state.get('people', 0) > 0:
            break
        time.sleep(.3)
    else:
        print('No visitor arrived; no service change.')
        return
    subprocess.run(['sudo', 'systemd-run', '--unit=pumpkin-voice-check-restore', '--on-active=100s',
                    '/usr/bin/systemctl', 'start', 'pumpkin'], check=True, capture_output=True)
    try:
        subprocess.run(['sudo', 'systemctl', 'stop', 'pumpkin'], check=True)
        import base64
        import cv2
        camera = cv2.VideoCapture('/dev/video0', cv2.CAP_V4L2)
        try:
            camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            def snapshot():
                ok, frame = camera.read()
                return frame if ok else None
            image = visitor_image(snapshot)
            if image:
                (CHECK / 'visitor.jpg').write_bytes(base64.b64decode(image))
        finally:
            camera.release()
        report = {}
        for name in ('normal', 'quiet'):
            play(name)
            time.sleep(.4)
            with ThreadPoolExecutor(max_workers=2) as pool:
                captures = {card: pool.submit(capture, card) for card in ('C920', 'Device')}
                for card, future in captures.items():
                    raw = future.result()
                    pcm = np.frombuffer(raw, dtype='<i2').astype(float)
                    windows = pcm.reshape(-1, 1600).copy()
                    windows -= windows.mean(axis=1, keepdims=True)
                    levels = np.sqrt(np.mean(windows ** 2, axis=1))
                    report[f'{name}-{card}'] = {'peak': float(np.max(np.abs(pcm))),
                        'rms_median': float(np.median(levels)), 'rms_p95': float(np.percentile(levels, 95)),
                        'clipped_fraction': float(np.mean(np.abs(pcm) >= 32760)),
                        'rms_100ms': np.round(levels, 1).tolist()}
                    with wave.open(str(CHECK / f'{name}-{card}.wav'), 'wb') as wav:
                        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                        wav.writeframes(raw)
                    if card == 'C920':
                        gate = SpeechGate(threshold=100)
                        for offset in range(0, len(raw), 640):
                            if gate.feed(raw[offset:offset + 640]):
                                break
                        candidate = gate.wav()
                        (CHECK / f'{name}-candidate.wav').write_bytes(candidate)
                        report[f'{name}-{card}']['candidate_captured'] = bool(candidate)
        play('done')
        print(json.dumps(report))
    finally:
        subprocess.run(['sudo', 'systemctl', 'start', 'pumpkin'], check=True)
        subprocess.run(['sudo', 'systemctl', 'stop', 'pumpkin-voice-check-restore.timer'], capture_output=True)


if __name__ == '__main__':
    main()
