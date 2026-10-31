import asyncio, io, os, sys, tempfile, time, unittest, wave
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from protect_bridge.core import Gate, normalize, validate_wav
C = {"door": "G4 Doorbell"}
def m(kind, eid, pt, start, end=None, smart=None):
    it = {"modelKey": "event", "id": eid, "type": pt, "device": "door", "start": start * 1000}
    if end: it["end"] = end * 1000
    if smart: it["smartDetectTypes"] = smart
    return {"type": kind, "item": it}
def wav(sec=1, rate=24000, ch=1):
    b = io.BytesIO(); w = wave.open(b, "wb"); w.setnchannels(ch); w.setsampwidth(2); w.setframerate(rate)
    w.writeframes(b"\0\0" * ch * int(rate * sec)); w.close(); return b.getvalue()
class T(unittest.TestCase):
    def test_real_ring_shape(self):  # exact live message 2026-10-24 07:48 MT (add carries end)
        msg = {"type":"add","item":{"id":"695c","modelKey":"event","type":"ring","start":1792849686504,"end":1792849696504,"device":"door"}}
        e = normalize(msg, C); self.assertEqual([x["type"] for x in e], ["doorbell.ring"])
    def test_real_person_payloads(self):  # captured live 2026-10-24 07:51 MT (G4 doorbell)
        dev = "6a8e3fd302019203e40008c1"; cams = {dev: "G4 Doorbell"}
        add = {"type":"add","item":{"id":"18811cb6-bc77-4504-8b38-62112ca4cf74","modelKey":"event","type":"smartDetectZone","start":1792849871118,"device":dev,"smartDetectTypes":["person"]}}
        upd = {"type":"update","item":{"id":"18811cb6-bc77-4504-8b38-62112ca4cf74","type":"smartDetectZone","start":1792849871118,"device":dev,"smartDetectTypes":["person"],"modelKey":"event"}}
        end = {"type":"update","item":{"id":"18811cb6-bc77-4504-8b38-62112ca4cf74","type":"smartDetectZone","start":1792849871118,"end":1792849909625,"device":dev,"smartDetectTypes":["person"],"modelKey":"event"}}
        g = Gate(); now = 1792849871.5
        out = [(e["type"], g.check(e, now=now)[1]) for m in (add, upd, end, end) for e in normalize(m, cams)]
        self.assertEqual(out[:2], [("person.detected", "ok"), ("person.detected", "duplicate")])
        self.assertEqual([r for t, r in out if t == "person.ended"], ["ok", "duplicate"])
        self.assertEqual(normalize(add, cams)[0]["camera_name"], "G4 Doorbell")
    def test_late_person_not_stale(self):
        n = time.time(); g = Gate()
        late = m("update", "lp", "smartDetectZone", n - 60, None, ["person"])
        self.assertEqual(g.check(normalize(late, C)[0], now=time.time()), (True, "ok"))
    def test_types(self):
        n = time.time()
        self.assertEqual([x["type"] for x in normalize(m("add","a","motion",n), C)], ["motion.started"])
        self.assertEqual([x["type"] for x in normalize(m("update","a","motion",n,n+5), C)], ["motion.ended"])
        self.assertEqual([x["type"] for x in normalize(m("update","b","smartDetectZone",n,None,["person"]), C)], ["person.detected"])
        self.assertEqual(normalize({"type":"update","item":{"modelKey":"camera","id":"x"}}, C), [])
    def test_gate(self):
        p = os.path.join(tempfile.mkdtemp(), "s.json"); n = time.time(); g = Gate(state_path=p)
        chk = lambda msg, now=n, g=g: g.check(normalize(msg, C)[0], now=now)
        self.assertEqual(chk(m("add","a","ring",n-1)), (True,"ok"))
        self.assertEqual(chk(m("add","a","ring",n-1)), (False,"duplicate"))
        self.assertEqual(chk(m("add","b","ring",n)), (False,"ring_burst"))
        self.assertEqual(chk(m("add","c","motion",n-120)), (False,"stale"))
        g2 = Gate(state_path=p)
        self.assertEqual(chk(m("add","a","ring",n-1), g=g2), (False,"duplicate"))
        self.assertEqual(chk(m("add","z","ring",n+20), n+20, g2), (True,"ok"))
        # person on same event only once
        self.assertEqual(chk(m("update","q","smartDetectZone",n,None,["person"])), (True,"ok"))
        self.assertEqual(chk(m("update","q","smartDetectZone",n,n+3,["person"])), (False,"duplicate"))
    def test_wav(self):
        self.assertEqual(validate_wav(wav()), (True, None))
        self.assertFalse(validate_wav(wav(rate=16000))[0]); self.assertFalse(validate_wav(wav(ch=2))[0])
        self.assertFalse(validate_wav(wav(sec=21))[0]); self.assertFalse(validate_wav(b"junk")[0])
