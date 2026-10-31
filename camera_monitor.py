"""Local camera/Hailo calibration during audition; no saved images or audio."""
import json
from pathlib import Path
import signal
import sys
import time

import cv2
from pumpkin import Detector


def main():
    until = float(sys.argv[1])
    def stop(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    detector = Detector()
    camera = cv2.VideoCapture('/dev/video0', cv2.CAP_V4L2)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    path = Path(__file__).resolve().parent / 'camera-status.json'
    try:
        while time.time() < until:
            ok, frame = camera.read()
            status = {'time': time.time(), 'camera_ready': bool(ok)}
            if ok:
                status.update(people=int(detector.count(frame)), brightness=round(float(frame.mean()), 1))
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(status))
            temporary.replace(path)
            time.sleep(.5)
    finally:
        camera.release()
        detector.stack.close()


if __name__ == '__main__':
    main()
