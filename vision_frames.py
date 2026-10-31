"""A short, cancellable camera burst, encoded as one chronological contact sheet."""
import base64
import time


def visitor_image(snapshot, current=lambda: True, interval=.4, max_width=640):
    import cv2
    import numpy as np

    panels = []
    previous = None
    for index in range(3):
        if index:
            deadline = time.monotonic() + interval
            while time.monotonic() < deadline:
                if not current():
                    return ''
                time.sleep(min(.05, max(0, deadline - time.monotonic())))
        if not current():
            return ''
        frame = snapshot()
        if frame is None:
            continue
        if previous is not None and np.array_equal(frame, previous):
            continue
        previous = frame
        height, width = frame.shape[:2]
        scale = min(640 / width, 350 / height, 1)
        resized = cv2.resize(frame, (round(width * scale), round(height * scale)))
        panel = np.zeros((375, 640, 3), dtype=np.uint8)
        panel[25:25 + resized.shape[0], :resized.shape[1]] = resized
        cv2.putText(panel, f'Frame {index + 1} - {index * interval:.1f}s', (8, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
        panels.append(panel)
    if not panels or not current():
        return ''
    sheet = np.vstack(panels)
    if max_width < 640:
        sheet = cv2.resize(sheet, (max_width, round(sheet.shape[0] * max_width / 640)))
    for quality in (75, 55, 35):
        ok, jpeg = cv2.imencode('.jpg', sheet, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok:
            encoded = base64.b64encode(jpeg).decode()
            if len(encoded) <= 500000:
                return encoded
    return ''
