"""Reconnect only the explicitly commissioned speaker; never scan or re-pair."""
import re
import subprocess
import sys


def connect(device):
    if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', device):
        raise ValueError('Invalid speaker address')
    try:
        status = subprocess.run(['bluetoothctl', 'info', device], capture_output=True,
                                text=True, timeout=5)
        if status.returncode == 0 and 'Connected: yes' in status.stdout:
            return True
        result = subprocess.run(['bluetoothctl', 'connect', device], capture_output=True,
                                text=True, timeout=25)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


if __name__ == '__main__':
    sys.exit(0 if connect(sys.argv[1]) else 1)
