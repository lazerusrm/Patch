"""Porch zones from the G4 doorbell view, measured on real walks 2026-10-24.

G4 footpoint y (box bottom, normalized): the walkway climbs from about .62 at
the sidewalk end to .80 at the porch edge; people standing at the pumpkin are
about .82-.95; at the door the box is clipped by the frame bottom (>= .95).
Frames arrive about once a second with frequent single-frame misses, so every
decision tolerates gaps and uses the nearest (largest y) person.
"""
from collections import deque


class PorchZones:
    def __init__(self, porch=.80, door=.95, gap=2.5, forget=12):
        self.porch, self.door, self.gap, self.forget = porch, door, gap, forget
        self.history = deque(maxlen=12)  # (stamp, y) of nearest person; y is None for an empty frame.
        self.last_person = float('-inf')
        self.last_frame = float('-inf')
        self.peak = None           # deepest y reached during this visit
        self.door_since = None
        self.leaving_at = None
        self.candidate = None      # (stamp, y) first downhill path frame, awaiting confirmation
        self.zone = None

    def zone_of(self, y):
        return None if y is None else 'door' if y >= self.door else 'porch' if y >= self.porch else 'path'

    def observe(self, points, stamp):
        """points: [(x, y, height)] from PorchCrossing.people. Returns list of new events."""
        if stamp <= self.last_frame:
            return []
        self.last_frame = stamp
        events = []
        nearest = max(points, key=lambda p: p[1], default=None)
        y = nearest[1] if nearest else None
        x = nearest[0] if nearest else None
        self.history.append((stamp, y))
        if y is None:
            if self.candidate and stamp - self.candidate[0] >= 1.5 and self.leaving_at is None:
                self.leaving_at = self.candidate[0]  # Walked down the path and out of view.
                self.candidate = None
                events.append('leaving')
            if stamp - self.last_person > self.forget:
                self.peak = self.door_since = self.leaving_at = self.candidate = None
                self.zone = None
            elif stamp - self.last_person > self.gap:
                self.zone = None
                self.door_since = None
            return events
        if self.peak is None:
            events.append('approach')
        self.last_person = stamp
        previous = self.zone
        self.zone = self.zone_of(y)
        if self.zone == 'door':
            if self.door_since is None:
                self.door_since = stamp
        else:
            self.door_since = None
        self.peak = y if self.peak is None else max(self.peak, y)
        recent = [value for at, value in self.history if value is not None and stamp - at <= 5]
        # Clearly down the walkway (hysteresis below the porch edge), not the frame edges.
        on_path = y <= self.porch - .04 and .4 <= x <= .82
        if self.candidate and on_path and y <= self.candidate[1] + .03 and self.leaving_at is None:
            self.leaving_at = self.candidate[0]
            self.candidate = None
            events.append('leaving')
        elif (on_path and self.leaving_at is None and self.candidate is None
                and self.peak >= self.porch + .04 and recent and max(recent) - y >= .08):
            self.candidate = (stamp, y)
        elif y >= self.porch + .03:
            self.candidate = None
            if self.leaving_at is not None:
                self.leaving_at = None  # Came back up.
                events.append('returned')
        if self.zone == 'door' and previous != 'door':
            events.append('door')
        return events

    def fresh(self, now):
        return now - self.last_frame <= 3

    def at_door_for(self, now):
        if self.door_since is None or now - self.last_person > self.gap:
            return 0
        return now - self.door_since

    def departing(self, now):
        """Walked back down the path after reaching the porch, and nobody is near now."""
        if self.leaving_at is None or now - self.leaving_at > 15:
            return False
        nearest = next((value for _, value in reversed(self.history) if value is not None), None)
        return nearest is None or nearest < self.porch

    def present(self, now):
        return now - self.last_person <= self.gap

    def near(self, now):
        return self.present(now) and self.zone in ('porch', 'door')