class BridgeHTTP(unittest.IsolatedAsyncioTestCase):
    """REQ-3: playback id == X-Request-ID; GET/DELETE accept it; X-Target chime -> 501; cancel race."""
    async def asyncSetUp(self):
        import argparse
        from aiohttp.test_utils import TestClient, TestServer
        from protect_bridge import bridge as B
        d = tempfile.mkdtemp()
        for f in ("k", "t"): open(os.path.join(d, f), "w").write("secret-" + f)
        a = argparse.Namespace(protect_host="127.0.0.1", api_key_file=f"{d}/k", token_file=f"{d}/t", state_file=f"{d}/s.json",
                               stale_after=30.0, ring_burst=15.0, doorbell_id=B.DOORBELL)
        self.b = B.Bridge(a)
        async def noop(): pass
        self.b.ws_loop = noop
        self.started = []
        async def fake_play(j, data):
            self.started.append(j["id"]); j["state"] = "playing"
        self.b.play = fake_play
        self.c = TestClient(TestServer(self.b.app())); await self.c.start_server()
        self.h = {"Authorization": "Bearer secret-t"}
    async def asyncTearDown(self): await self.c.close()
    async def test_request_id_is_playback_id(self):
        h = {**self.h, "X-Request-ID": "greet-1", "Content-Type": "audio/wav"}
        r = await self.c.post("/audio", data=wav(0.5), headers=h); self.assertEqual(r.status, 202)
        j = await r.json(); self.assertEqual((j["id"], j["request_id"]), ("greet-1", "greet-1"))
        self.assertEqual((await (await self.c.get("/audio/greet-1", headers=self.h)).json())["id"], "greet-1")
        self.assertEqual((await (await self.c.get("/audio/-", headers={**self.h, "X-Request-ID": "greet-1"})).json())["id"], "greet-1")
        r = await self.c.post("/audio", data=wav(0.5), headers=h); self.assertEqual(r.status, 200)  # idempotent, no replay
        self.assertEqual(self.started, ["greet-1"])
        r = await self.c.post("/audio", data=wav(0.5), headers={**h, "X-Request-ID": "other"}); self.assertEqual(r.status, 409)
        d = await (await self.c.delete("/audio/greet-1", headers=self.h)).json(); self.assertEqual(d["state"], "cancelled")
        self.assertEqual((await self.c.get("/audio/nope", headers=self.h)).status, 404)
    async def test_snapshot_width_resize_keeps_timestamp(self):
        import io
        from PIL import Image
        o = io.BytesIO(); Image.new("RGB", (1600, 1200), (200, 90, 10)).save(o, "JPEG"); src = o.getvalue()
        self.b.cameras = {self.b.doorbell: "G4 Doorbell"}
        async def fake_fetch(cid, hq): return 200, src, 1000.0, 1000.25
        self.b.fetch_snapshot = fake_fetch
        r = await self.c.get("/snapshot?width=640", headers=self.h); body = await r.read()
        self.assertEqual(r.status, 200)
        self.assertEqual(Image.open(io.BytesIO(body)).size, (640, 480))
        self.assertEqual(r.headers["X-Image-Size"], "640x480"); self.assertEqual(r.headers["X-Source-Size"], "1600x1200")
        self.assertEqual(r.headers["X-Fetch-Ms"], "250")
        self.assertTrue(r.headers["X-Captured-At"].startswith("1970-01-01T00:16:40.25"), r.headers["X-Captured-At"])
        r = await self.c.get("/snapshot", headers=self.h); self.assertEqual(await r.read(), src)
        r = await self.c.get("/snapshot?width=abc", headers=self.h); self.assertEqual(r.status, 400)
    async def test_target_and_size(self):
        h = {**self.h, "X-Request-ID": "c1", "Content-Type": "audio/wav"}
        self.assertEqual((await self.c.post("/audio", data=wav(0.5), headers={**h, "X-Target": "chime"})).status, 501)
        self.assertEqual((await self.c.post("/audio", data=wav(0.5), headers={**h, "X-Target": "toaster"})).status, 400)
        self.assertEqual((await self.c.post("/audio", data=b"\0" * 1_200_000, headers=h)).status, 413)
    async def test_cancel_race_never_starts(self):
        from protect_bridge import bridge as B
        b = self.b; j = {"id": "x", "state": "queued", "camera_id": B.DOORBELL, "timings": {}, "t0": time.time()}
        class P:
            returncode = None; killed = False
            def kill(s): s.killed = True; s.returncode = -9
            async def wait(s): return s.returncode
            async def communicate(s, d): raise AssertionError("must not stream")
        proc = P()
        async def spawn(*a, **k):
            j["state"] = "cancelled"; return proc  # DELETE lands while ffmpeg spawns
        import unittest.mock as um
        class Resp:
            status = 200
            async def json(s): return {"url": "rtp://127.0.0.1:1", "samplingRate": 24000}
            async def __aenter__(s): return s
            async def __aexit__(s, *a): pass
        class Sess:
            def post(s, *a, **k): return Resp()
            async def __aenter__(s): return s
            async def __aexit__(s, *a): pass
        with um.patch.object(B.aiohttp, "ClientSession", lambda: Sess()), um.patch.object(B.asyncio, "create_subprocess_exec", spawn):
            await B.Bridge.play(b, j, wav(0.2))
        self.assertTrue(proc.killed); self.assertEqual(j["state"], "cancelled")

