"""Pure event logic for the UniFi Protect -> PumpkinTalk bridge (no I/O)."""
from __future__ import annotations
import json, os, tempfile, time
from dataclasses import dataclass, field
from datetime import datetime, timezone

def iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def _s(v):
    return None if v is None else float(v) / 1000.0

def normalize(msg: dict, cameras: dict[str, str]) -> list[dict]:
    """subscribe/events websocket message -> zero or more contract events.

    Types: doorbell.ring, person.detected, person.ended, motion.started, motion.ended,
    plus smart.detected (non-person object), smart.line, smart.audio, protect.<type>.
    Each candidate carries a dedupe key (upstream id + type)."""
    item = msg.get("item") or {}
    if item.get("modelKey") != "event" or not item.get("id"):
        return []
    pt, add = item.get("type") or "unknown", msg.get("type") == "add"
    smart = list(item.get("smartDetectTypes") or [])
    start, end = _s(item.get("start")), _s(item.get("end"))
    out = []
    def ev(t, when):
        out.append({"id": f"{item['id']}:{t}", "upstream_id": item["id"], "type": t,
                    "camera_id": item.get("device"), "camera_name": cameras.get(item.get("device")),
                    "occurred_ts": when or time.time(), "start_ts": start,
                    "zone": item.get("zone") or item.get("zones"),
                    "smart_types": smart or None, "protect_type": pt})
    if pt == "ring":
        if add: ev("doorbell.ring", start)
    elif pt == "motion":
        if add: ev("motion.started", start)
        if end is not None: ev("motion.ended", end)
    elif pt in ("smartDetectZone", "smartDetectLoiterZone"):
        if "person" in smart:
            # person may be added to an already-running event by a later 'update'; stamp it now so it isn't dropped as stale
            ev("person.detected", start if add or start is None or time.time() - start < 10 else time.time())
            if end is not None: ev("person.ended", end)
        elif add: ev("smart.detected", start)
    elif pt == "smartDetectLine":
        if add: ev("smart.line", start)
    elif pt == "smartAudioDetect":
        if add: ev("smart.audio", start)
    elif add:
        ev("protect." + pt, start)
    return out

@dataclass
class Gate:
    """Dedupe (persisted), stale expiry, ring-burst suppression, replay protection."""
    state_path: str | None = None
    stale_after_s: float = 30.0
    ring_burst_s: float = 15.0
    keep_s: float = 6 * 3600
    seen: dict = field(default_factory=dict)
    last_ring: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.state_path and os.path.exists(self.state_path):
            try:
                d = json.load(open(self.state_path))
                self.seen, self.last_ring = d.get("seen", {}), d.get("last_ring", {})
            except Exception:
                pass

    def save(self):
        if not self.state_path:
            return
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.state_path) or ".")
        with os.fdopen(fd, "w") as f:
            json.dump({"seen": self.seen, "last_ring": self.last_ring}, f)
        os.replace(tmp, self.state_path)

    def check(self, ev: dict, now: float | None = None) -> tuple[bool, str]:
        now = time.time() if now is None else now
        for k, t in list(self.seen.items()):
            if now - t > self.keep_s:
                del self.seen[k]
        if ev["id"] in self.seen:
            return False, "duplicate"
        self.seen[ev["id"]] = now
        try:
            if now - ev["occurred_ts"] > self.stale_after_s:
                return False, "stale"
            if ev["type"] == "doorbell.ring":
                cam, last = ev["camera_id"], self.last_ring.get(ev["camera_id"])
                if last is not None and 0 <= ev["occurred_ts"] - last < self.ring_burst_s:
                    return False, "ring_burst"
                self.last_ring[cam] = ev["occurred_ts"]
            return True, "ok"
        finally:
            self.save()

def public(ev: dict, seq: int, received: float) -> dict:
    e = {k: v for k, v in ev.items() if k not in ("occurred_ts", "start_ts")}
    e.update(seq=seq, occurred_at=iso(ev["occurred_ts"]), received_at=iso(received))
    return e

def validate_wav(data: bytes, max_s=20.0, max_bytes=1_000_000):
    """Return (ok, error). Requires RIFF/WAVE PCM16 mono 24000 Hz."""
    import io, wave
    if len(data) > max_bytes:
        return False, "too large (max 1MB)"
    try:
        w = wave.open(io.BytesIO(data))
    except Exception:
        return False, "not a WAV file"
    if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, 24000) or w.getcomptype() != "NONE":
        return False, "must be mono PCM16 24000 Hz"
    if w.getnframes() / 24000 > max_s:
        return False, "too long (max 20s)"
    return True, None
