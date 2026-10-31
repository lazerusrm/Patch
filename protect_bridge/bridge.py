"""UniFi Protect -> PumpkinTalk bridge, contract v1 (+ live stream).

Primary: GET /events/stream  (SSE; resume with Last-Event-ID or ?after=<cursor>)
Compat : GET /events?after=latest|<cursor>   (contract v1 polling, same cursors)
Also   : GET /health, GET /snapshot?camera_id=, POST/GET/DELETE /audio, POST /chime
Audio is played ONLY when the controller POSTs it. The bridge never self-initiates sound.
"""
from __future__ import annotations
import argparse, asyncio, collections, hmac, json, logging, os, socket, ssl, time, uuid
from urllib.parse import urlsplit
import aiohttp
from aiohttp import web
from .core import Gate, normalize, public, validate_wav, iso

log = logging.getLogger("protect_bridge")
CFG = os.path.expanduser("~/.config/pumpkin-protect")
DOORBELL = "6a8e3fd302019203e40008c1"
BATCH = 50
# Doorbell speaker is very quiet and its volume is not settable via Integration API: compress + make-up + limit.
# Limiter 0.62 (was 0.89; HAL 2026-10-24 option C): 0.89 hit 0 dBFS / up to +1.7 dBTP after Opus 48k/96k encode + 24 kHz decode; 0.62 keeps decoded Opus <= -1.6 dBTP on loud test material.
LIVE_AF = "highpass=f=180,acompressor=threshold=-24dB:ratio=8:attack=5:release=80:makeup=14,alimiter=limit=0.62:level=false"
# Minimum quiet time between the end of one bridge talkback session and the start of the next, so the G4
# finishes playing out the previous tail before a new session can preempt it (HAL transport review 2026-10-24).
SESSION_GAP_S = 1.0
# Clips are encoded first, then each 20 ms RTP packet is sent on its own clock. ffmpeg's -readrate released
# the WAV in ~85 ms blocks (4 packets, then a gap) with no head start, and the G4's small talkback buffer
# ran dry in the gaps: audible hitching on sustained sounds (the ding-dong) and crackle on speech.
PACE_LEAD_S = float(os.environ.get("DOORBELL_PACE_LEAD_S", "0.06"))  # packets stay this far ahead of playback
READRATE_BURST = "0.001"  # live talk only  # effectively no initial burst (0 means default 0.5 s in ffmpeg 8)
RTP_PT = "97"   # Opus dynamic PT; ffmpeg already picked 97 implicitly, now explicit
# Compact input (HAL 2026-10-24): optional Ogg Opus upload on POST /audio, decoded in memory to mono PCM16 24 kHz.
OGG_TYPES = ("audio/ogg", "audio/opus", "application/ogg")
WAV_TYPES = ("audio/wav", "audio/x-wav", "audio/wave")
MAX_BODY = 1_000_000
MAX_AUDIO_S = 20.0
DECODE_TIMEOUT_S = 5.0          # wall-time bound for the ffmpeg decode
DECODE_CONCURRENCY = 2

class DecodeError(Exception):
    def __init__(self, status, msg): super().__init__(msg); self.status = status

def pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    import io, wave
    b = io.BytesIO(); w = wave.open(b, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
    w.writeframes(pcm); w.close(); return b.getvalue()

def ogg_opus_header_ok(data: bytes) -> bool:
    """Cheap structural check before spawning a decoder: first Ogg page must be a BOS page carrying OpusHead."""
    return len(data) >= 47 and data[:4] == b"OggS" and data[4] == 0 and (data[5] & 0x02) and data[28:36] == b"OpusHead"

async def decode_ogg_opus(data: bytes, max_s: float = MAX_AUDIO_S, timeout: float = DECODE_TIMEOUT_S) -> bytes:
    """Decode Ogg Opus bytes -> raw mono PCM16 24 kHz, fully in memory via pipes.
    Forced Ogg demuxer + Opus decoder, pipe-only protocol whitelist, bounded output size and wall time.
    Raises DecodeError(status, msg)."""
    if not ogg_opus_header_ok(data): raise DecodeError(415, "not an Ogg Opus stream (expected OggS page with OpusHead)")
    limit = int(max_s * 24000) * 2
    p = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror",
        "-protocol_whitelist", "pipe", "-f", "ogg", "-c:a", "libopus", "-i", "pipe:0",
        "-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", "-f", "s16le",
        "-protocol_whitelist", "pipe", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out = bytearray(); too_long = False
    async def feed():
        try:
            p.stdin.write(data); await p.stdin.drain()
        except (BrokenPipeError, ConnectionResetError): pass
        finally:
            try: p.stdin.close()
            except Exception: pass
    async def drain_out():
        nonlocal too_long
        while True:
            chunk = await p.stdout.read(65536)
            if not chunk: return
            out.extend(chunk)
            if len(out) > limit + 480:   # allow <=10 ms rounding slack
                too_long = True; return
    async def drain_err():
        return await p.stderr.read(4096)
    try:
        res = await asyncio.wait_for(asyncio.gather(feed(), drain_out(), drain_err()), timeout)
        err = res[2]
        if too_long: raise DecodeError(413, f"too long (max {max_s:g}s decoded)")
        rc = await asyncio.wait_for(p.wait(), timeout)
    except asyncio.TimeoutError:
        raise DecodeError(400, f"decode timed out (>{timeout:g}s)")
    finally:
        if p.returncode is None:
            try: p.kill()
            except ProcessLookupError: pass
            await p.wait()
    if rc != 0: raise DecodeError(400, "malformed Ogg Opus: " + err.decode(errors="replace").strip().splitlines()[-1][:120] if err.strip() else "malformed Ogg Opus")
    if len(out) < 2: raise DecodeError(400, "Ogg Opus decoded to no audio")
    if len(out) > limit: del out[limit:]       # trim the <=10 ms slack
    if len(out) % 2: del out[-1]
    return bytes(out)

LOUD = "highpass=f=180,acompressor=threshold=-24dB:ratio=8:attack=5:release=80:makeup=14,alimiter=limit=0.62:level=false"

def resize_jpeg(body: bytes, width: int, quality: int = 80):
    """Downscale a JPEG to `width` (aspect kept; never upscales). Pure in-memory; nothing is stored."""
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(body)); src = im.size
    if width >= src[0]: return body, src, src
    dst = (width, max(1, round(src[1] * width / src[0])))
    im.draft("RGB", dst)  # fast DCT-domain downscale during decode
    im = im.convert("RGB").resize(dst, Image.BILINEAR)
    out = io.BytesIO(); im.save(out, "JPEG", quality=quality)
    return out.getvalue(), src, dst

