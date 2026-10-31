"""Run on the Pi to undo this integration; refuse to overwrite later code edits."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path('/home/pi/pumpkintalk')
BACKUP = ROOT / '.pipeline-backup-20261024'
KEYS = {'MIC_THRESHOLD', 'MIC_VAD', 'TTS_URL', 'PUMPKIN_UNIFI_URL', 'PUMPKIN_UNIFI_TOKEN_FILE',
        'CHIME_AUDIO_OUTPUT', 'CHIME_PREROLL_SECONDS',
        'INTERNAL_AUDIO_OUTPUT', 'INTERNAL_AUDIO_DELAY_SECONDS',
        'AUDIO_WARM_PREROLL_SECONDS',
        'PORCH_GATE', 'PORCH_CROSSING_ENABLED'}


def main():
    manifest = json.loads((BACKUP / 'manifest.json').read_text())
    installed = json.loads((BACKUP / 'installed.json').read_text())
    for name, digest in installed.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Later edit must be preserved before rollback: ' + name)
    env = (ROOT / 'pumpkin.env').read_text().splitlines()
    before = (BACKUP / 'pumpkin.env').read_text().splitlines()
    env = [line for line in env if line.partition('=')[0] not in KEYS]
    env.extend(line for line in before if line.partition('=')[0] in KEYS)
    active = subprocess.run(['systemctl', 'is-active', '--quiet', 'pumpkin']).returncode == 0
    subprocess.run(['sudo', 'systemctl', 'stop', 'pumpkin'], check=True)
    try:
        for name in manifest['files']:
            if name in manifest['existing']:
                shutil.copy2(BACKUP / name, ROOT / name)
            else:
                (ROOT / name).unlink(missing_ok=True)
        (ROOT / 'pumpkin.env').write_text('\n'.join(env) + '\n')
        (ROOT / 'pumpkin.env').chmod(0o600)
    finally:
        if active:
            subprocess.run(['sudo', 'systemctl', 'start', 'pumpkin'], check=True)
    print('Original controller and integration settings restored; caches retained.')


if __name__ == '__main__':
    main()