class SessionGap(unittest.IsolatedAsyncioTestCase):
    """HAL 2026-10-24: >=1 s between talkback sessions, real-time pacing (no burst), explicit PT 97."""
    def setUp(self):
        import argparse
        from protect_bridge import bridge as B
        self.B = B
        d = tempfile.mkdtemp()
        for f in ("k", "t"): open(os.path.join(d, f), "w").write("secret-" + f)
        a = argparse.Namespace(protect_host="127.0.0.1", api_key_file=f"{d}/k", token_file=f"{d}/t", state_file=f"{d}/s.json",
                               stale_after=30.0, ring_burst=15.0, doorbell_id=B.DOORBELL)
        self.b = B.Bridge(a); self.posts = []; self.spawns = []
        test = self
        class Resp:
            status = 200
            async def json(s): return {"url": "rtp://127.0.0.1:7004", "codec": "opus", "samplingRate": 24000, "bitsPerSample": 16}
            async def __aenter__(s): return s
            async def __aexit__(s, *a): pass
        class Sess:
            def post(s, *a, **k): test.posts.append(time.monotonic()); return Resp()
            async def __aenter__(s): return s
            async def __aexit__(s, *a): pass
        class P:
            returncode = None
            def kill(s): s.returncode = -9
            async def wait(s): return s.returncode
            async def communicate(s, d): s.returncode = 0; return b"", b""
        async def spawn(*a, **k): test.spawns.append(a); return P()
        import unittest.mock as um
        self.patches = [um.patch.object(B.aiohttp, "ClientSession", lambda: Sess()), um.patch.object(B.asyncio, "create_subprocess_exec", spawn)]
        for x in self.patches: x.start()
    def tearDown(self):
        for x in self.patches: x.stop()
    def job(self, i): return {"id": i, "state": "queued", "camera_id": self.B.DOORBELL, "timings": {}, "t0": time.time(), "raw": True}

    async def test_cancel_during_gap_never_starts(self):
        self.b._mark_session_end()                      # a session just ended
        j = self.job("g"); t = asyncio.create_task(self.b.play(j, wav(0.2)))
        await asyncio.sleep(0.3); self.assertEqual(j["state"], "queued")
        j["state"] = "cancelled"                        # DELETE lands while waiting for the gap
        await asyncio.wait_for(t, 2)
        self.assertEqual((self.posts, self.spawns), ([], [])); self.assertEqual(j["state"], "cancelled")

    async def test_gap_enforced_and_encoder_args(self):
        j1 = self.job("a"); await self.b.play(j1, wav(0.2)); self.assertEqual(j1["state"], "finished")
        end1 = self.b.session_end
        j2 = self.job("b"); await self.b.play(j2, wav(0.2)); self.assertEqual(j2["state"], "finished")
        self.assertEqual(len(self.posts), 2); self.assertGreaterEqual(self.posts[1] - end1, self.B.SESSION_GAP_S - 0.01)
        a = list(self.spawns[0]); i = a.index("pipe:0")
        self.assertNotIn("-readrate", a)  # Clips are encoded into a local socket and paced by _send_paced.
        self.assertTrue(a[-1].startswith("rtp://127.0.0.1:"))
        self.assertEqual(a[a.index("-payload_type") + 1], "97")
        for k, v in (("-ar", "48000"), ("-b:a", "96k"), ("-application", "audio"), ("-frame_duration", "20"), ("-c:a", "libopus")):
            self.assertEqual(a[a.index(k, i) + 1], v)
        self.assertNotIn("-af", a)                      # X-Loudness: raw
        self.assertFalse(any("apad" in str(x) for x in a))

    async def test_default_loudness_kept(self):
        j = self.job("c"); j["raw"] = False; await self.b.play(j, wav(0.2))
        a = list(self.spawns[0]); self.assertEqual(a[a.index("-af") + 1], self.B.LOUD)
        self.assertFalse(any("apad" in str(x) for x in a))

    async def test_limiter_corrected_and_raw_unchanged(self):
        # option C: limiter 0.62 in both default chains (decoded Opus <= -1 dBTP); raw path still gets no -af at all
        for chain in (self.B.LOUD, self.B.LIVE_AF):
            self.assertIn("alimiter=limit=0.62:level=false", chain); self.assertNotIn("0.89", chain)
            self.assertTrue(chain.startswith("highpass=f=180,acompressor=threshold=-24dB:ratio=8:attack=5:release=80:makeup=14,"))
        j = self.job("r"); await self.b.play(j, wav(0.2))   # job() default is raw
        a = list(self.spawns[0]); self.assertNotIn("-af", a); self.assertFalse(any("alimiter" in str(x) for x in a))
        await self.b._live_open(24000)
        a = list(self.spawns[1]); self.assertEqual(a[a.index("-af") + 1], self.B.LIVE_AF)

    async def test_live_open_waits_gap_and_pt97(self):
        self.b._mark_session_end(); t0 = time.monotonic()
        await self.b._live_open(24000)
        self.assertGreaterEqual(self.posts[0] - t0, self.B.SESSION_GAP_S - 0.05)
        a = list(self.spawns[0]); self.assertEqual(a[a.index("-payload_type") + 1], "97")