class Bridge:
    def __init__(self, a):
        self.base = f"https://{a.protect_host}/proxy/protect/integration/v1"
        self.key = open(a.api_key_file).read().strip()
        self.token = open(a.token_file).read().strip()
        self.gate = Gate(state_path=a.state_file, stale_after_s=a.stale_after, ring_burst_s=a.ring_burst)
        self.instance = uuid.uuid4().hex[:12]
        self.doorbell = a.doorbell_id
        self.cameras: dict[str, str] = {}
        self.chimes: list[dict] = []
        self.buf = collections.deque(maxlen=200)
        self.seq = 0
        self.cond = asyncio.Condition()
        self.ws_connected = False
        self.counts = collections.Counter()
        self.audio: dict[str, dict] = {}       # id -> job
        self.audio_lock = asyncio.Lock()
        self.decode_sem = asyncio.Semaphore(DECODE_CONCURRENCY)
        self.current = None                    # active job id
        self.live = None                       # active live-stream state
        self.session_end = 0.0                 # time.monotonic() when the last talkback session ended
        self.sx = ssl.create_default_context(); self.sx.check_hostname = False; self.sx.verify_mode = ssl.CERT_NONE

    # ---------- upstream ----------
    def H(self): return {"X-API-KEY": self.key}

    async def refresh(self, s):
        async with s.get(self.base + "/cameras", headers=self.H(), ssl=self.sx) as r:
            r.raise_for_status(); self.cameras = {c["id"]: c.get("name") or c["id"] for c in await r.json()}
        async with s.get(self.base + "/chimes", headers=self.H(), ssl=self.sx) as r:
            if r.status == 200: self.chimes = await r.json()

    async def ingest(self, msg, via="ws"):
        for ev in normalize(msg, self.cameras):
            ok, why = self.gate.check(ev); self.counts[why] += 1
            log.info("%s %s %s cam=%s -> %s", via, ev["type"], ev["upstream_id"], ev["camera_name"], why)
            if ok:
                async with self.cond:
                    self.seq += 1
                    self.buf.append(public(ev, self.seq, time.time())); self.cond.notify_all()

    async def ws_loop(self):
        backoff = 1
        async with aiohttp.ClientSession() as s:
            while True:
                try:
                    await self.refresh(s)
                    async with s.ws_connect(self.base + "/subscribe/events", headers=self.H(), ssl=self.sx, heartbeat=20) as ws:
                        self.ws_connected, backoff = True, 1
                        log.info("event websocket connected (%d cameras)", len(self.cameras))
                        async for m in ws:
                            if m.type == aiohttp.WSMsgType.TEXT:
                                try: await self.ingest(json.loads(m.data))
                                except Exception: log.exception("bad event message")
                except asyncio.CancelledError: raise
                except Exception as e: log.warning("websocket error: %s", type(e).__name__)
                self.ws_connected = False
                await asyncio.sleep(backoff); backoff = min(backoff * 2, 30)

    # ---------- cursors ----------
    def cursor(self, seq=None): return f"{self.instance}.{self.seq if seq is None else seq}"

    def parse(self, c):
        """-> (seq, reset_reason|None)"""
        if c in (None, "", "latest"): return self.seq, None
        try: inst, n = c.split("."); n = int(n)
        except Exception: return self.seq, "bad_cursor"
        if inst != self.instance: return self.seq, "bridge_restarted"
        oldest = self.buf[0]["seq"] if self.buf else self.seq + 1
        if n < oldest - 1 or n > self.seq: return self.seq, "cursor_expired"
        return n, None

    # ---------- http ----------
    @web.middleware
    async def auth(self, req, handler):
        t = req.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not t or not hmac.compare_digest(t, self.token):
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(req)

    async def health(self, req):
        return web.json_response({
            "ready": self.ws_connected, "instance_id": self.instance, "cursor": self.cursor(),
            "targets": ["doorbell"],
            "capabilities": {"events": True, "events_stream": True, "snapshot": True, "audio": True,
                             "audio_cancel": True, "audio_live": True, "microphone": False, "owner_talkback_detection": False,
                             "chime_audio": False, "chime_tones": False,
                             "audio_compact": True},
            "audio_input": {"content_types": list(WAV_TYPES + OGG_TYPES), "max_bytes": MAX_BODY, "max_seconds": MAX_AUDIO_S,
                            "wav": "mono PCM16 24000 Hz", "ogg": "Ogg Opus (any rate/channels) decoded to mono PCM16 24000 Hz"},
            "chime": {"present": bool(self.chimes), "model": [c.get("type") for c in self.chimes],
                      "remote_play": False, "sounds": [], "ringtone_select": True, "ringtone_upload": True},
            "cameras": self.cameras, "audio_active": self.current, "counts": dict(self.counts)})

    async def events(self, req):
        after = req.query.get("after", "latest")
        if after == "latest":
            return web.json_response({"cursor": self.cursor(), "events": []})
        n, reset = self.parse(after)
        if reset:
            return web.json_response({"cursor": self.cursor(), "events": [], "reset": True, "reason": reset})
        evs = [e for e in self.buf if e["seq"] > n][:BATCH]
        return web.json_response({"cursor": self.cursor(evs[-1]["seq"] if evs else n), "events": evs})

    async def stream(self, req):
        n, reset = self.parse(req.headers.get("Last-Event-ID") or req.query.get("after", "latest"))
        r = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await r.prepare(req)
        if reset:
            await r.write(f"event: reset\nid: {self.cursor()}\ndata: {json.dumps({'reason': reset})}\n\n".encode())
        while True:
            for e in [e for e in self.buf if e["seq"] > n]:
                await r.write(f"id: {self.cursor(e['seq'])}\nevent: {e['type']}\ndata: {json.dumps(e)}\n\n".encode())
                n = e["seq"]
            async with self.cond:
                try: await asyncio.wait_for(self.cond.wait_for(lambda: self.seq > n), 15)
                except asyncio.TimeoutError: await r.write(b": keepalive\n\n")

    async def fetch_snapshot(self, cid, hq):
        """One Protect snapshot read. Returns (status, body, started, done) with wall-clock times."""
        q = "?highQuality=true" if hq else ""
        t0 = time.time()
        async with aiohttp.ClientSession() as s, s.get(f"{self.base}/cameras/{cid}/snapshot{q}", headers=self.H(),
                                                       ssl=self.sx, timeout=aiohttp.ClientTimeout(total=8)) as u:
            body = await u.read()
            return u.status, body, t0, time.time()

    async def snapshot(self, req):
        cid = req.query.get("camera_id", self.doorbell)
        if cid not in self.cameras:
            return web.json_response({"error": "unknown camera_id", "cameras": self.cameras}, status=404)
        width = req.query.get("width")
        if width is not None:
            try:
                width = int(width); assert 64 <= width <= 1920
            except Exception:
                return web.json_response({"error": "width must be an integer 64..1920"}, status=400)
        try:
            st, body, t0, ts = await self.fetch_snapshot(cid, bool(req.query.get("hq")))
            if st != 200: return web.json_response({"error": f"unavailable (protect {st})"}, status=503)
        except Exception as e:
            return web.json_response({"error": f"unavailable ({type(e).__name__})"}, status=503)
        h = {"X-Camera-Id": cid, "X-Camera-Name": self.cameras[cid], "X-Captured-At": iso(ts),
             "X-Fetch-Started-At": iso(t0), "X-Fetch-Ms": str(int((ts - t0) * 1000)), "Cache-Control": "no-store"}
        if width:
            try:
                body, src, dst = await asyncio.get_running_loop().run_in_executor(None, resize_jpeg, body, width)
            except Exception as e:
                return web.json_response({"error": f"resize failed ({type(e).__name__})"}, status=503)
            h.update({"X-Source-Size": f"{src[0]}x{src[1]}", "X-Image-Size": f"{dst[0]}x{dst[1]}",
                      "X-Resize-Ms": str(int((time.time() - ts) * 1000))})
        return web.Response(body=body, content_type="image/jpeg", headers=h)

    # ---------- audio ----------
    def job_view(self, j):
        v = {k: j[k] for k in ("id", "state", "target", "camera_id", "input", "error", "timings") if j.get(k) is not None}
        v["request_id"] = j["id"]; return v

    async def _body(self, req, limit=1_000_000):
        data = bytearray()
        while True:
            chunk = await req.content.read(65536)
            if not chunk: return bytes(data)
            data += chunk
            if len(data) > limit: return None

    async def audio_post(self, req):
        rid = req.headers.get("X-Request-ID", "").strip()
        if not rid or len(rid) > 100: return web.json_response({"error": "X-Request-ID required"}, status=400)
        if rid in self.audio: return web.json_response(self.job_view(self.audio[rid]))
        target = req.headers.get("X-Target", "doorbell")
        if target == "chime":
            return web.json_response({"error": "chime audio not supported on this install (Integration API has no chime play; see /health)"}, status=501)
        if target != "doorbell": return web.json_response({"error": "unknown target"}, status=400)
        cam = req.headers.get("X-Camera-ID", self.doorbell)
        if cam != self.doorbell: return web.json_response({"error": "camera not allowed"}, status=403)
        ct = req.content_type
        if ct not in WAV_TYPES and ct not in OGG_TYPES:
            return web.json_response({"error": "Content-Type must be audio/wav or audio/ogg (Opus)"}, status=415)
        data = await self._body(req)
        if data is None: return web.json_response({"error": "too large (max 1MB)"}, status=413)
        decode_ms = None
        if ct in OGG_TYPES:
            t = time.monotonic()
            try:
                async with self.decode_sem: pcm = await decode_ogg_opus(data)
            except DecodeError as e:
                return web.json_response({"error": str(e)}, status=e.status)
            data = pcm_to_wav(pcm); decode_ms = round((time.monotonic() - t) * 1000)
        ok, err = validate_wav(data)
        if not ok: return web.json_response({"error": err}, status=400)
        async with self.audio_lock:
            if rid in self.audio: return web.json_response(self.job_view(self.audio[rid]))  # same id raced in during read/decode
            if self.live is not None:
                return web.json_response({"error": "busy", "active": "live"}, status=409)
            if self.current and self.audio[self.current]["state"] in ("queued", "playing"):
                return web.json_response({"error": "busy", "active": self.current}, status=409)
            j = {"raw": req.headers.get("X-Loudness", "").lower() == "raw", "id": rid, "state": "queued", "target": "doorbell", "camera_id": cam, "timings": {}, "proc": None, "t0": time.time()}
            if decode_ms is not None: j["input"] = "ogg_opus"; j["timings"]["decode_ms"] = decode_ms
            self.audio[rid] = j; self.current = rid
            while len(self.audio) > 50:
                self.audio.pop(next(iter(self.audio)))
        j["task"] = asyncio.create_task(self.play(j, data))
        return web.json_response(self.job_view(j), status=202)

    def _mark_session_end(self):
        self.session_end = time.monotonic()

    async def _session_gap(self, cancelled=lambda: False):
        """Wait until SESSION_GAP_S has passed since the previous talkback session ended.
        Returns False (without opening anything) if cancelled() becomes true while waiting."""
        while True:
            if cancelled(): return False
            rem = self.session_end + SESSION_GAP_S - time.monotonic()
            if rem <= 0: return True
            await asyncio.sleep(min(rem, 0.05))

    async def _open_session(self, cam, kind):
        async with aiohttp.ClientSession() as s, s.post(f"{self.base}/cameras/{cam}/talkback-session",
                                                        headers=self.H(), ssl=self.sx, timeout=aiohttp.ClientTimeout(total=8)) as r:
            sess = await r.json()
            if r.status != 200 or not str(sess.get("url", "")).startswith("rtp://"):
                raise RuntimeError(f"talkback-session {r.status}")
        try: port = urlsplit(sess["url"]).port
        except Exception: port = None
        # non-secret metadata only (no host/key/token)
        log.info("talkback session %s: device codec=%s samplingRate=%s bits=%s port=%s -> sending opus/48000 96k 20ms pt=%s",
                 kind, sess.get("codec"), sess.get("samplingRate"), sess.get("bitsPerSample"), port, RTP_PT)
        return sess

    async def play(self, j, data):
        opened = False
        try:
            g0 = time.monotonic()
            if not await self._session_gap(lambda: j["state"] == "cancelled"): return
            j["timings"]["gap_wait_ms"] = round((time.monotonic() - g0) * 1000)
            sess = await self._open_session(j["camera_id"], "clip"); opened = True
            j["timings"]["session_ms"] = round((time.time() - j["t0"]) * 1000)
            if j["state"] == "cancelled": return
            rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            rx.bind(("127.0.0.1", 0)); rx.setblocking(False)
            local = rx.getsockname()[1]
            p = await asyncio.create_subprocess_exec(
                # Encode as fast as possible into a local socket (RTCP too); _send_paced does the timing.
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
                *([] if j.get("raw") else ["-af", LOUD]),
                "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "96k", "-application", "audio", "-frame_duration", "20",
                "-payload_type", RTP_PT, "-f", "rtp", f"rtp://127.0.0.1:{local}?rtcpport={local}&pkt_size=1200",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            j["proc"] = p
            if j["state"] == "cancelled":
                p.kill(); await p.wait(); rx.close(); return
            j["state"] = "playing"
            j["timings"]["stream_start_ms"] = round((time.time() - j["t0"]) * 1000)
            # Encoding runs far faster than real time, so sending starts with the first packets.
            loop = asyncio.get_running_loop(); queue = asyncio.Queue()
            async def collect():
                while True: queue.put_nowait(await loop.sock_recv(rx, 2048))
            collector = asyncio.create_task(collect())
            sender = asyncio.create_task(self._send_paced(j, queue, sess["url"]))
            try:
                _, err = await p.communicate(data)
                j["timings"]["encode_ms"] = round((time.time() - j["t0"]) * 1000) - j["timings"]["stream_start_ms"]
                await asyncio.sleep(0.02)  # local datagrams still in flight
            finally:
                collector.cancel()
                try: await collector
                except (asyncio.CancelledError, OSError): pass
                rx.close()
                queue.put_nowait(None)
            await sender
            j["timings"]["finished_ms"] = round((time.time() - j["t0"]) * 1000)
            if j["state"] == "cancelled": return
            if p.returncode == 0: j["state"] = "finished"
            else: j["state"], j["error"] = "failed", f"ffmpeg exit {p.returncode}"
        except Exception as e:
            if j["state"] != "cancelled": j["state"], j["error"] = "failed", str(e)[:120]
        finally:
            if opened: self._mark_session_end()
            log.info("audio %s -> %s %s", j["id"], j["state"], j["timings"])

    async def _send_paced(self, j, queue, url):
        """Send RTP on the media clock, PACE_LEAD_S ahead; stops on cancel. None ends."""
        target = urlsplit(url); host, port = target.hostname, target.port
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ts0 = start = None; late = 0.0; offset = 0.0
        try:
            while (pkt := await queue.get()) is not None:
                if j["state"] == "cancelled": return
                if len(pkt) > 1 and 200 <= pkt[1] <= 204:
                    # RTCP from a faster-than-real-time encode maps the media clock to the wrong wall
                    # time (~40x); forwarding it confused the G4's playout. Send RTP only.
                    continue
                if len(pkt) <= 12: continue
                ts = int.from_bytes(pkt[4:8], "big")
                if ts0 is None: ts0, start = ts, time.monotonic()
                offset = ((ts - ts0) & 0xFFFFFFFF) / 48000
                wait = start + offset - PACE_LEAD_S - time.monotonic()
                if wait > 0: await asyncio.sleep(wait)
                elif offset >= PACE_LEAD_S: late = max(late, -wait)  # (the head start is sent at once)
                tx.sendto(pkt, (host, port))
            if start is None: return
            j["timings"]["max_late_ms"] = round(late * 1000)
            rest = start + offset + 0.02 - time.monotonic()  # until the last frame has played
            if rest > 0 and j["state"] != "cancelled": await asyncio.sleep(rest)
        finally:
            tx.close()

    async def audio_get(self, req):
        i = req.match_info["id"]; j = self.audio.get(req.headers.get("X-Request-ID", "") if i == "-" else i)
        return web.json_response(self.job_view(j)) if j else web.json_response({"error": "not found"}, status=404)

    async def audio_del(self, req):
        i = req.match_info["id"]; j = self.audio.get(req.headers.get("X-Request-ID", "") if i == "-" else i)
        if not j: return web.json_response({"error": "not found"}, status=404)
        if j["state"] in ("queued", "playing"):
            j["state"] = "cancelled"
            if j.get("proc") and j["proc"].returncode is None: j["proc"].terminate(); self._mark_session_end()
        return web.json_response(self.job_view(j))


    # ---------- live talk (WebSocket /audio/live) ----------
    async def _cancel_clip(self):
        j = self.audio.get(self.current) if self.current else None
        if j and j["state"] in ("queued", "playing"):
            j["state"] = "cancelled"; j["error"] = "barge-in by live stream"
            if j.get("proc") and j["proc"].returncode is None: j["proc"].kill(); self._mark_session_end()
            return j["id"]

    async def _live_open(self, rate):
        await self._session_gap()
        sess = await self._open_session(self.doorbell, "live")
        return await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-fflags", "nobuffer", "-flags", "low_delay",
            "-probesize", "32", "-analyzeduration", "0", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0",
            "-af", LIVE_AF, "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "96k", "-application", "audio",
            "-frame_duration", "20", "-flush_packets", "1", "-payload_type", RTP_PT, "-f", "rtp", sess["url"],
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)

    async def live_ws(self, req):
        """Binary frames = raw PCM16 LE mono at ?rate=24000|48000 (default 24000), any size (20 ms recommended).
        Text 'flush' = end of utterance (session kept warm for ?idle=s, default 4 s, max 15). Text 'close' = stop now."""
        rate = int(req.query.get("rate", 24000))
        idle = min(float(req.query.get("idle", 4)), 15.0)
        if rate not in (24000, 48000): return web.json_response({"error": "rate must be 24000 or 48000"}, status=400)
        if self.live is not None: return web.json_response({"error": "busy", "active": "live"}, status=409)
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=256 * 1024)
        await ws.prepare(req)
        st = self.live = {"proc": None, "last": time.time(), "bytes": 0, "sessions": 0, "rate": rate}
        silence = b"\0\0" * (rate // 50)  # 20 ms
        async def keepwarm():
            # while a session is open and the client is silent, feed 20 ms silence so the encoder keeps pacing; close when idle
            while True:
                await asyncio.sleep(0.02)
                p = st["proc"]
                if p is None: continue
                gap = time.time() - st["last"]
                if gap > idle:
                    await self._live_close(st); await ws.send_json({"event": "session_closed", "reason": "idle"})
                elif gap > 0.06:
                    try: p.stdin.write(silence)
                    except Exception: pass
        kw = asyncio.create_task(keepwarm())
        try:
            async for m in ws:
                if m.type == aiohttp.WSMsgType.BINARY:
                    if st["proc"] is not None and st["proc"].returncode is not None:
                        st["fails"] = st.get("fails", 0) + 1; st["proc"] = None
                        if st["fails"] >= 3:
                            await ws.send_json({"event": "error", "error": "encoder keeps exiting"}); break
                    if st["proc"] is None:
                        t0 = time.time()
                        cancelled = await self._cancel_clip()
                        try: st["proc"] = await self._live_open(rate)
                        except Exception as e:
                            await ws.send_json({"event": "error", "error": str(e)[:120]}); continue
                        st["sessions"] += 1
                        await ws.send_json({"event": "session_open", "open_ms": round((time.time() - t0) * 1000),
                                            **({"cancelled_clip": cancelled} if cancelled else {})})
                    st["last"] = time.time(); st["bytes"] += len(m.data)
                    try:
                        st["proc"].stdin.write(m.data); await st["proc"].stdin.drain()
                    except (BrokenPipeError, ConnectionResetError): pass
                elif m.type == aiohttp.WSMsgType.TEXT:
                    if m.data == "close": break
                    if m.data == "flush": await ws.send_json({"event": "flushed", "warm_s": idle})
        finally:
            kw.cancel()
            await self._live_close(st)
            log.info("live stream ended bytes=%d sessions=%d", st["bytes"], st["sessions"])
            self.live = None
        return ws

    async def _live_close(self, st):
        p, st["proc"] = st["proc"], None
        if p and p.returncode is None:
            try:
                p.stdin.close(); await asyncio.wait_for(p.wait(), 1.5)
            except Exception:
                p.kill()
        if p: self._mark_session_end()

    # ---------- chime (UP Chime) ----------
    CHIME_DEFAULT = {"ringtoneId": "68ee8976021dc503e40003fe", "volume": 80, "repeatTimes": 1}

    async def _up(self, method, path, **kw):
        async with aiohttp.ClientSession() as s, s.request(method, self.base + path, headers=self.H(), ssl=self.sx,
                                                           timeout=aiohttp.ClientTimeout(total=20), **kw) as r:
            try: body = await r.json()
            except Exception: body = {"raw": (await r.text())[:200]}
            return r.status, body

    def _chime_id(self, req):
        return req.query.get("chime_id") or (self.chimes[0]["id"] if self.chimes else None)

    async def chime_state(self, req):
        st, body = await self._up("GET", f"/chimes/{self._chime_id(req)}")
        return web.json_response({"chime": body, "default": self.CHIME_DEFAULT}, status=st)

    async def ringtones(self, req):
        st, body = await self._up("GET", "/files/ringtones")
        if st == 200:
            body = [{"id": r["id"], "name": r.get("originalName") or r["name"], "size": r.get("size"),
                     "supported_by": r.get("metadata", {}).get("supportedBy"), "default": bool(r.get("metadata", {}).get("isDefault"))} for r in body]
        return web.json_response(body, status=st)

    async def ringtone_upload(self, req):
        if req.content_type not in ("audio/mpeg", "audio/mp3"):
            return web.json_response({"error": "Content-Type must be audio/mpeg (MP3, short clip)"}, status=415)
        name = "".join(c for c in req.query.get("name", "pumpkin_sfx") if c.isalnum() or c in "_-")[:40] or "pumpkin_sfx"
        data = await self._body(req)
        if data is None: return web.json_response({"error": "max 1MB"}, status=413)
        fd = aiohttp.FormData(); fd.add_field("file", data, filename=name + ".mp3", content_type="audio/mpeg")
        st, body = await self._up("POST", "/files/ringtones", data=fd)
        log.info("ringtone upload %s -> %s", name, st)
        return web.json_response(body, status=st)

    async def _set_ring(self, req, ringtone, volume, repeat):
        cid = self._chime_id(req)
        st, ch = await self._up("GET", f"/chimes/{cid}")
        if st != 200: return web.json_response(ch, status=st)
        cam = req.query.get("camera_id", self.doorbell)
        rs = [dict(r) for r in ch.get("ringSettings", [])]
        for r in rs:
            if r["cameraId"] == cam:
                r.update(ringtoneId=ringtone, volume=int(volume), repeatTimes=int(repeat))
        st, body = await self._up("PATCH", f"/chimes/{cid}", json={"ringSettings": rs})
        log.info("chime ringSettings cam=%s ringtone=%s vol=%s rep=%s -> %s", cam, ringtone, volume, repeat, st)
        return web.json_response(body, status=st)

    async def chime_select(self, req):
        b = await req.json()
        rid = b.get("ringtone_id")
        st, tones = await self._up("GET", "/files/ringtones")
        ok_ids = {t["id"] for t in tones if "chime" in t.get("metadata", {}).get("supportedBy", [])} | {self.CHIME_DEFAULT["ringtoneId"]}
        if rid not in ok_ids: return web.json_response({"error": "ringtone_id not a chime-capable ringtone", "allowed": sorted(ok_ids)}, status=400)
        v, n = int(b.get("volume", 80)), int(b.get("repeat_times", 1))
        if not (0 <= v <= 100 and 1 <= n <= 5): return web.json_response({"error": "volume 0-100, repeat_times 1-5"}, status=400)
        return await self._set_ring(req, rid, v, n)

    async def chime_restore(self, req):
        d = self.CHIME_DEFAULT
        return await self._set_ring(req, d["ringtoneId"], d["volume"], d["repeatTimes"])

    async def chime(self, req):
        return web.json_response({"error": "chime remote play not supported by this Protect Integration API; chime only sounds on a real doorbell press with its selected ringtone (see /chime/select)",
                                  "sounds": []}, status=501)

    def app(self):
        a = web.Application(middlewares=[self.auth], client_max_size=2_000_000)
        a.add_routes([web.get("/health", self.health), web.get("/events", self.events), web.get("/events/stream", self.stream),
                      web.get("/snapshot", self.snapshot), web.post("/audio", self.audio_post),
                      web.get("/audio/live", self.live_ws), web.get("/audio/{id}", self.audio_get), web.delete("/audio/{id}", self.audio_del),
                      web.post("/chime", self.chime), web.get("/chime/state", self.chime_state), web.get("/chime/ringtones", self.ringtones), web.post("/chime/ringtones", self.ringtone_upload), web.post("/chime/select", self.chime_select), web.post("/chime/restore", self.chime_restore)])
        async def up(app): app["ws"] = asyncio.create_task(self.ws_loop())
        async def down(app): app["ws"].cancel()
        a.on_startup.append(up); a.on_cleanup.append(down)
        return a

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--protect-host", default="192.168.0.24")
    p.add_argument("--doorbell-id", default=DOORBELL)
    p.add_argument("--api-key-file", default=f"{CFG}/api_key")
    p.add_argument("--token-file", default=f"{CFG}/token")
    p.add_argument("--state-file", default=f"{CFG}/state.json")
    p.add_argument("--bind", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8768)
    p.add_argument("--stale-after", type=float, default=30.0)
    p.add_argument("--ring-burst", type=float, default=15.0)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    web.run_app(Bridge(a).app(), host=a.bind, port=a.port, print=None, access_log=None)

if __name__ == "__main__":
    main()
