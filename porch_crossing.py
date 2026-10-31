"""Anonymous, short-lived footpoint tracks; loss of detection is never an exit."""
import math


class PorchCrossing:
    # Candidate geometry from the G4 view. Enable actions only after a walk test.
    def __init__(self, x1=.48, x2=.74, y=.78, margin=.025):
        if not (0 <= x1 < x2 <= 1 and 0 < margin < y < 1 - margin):
            raise ValueError('Invalid porch gate')
        self.x1, self.x2, self.y, self.margin = x1, x2, y, margin
        self.tracks = []
        self.last_frame = float('-inf')
        self.last_person = float('-inf')
        self.departing = False
        self.uncertain = False
        self.near_count = 0
        self.state = 'clear'

    @staticmethod
    def people(boxes):
        """Hailo NMS: ymin, xmin, ymax, xmax, confidence; exclude street/sky."""
        result = []
        for box in boxes:
            if len(box) < 5 or not all(math.isfinite(float(v)) for v in box[:5]):
                continue
            top, left, bottom, right, score = map(float, box[:5])
            x = (left + right) / 2
            if (score >= .55 and 0 <= top < bottom <= 1 and 0 <= left < right <= 1
                    and (bottom - top) * (right - left) >= .012
                    and .32 <= x <= .96 and bottom >= .63):
                result.append((x, bottom, bottom - top))
        return result[:16]

    def observe(self, boxes, now):
        if now <= self.last_frame:
            return []  # Never count a cached frame twice.
        if now - self.last_frame > 3:
            self.tracks.clear()
            self.departing = False
            self.uncertain = False
        self.last_frame = now
        points = self.people(boxes)
        self.near_count = sum(y > self.y - self.margin for _, y, _ in points)
        if points:
            self.last_person = now
        elif now - self.last_person > 10:
            self.tracks.clear()
            self.departing = False
            self.uncertain = False
        expired = [t for t in self.tracks if now - t['seen'] > 3]
        if any(t['side'] == 1 for t in expired):
            self.uncertain = True  # A person vanished behind the column, not an exit.
        self.tracks = [t for t in self.tracks if now - t['seen'] <= 3]
        # ponytail: tiny groups use nearest footpoints; ambiguous matches lose continuity.
        candidates = []
        for point in points:
            x, y, height = point
            distances = sorted((math.hypot(x - t['x'], y - t['y']), i)
                               for i, t in enumerate(self.tracks)
                               if .3 <= height / t['height'] <= 3.3)
            limit = min(.4, .12 + .22 * max(.05, now - self.tracks[distances[0][1]]['seen'])) if distances else 0
            candidates.append(distances[0][1] if distances and distances[0][0] < limit
                              and (len(distances) == 1 or distances[1][0] - distances[0][0] > .04)
                              else None)
        events = []
        for point, index in zip(points, candidates):
            x, y, height = point
            side = 1 if y > self.y + self.margin else -1 if y < self.y - self.margin else 0
            if index is None or candidates.count(index) != 1:
                track = dict(x=x, y=y, height=height, seen=now, side=side, pending=side, hits=0,
                             stable_x=x, stable_y=y)
                self.tracks.append(track)
            else:
                track = self.tracks[index]
            track.update(x=x, y=y, height=height, seen=now)
            if not side:
                track.update(pending=0, hits=0)
                continue
            track['hits'] = track['hits'] + 1 if track['pending'] == side else 1
            track['pending'] = side
            # At1Hz a walker can occupy each side for only one frame. The two
            # observations across the hysteresis band establish the crossing.
            if track['side'] and track['side'] != side:
                old_y, old_x = track['stable_y'], track['stable_x']
                crossing_x = old_x + (x - old_x) * (self.y - old_y) / (y - old_y)
                if self.x1 <= crossing_x <= self.x2:
                    events.append('arriving' if side == 1 else 'leaving')
            track.update(side=side, stable_x=x, stable_y=y)
        self.tracks = self.tracks[-32:]
        # Require a measured outward crossing and no remaining or unaccounted visitor.
        if 'leaving' in events:
            self.departing = True
        if ('arriving' in events or self.uncertain or any(y > self.y - self.margin for _, y, _ in points)
                or any(t['side'] == 1 for t in self.tracks)):
            self.departing = False
        occupied = self.near_count or any(t['side'] == 1 for t in self.tracks)
        self.state = ('at_doorstep' if occupied else 'uncertain' if self.uncertain else
                      'leaving' if self.departing else 'approaching' if points else 'clear')
        return events
