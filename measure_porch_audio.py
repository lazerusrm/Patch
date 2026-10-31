"""One bounded dual-mic/speaker measurement; retain numbers, never recordings."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import subprocess
import time
import wave

import numpy as np


def main():
    root = Path('/home/pi/pumpkintalk')
    source = root / 'auditions/likeness/dobby-a.wav'
    with wave.open(str(source)) as wav:
        params = wav.getparams()
        frames = wav.readframes(min(wav.getnframes(), wav.getframerate() * 5))
    sample = io.BytesIO()
    with wave.open(sample, 'wb') as wav:
        wav.setparams(params)
        # Same quiet speaker preparation used in production, followed by five seconds.
        warm = (300 * np.sin(2 * np.pi * 180 * np.arange(params.framerate * 3) / params.framerate)).astype('<i2')
        wav.writeframes(np.repeat(warm, params.nchannels).tobytes())
        wav.writeframes(frames)
    active = subprocess.run(['systemctl', 'is-active', '--quiet', 'pumpkin']).returncode == 0
    if not active:
        raise RuntimeError('Porch service not active; do not change another operator state')
    subprocess.run(['sudo', 'systemd-run', '--unit=pumpkin-mic-restore', '--on-active=45s',
                    '/usr/bin/systemctl', 'start', 'pumpkin'], check=True, capture_output=True)
    try:
        subprocess.run(['sudo', 'systemctl', 'stop', 'pumpkin'], check=True)
        def capture(card):
            return subprocess.run(['arecord', '-q', '-D', f'plughw:CARD={card},DEV=0',
                                   '-f', 'S16_LE', '-r', '16000', '-c', '1', '-d', '15', '-t', 'raw'],
                                  capture_output=True, timeout=20, check=True).stdout
        with ThreadPoolExecutor(max_workers=2) as pool:
            captures = {card: pool.submit(capture, card) for card in ('C920', 'Device')}
            time.sleep(3)
            subprocess.run(['aplay', '-q', '-D', 'bluealsa:DEV=B1:2E:84:76:00:D9,PROFILE=a2dp'],
                           input=sample.getvalue(), capture_output=True, timeout=15, check=True)
            report = {}
            for card, future in captures.items():
                pcm = np.frombuffer(future.result(), dtype='<i2').astype(float)
                windows = pcm[:len(pcm) // 1600 * 1600].reshape(-1, 1600)
                rms = np.sqrt(np.mean(windows ** 2, axis=1))
                report[card] = {'seconds': len(pcm) / 16000,
                                'baseline_rms_median': round(float(np.median(rms[5:25])), 1),
                                'speaker_rms_median': round(float(np.median(rms[65:105])), 1),
                                'tail_rms_median': round(float(np.median(rms[125:])), 1),
                                'peak': round(float(np.max(np.abs(pcm))), 1),
                                'clipped_fraction': float(np.mean(np.abs(pcm) >= 32760)),
                                'rms_100ms': np.round(rms, 1).tolist()}
            print(json.dumps(report))
    finally:
        subprocess.run(['sudo', 'systemctl', 'start', 'pumpkin'], check=True)
        subprocess.run(['sudo', 'systemctl', 'stop', 'pumpkin-mic-restore.timer'], capture_output=True)


if __name__ == '__main__':
    main()
