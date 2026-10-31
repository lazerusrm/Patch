"""YOLOv8s-pose on the Hailo-8: person boxes plus 17 COCO keypoints, and simple pose tests.

The HEF (Hailo Model Zoo v2.13, hailo8/yolov8s_pose.hef) returns raw heads at strides 32/16/8:
a 64-channel DFL box head, a 1-channel person score and 51 keypoint channels (17 x [x, y, conf]).
decode() turns them into people in normalized frame coordinates.
"""
import math

import numpy as np

KEYPOINTS = ('nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear', 'left_shoulder', 'right_shoulder',
             'left_elbow', 'right_elbow', 'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
             'left_knee', 'right_knee', 'left_ankle', 'right_ankle')
K = {name: index for index, name in enumerate(KEYPOINTS)}


def _sigmoid(x):
    return 1 / (1 + np.exp(-x))


def _looks_like_probability(x):
    return float(np.min(x)) >= 0 and float(np.max(x)) <= 1.0001


def _nms(boxes, scores, iou=.5):
    order = np.argsort(-scores)
    keep = []
    while len(order):
        i = order[0]
        keep.append(i)
        if len(order) == 1:
            break
        rest = order[1:]
        x1 = np.maximum(boxes[i, 0], boxes[rest, 0]); y1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        x2 = np.minimum(boxes[i, 2], boxes[rest, 2]); y2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
        area = lambda b: (b[..., 2] - b[..., 0]) * (b[..., 3] - b[..., 1])
        overlap = inter / (area(boxes[i]) + area(boxes[rest]) - inter + 1e-9)
        order = rest[overlap < iou]
    return keep


def decode(outputs, size=640, min_score=.3):
    """outputs: {name: float array (1, H, W, C)} -> list of people dicts (normalized 0..1)."""
    heads = {}
    for name, value in outputs.items():
        array = np.asarray(value, dtype=np.float32)
        array = array[0] if array.ndim == 4 else array
        heads.setdefault(array.shape[0], {})[array.shape[-1]] = array
    boxes, scores, points = [], [], []
    for grid, parts in heads.items():
        if not {64, 1, 51} <= set(parts):
            continue
        stride = size / grid
        cls = parts[1][..., 0]
        cls = cls if _looks_like_probability(cls) else _sigmoid(cls)
        ys, xs = np.nonzero(cls >= min_score)
        if not len(ys):
            continue
        dfl = parts[64][ys, xs].reshape(-1, 4, 16)
        dfl = np.exp(dfl - dfl.max(-1, keepdims=True))
        dfl /= dfl.sum(-1, keepdims=True)
        dist = (dfl * np.arange(16)).sum(-1) * stride  # left, top, right, bottom
        cx, cy = (xs + .5) * stride, (ys + .5) * stride
        boxes.append(np.stack([cx - dist[:, 0], cy - dist[:, 1], cx + dist[:, 2], cy + dist[:, 3]], -1))
        scores.append(cls[ys, xs])
        kp = parts[51][ys, xs].reshape(-1, 17, 3)
        kx = (kp[..., 0] * 2 + xs[:, None]) * stride
        ky = (kp[..., 1] * 2 + ys[:, None]) * stride
        kc = kp[..., 2] if _looks_like_probability(kp[..., 2]) else _sigmoid(kp[..., 2])
        points.append(np.stack([kx, ky, kc], -1))
    if not boxes:
        return []
    boxes, scores, points = np.concatenate(boxes), np.concatenate(scores), np.concatenate(points)
    people = []
    for i in _nms(boxes, scores):
        x1, y1, x2, y2 = np.clip(boxes[i] / size, 0, 1)
        kps = [(float(np.clip(x / size, 0, 1)), float(np.clip(y / size, 0, 1)), float(c)) for x, y, c in points[i]]
        people.append({'box': (float(y1), float(x1), float(y2), float(x2), float(scores[i])), 'keypoints': kps})
    return people


def _point(person, name, min_conf=.4):
    x, y, c = person['keypoints'][K[name]]
    return (x, y) if c >= min_conf else None


def hands_raised(person):
    """Number of hands held clearly above the shoulders (0, 1 or 2); hands resting on the head do not count."""
    if hands_on_head(person):
        return 0
    raised = 0
    shoulders = [p for p in (_point(person, 'left_shoulder'), _point(person, 'right_shoulder')) if p]
    if not shoulders:
        return 0
    box = person['box']
    margin = .08 * max(.05, box[2] - box[0])  # Clearly above, relative to how big they appear.
    for side in ('left', 'right'):
        wrist, shoulder, elbow = (_point(person, side + part) for part in ('_wrist', '_shoulder', '_elbow'))
        shoulder = shoulder or shoulders[0]
        if wrist and wrist[1] < shoulder[1] - margin and (elbow is None or wrist[1] < elbow[1]):
            raised += 1
    return raised


def arms_out(person):
    """T-pose: both wrists roughly level with the shoulders and far out to the sides."""
    parts = {n: _point(person, n) for n in ('left_wrist', 'right_wrist', 'left_shoulder', 'right_shoulder')}
    if not all(parts.values()):
        return False
    width = abs(parts['left_shoulder'][0] - parts['right_shoulder'][0])
    span = abs(parts['left_wrist'][0] - parts['right_wrist'][0])
    level = all(abs(parts[s + '_wrist'][1] - parts[s + '_shoulder'][1]) < max(.05, width * .8) for s in ('left', 'right'))
    return width > 0 and span > width * 2.2 and level


def hands_on_head(person):
    """Both wrists near the head: at head height, not stretched up above it."""
    head = _point(person, 'nose', .3) or _point(person, 'left_eye', .3) or _point(person, 'right_eye', .3)
    wrists = [p for p in (_point(person, 'left_wrist'), _point(person, 'right_wrist')) if p]
    shoulders = [p for p in (_point(person, 'left_shoulder'), _point(person, 'right_shoulder')) if p]
    if not head or len(wrists) < 2 or not shoulders:
        return False
    width = max(.03, abs(shoulders[0][0] - shoulders[-1][0]))
    top = head[1] - width * .9  # Hands straight up go well above this.
    return all(abs(w[0] - head[0]) < width * 1.3 and top < w[1] < shoulders[0][1] for w in wrists)


def flexing(person):
    """'Show me your beefy arm': an elbow out at shoulder height with the wrist up above it."""
    for side in ('left', 'right'):
        wrist, elbow, shoulder = (_point(person, side + part) for part in ('_wrist', '_elbow', '_shoulder'))
        if wrist and elbow and shoulder:
            if abs(elbow[1] - shoulder[1]) < .08 and wrist[1] < elbow[1] - .03:
                return True
    return False


def movement(previous, current):
    """Mean keypoint displacement between two detections of the same person (for 'freeze')."""
    moved = [math.dist(a[:2], b[:2]) for a, b in zip(previous['keypoints'], current['keypoints'])
             if a[2] >= .4 and b[2] >= .4]
    scale = max(.05, current['box'][2] - current['box'][0])
    return (sum(moved) / len(moved) / scale) if moved else None
