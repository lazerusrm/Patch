"""Run on Pi after staging/tests. Check current hashes, back up, atomically install."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path('/home/pi/pumpkintalk')
STAGE = ROOT / '.pipeline-stage-20261024'
BACKUP = ROOT / '.pipeline-backup-20261024'
FILES = ['pumpkin.py', 'core.py', 'voice_input.py', 'vision_frames.py', 'unifi_client.py',
         'visitor_motion.py', 'porch_bits.py', 'sorting_ceremonies.py', 'porch_crossing.py',
         'routine_audio.py', 'games.py', 'entertainment.json', 'idle_music.py']


def main():
    expected = json.loads((STAGE / 'expected.json').read_text())
    for name in FILES:
        target = ROOT / name
        if target.exists():
            if name not in expected or hashlib.sha256(target.read_bytes()).hexdigest() != expected[name]:
                raise RuntimeError('Concurrent source change: ' + name)
    if BACKUP.exists():
        raise RuntimeError('Backup already exists; inspect before another installation')
    BACKUP.mkdir(mode=0o700)
    existing = []
    for name in FILES + ['pumpkin.env']:
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, BACKUP / name)
            existing.append(name)
    (BACKUP / 'manifest.json').write_text(json.dumps({'files': FILES, 'existing': existing}))
    active = subprocess.run(['systemctl', 'is-active', '--quiet', 'pumpkin']).returncode == 0
    if active:
        subprocess.run(['sudo', 'systemd-run', '--unit=pumpkin-pipeline-restore', '--on-active=90s',
                        '/usr/bin/systemctl', 'start', 'pumpkin'], check=True, capture_output=True)
        subprocess.run(['sudo', 'systemctl', 'stop', 'pumpkin'], check=True)
    try:
        for name in FILES:
            temporary = ROOT / (name + '.pipeline-new')
            shutil.copy2(STAGE / name, temporary)
            temporary.replace(ROOT / name)
        shutil.copytree(STAGE / 'cache', ROOT / 'cache', dirs_exist_ok=True)
        (ROOT / 'assets/effects').mkdir(parents=True, exist_ok=True)
        for name in ('button-fart.wav', 'small-fanfare.wav', 'polite-ding.wav'):
            shutil.copy2(STAGE / 'assets/effects' / name, ROOT / 'assets/effects' / name)
        changes = {'MIC_THRESHOLD': '100', 'PUMPKIN_UNIFI_URL': 'http://127.0.0.1:8768',
                   'PUMPKIN_UNIFI_TOKEN_FILE': str(ROOT / 'unifi-bridge.token')}
        lines = (ROOT / 'pumpkin.env').read_text().splitlines()
        lines = [line for line in lines if line.partition('=')[0] not in changes]
        lines.extend(key + '=' + value for key, value in changes.items())
        target = ROOT / 'pumpkin.env.pipeline-new'
        target.write_text('\n'.join(lines) + '\n')
        target.chmod(0o600)
        target.replace(ROOT / 'pumpkin.env')
        print('Installed visitor pipeline; previous files and settings preserved in', BACKUP)
    except Exception:
        for name in FILES + ['pumpkin.env']:
            if name in existing:
                shutil.copy2(BACKUP / name, ROOT / name)
            elif name in FILES:
                (ROOT / name).unlink(missing_ok=True)
        raise
    finally:
        if active:
            subprocess.run(['sudo', 'systemctl', 'start', 'pumpkin'], check=True)
            subprocess.run(['sudo', 'systemctl', 'stop', 'pumpkin-pipeline-restore.timer'], capture_output=True)


if __name__ == '__main__':
    main()