if __name__ == "__main__": unittest.main()


class PacedSend(unittest.IsolatedAsyncioTestCase):
    """Clip RTP leaves on the media clock, a fixed head start ahead, with no bursts or gaps."""
    async def test_even_spacing_and_head_start(self):
        import socket
        from protect_bridge import bridge as B
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); rx.bind(("127.0.0.1", 0)); rx.setblocking(False)
        q = asyncio.Queue()
        for i in range(30):  # 30 x 20 ms Opus frames, all available at once (as after a fast encode)
            q.put_nowait(bytes([0x80, 97]) + i.to_bytes(2, "big") + (i * 960).to_bytes(4, "big") + bytes(4) + b"x" * 40)
        q.put_nowait(None)
        j = {"state": "playing", "timings": {}}
        t0 = time.monotonic()
        await B.Bridge._send_paced(object(), j, q, f"rtp://127.0.0.1:{rx.getsockname()[1]}")
        got = []
        while True:
            try: got.append(rx.recv(100))
            except BlockingIOError: break
        rx.close()
        self.assertEqual(len(got), 30)
        self.assertGreaterEqual(time.monotonic() - t0, 29 * 0.02 - B.PACE_LEAD_S)  # paced, not dumped
        self.assertEqual(j["timings"]["max_late_ms"] < 40, True)

    async def test_cancel_stops_sending(self):
        from protect_bridge import bridge as B
        q = asyncio.Queue(); q.put_nowait(bytes([0x80, 97]) + bytes(10) + b"x"); q.put_nowait(None)
        j = {"state": "cancelled", "timings": {}}
        await B.Bridge._send_paced(object(), j, q, "rtp://127.0.0.1:9")
        self.assertNotIn("max_late_ms", j["timings"])
