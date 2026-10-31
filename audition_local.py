"""Short local-only voice comparisons; uses desktop audio, never the porch Pi."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import wave
from loudness import normalize_wav

ROOT = Path(__file__).resolve().parent
CLIPS = ROOT / 'runtime/likeness-v4-audition'
GROUPS = {
    'dobby-new': [('Original Dobby reference', 'dobby-user-original'),
                  ('Current Dobby A', 'dobby-a'),
                  ('New Dobby one, introduction reference', 'dobby-user-intro'),
                  ('New Dobby two, speaking reference', 'dobby-user-speaking')],
    'dobby': [('Dobby A (current)', 'dobby-a'),
              ('Dobby: full clean-reference conversion', 'dobby-tone'),
              ('Dobby: gentler conversion', 'dobby-tone60')],
    'strongbad': [('Strong Bad 2 (current)', 'strongbad-2'),
                  ('Strong Bad: expressive reference conversion', 'strongbad-tone-expressive'),
                  ('Strong Bad: calm reference conversion', 'strongbad-tone-calm'),
                  ('Strong Bad: gentler calm conversion', 'strongbad-tone-calm60')],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('character', choices=GROUPS, nargs='?', default='dobby')
    args = parser.parse_args()
    server = 'unix:/run/user/' + str(os.getuid()) + '/pulse/native'
    sink = subprocess.run(['pactl', '--server', server, 'get-default-sink'],
                          capture_output=True, text=True, check=True, timeout=5).stdout.strip()
    clips = []
    for label, name in GROUPS[args.character]:
        path = CLIPS / (name + '.wav')
        with wave.open(str(path)) as audio:
            duration = audio.getnframes() / audio.getframerate()
            if audio.getnchannels() != 1 or not 0 < duration <= 30:
                raise ValueError('Expected short mono audition: ' + str(path))
        clips.append((label, path, duration))
    if sum(item[2] + 3 for item in clips) > 90:
        raise ValueError('Local comparison exceeds 90 seconds')
    streams = subprocess.run(['pactl', '--server', server, '-f', 'json', 'list', 'source-outputs'],
                             capture_output=True, text=True, check=True, timeout=5)
    if any('audacity' in json.dumps(item.get('properties', {})).lower()
           for item in json.loads(streams.stdout)):
        raise SystemExit('Audacity has a recording or monitoring stream open. Stop it before the audition.')
    print('Local output: ' + sink, flush=True)
    with tempfile.TemporaryDirectory(dir=ROOT / 'runtime', prefix='local-labels-') as directory:
        labels = []
        for index, (label, _, _) in enumerate(clips):
            raw = Path(directory) / f'{index}-raw.wav'
            matched = Path(directory) / f'{index}.wav'
            subprocess.run(['espeak-ng', '-s', '155', '-w', str(raw), label], check=True, timeout=5)
            normalize_wav(raw, matched)
            with wave.open(str(matched)) as audio:
                labels.append((matched, audio.getnframes() / audio.getframerate()))
        if sum(item[2] + labels[i][1] + 3 for i, item in enumerate(clips)) > 90:
            raise ValueError('Labeled comparison exceeds 90 seconds')
        for (label, path, duration), (spoken_label, label_duration) in zip(clips, labels):
            print(label, flush=True)
            for audio, seconds in ((spoken_label, label_duration), (path, duration)):
                subprocess.run(['paplay', '--server', server, '--device', sink, str(audio)],
                               check=True, timeout=seconds + 5)
            time.sleep(3)
    print('Comparison complete. No porch settings changed.', flush=True)


if __name__ == '__main__':
    main()
