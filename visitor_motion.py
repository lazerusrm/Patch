"""Conservative departure cues from existing person boxes, without identity tracking."""
from collections import deque


class VisitorMotion:
    def __init__(self, near_area=.04, allow_retreat=False):
        self.near_area = near_area
        self.allow_retreat = allow_retreat
        self.samples = deque()
        self.absent_since = None
        self.departing = False
        self.was_near = False
        self.generation = None

    def observe(self, boxes, now, generation, active, camera_ok=True):
        if generation != self.generation or not camera_ok or not active:
            self.samples.clear()
            self.was_near = False
            self.departing = False
            self.absent_since = None
            self.generation = generation
        if not camera_ok or not active:
            return False
        areas = [(b[2] - b[0]) * (b[3] - b[1]) for b in boxes if b[4] >= .55]
        areas = [area for area in areas if area >= .012]
        if not areas:
            if self.absent_since is None:
                self.absent_since = now
            self.departing = self.was_near and now - self.absent_since >= 2
            return self.departing
        self.absent_since = None
        area, count = max(areas), len(areas)
        self.was_near = self.was_near or area >= self.near_area
        if self.samples and self.samples[-1][2] != count:
            self.samples.clear()  # Group changes can swap the nearest person.
        self.samples.append((now, area, count))
        while self.samples and now - self.samples[0][0] > 2:
            self.samples.popleft()
        self.departing = (self.allow_retreat and self.was_near and len(self.samples) >= 5
                          and now - self.samples[0][0] >= 1
                          and area < self.samples[0][1] * .6
                          and sum(b[1] < a[1] * .97 for a, b in zip(self.samples, list(self.samples)[1:])) >= 3
                          and all(b[1] <= a[1] * 1.1 for a, b in zip(self.samples, list(self.samples)[1:])))
        return self.departing


class WebcamDeparture:
    """Leaving, from the path webcam (on the path in front of the pumpkin, looking out).

    The nearest visitor's feet (box bottom, 0 top .. 1 bottom) are low in the frame when close and
    rise as they walk away. Measured 2026-10-25: at the pumpkin ~.95-1.0, corner of the path ~.65,
    sidewalk .37-.46. Departing = the nearest person was close, then rose steadily with a shrinking
    box to the middle of the path, or crossed back to the sidewalk line.
    """

    def __init__(self, near=.85, leave=.72, sidewalk=.52, window=1.6):
        self.near, self.leave, self.sidewalk, self.window = near, leave, sidewalk, window
        self.samples = deque()  # (t, feet, height) of the nearest person
        self.peak = None
        self.generation = None
        self.departing = False

    def reset(self, generation=None):
        self.samples.clear()
        self.peak = None
        self.generation = generation
        self.departing = False

    def observe(self, boxes, now, generation, active):
        """boxes: (ymin, xmin, ymax, xmax, score) people at or below the sidewalk line."""
        if generation != self.generation or not active:
            self.reset(generation)
            if not active:
                return False
        people = [b for b in boxes if b[4] >= .4 and b[2] - b[0] >= .08]
        if not people:
            return self.departing
        nearest = max(people, key=lambda b: b[2])
        feet, height = nearest[2], nearest[2] - nearest[0]
        if feet >= self.near:
            self.peak = max(self.peak or 0, feet)
        self.samples.append((now, feet, height))
        while self.samples and now - self.samples[0][0] > self.window:
            self.samples.popleft()
        if self.peak is None:
            return self.departing
        if feet < self.sidewalk:
            # Back to the sidewalk, but only after watching them walk out: a passer-by appearing on the
            # sidewalk while the visitor stands out of view behind the camera is not a departure.
            walked = any(self.sidewalk <= f <= self.leave for _, f, _ in self.samples)  # Seen mid-path.
            self.departing = len(self.samples) >= 3 and self.samples[0][1] - feet >= .2 and walked
            return self.departing
        if len(self.samples) >= 4 and now - self.samples[0][0] >= 1:
            steps = list(zip(self.samples, list(self.samples)[1:]))
            rising = sum(b[1] < a[1] - .005 for a, b in steps)
            shrinking = height < self.samples[0][2] * .8
            self.departing = (feet <= self.leave and rising >= .6 * len(steps) and shrinking
                              and self.samples[0][1] - feet >= .08)
        if feet >= self.near:
            self.departing = False  # Came back.
        return self.departing
