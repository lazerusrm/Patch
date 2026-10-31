import asyncio, os, sys, tempfile, unittest, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aiohttp.test_utils import TestClient, TestServer
from protect_bridge import bridge as B

class FakeStdin:
    def __init__(s): s.buf = bytearray(); s.closed = False
    def write(s, d): s.buf += d
    async def drain(s): pass
    def close(s): s.closed = True
class FakeProc:
    def __init__(s): s.stdin = FakeStdin(); s.returncode = None
    async def wait(s): s.returncode = 0; return 0
    def kill(s): s.returncode = -9

class Live(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        d = tempfile.mkdtemp()
        for f in ("k", "t"): open(os.path.join(d, f), "w").write("secret-" + f)
        a = argparse.Namespace(protect_host="127.0.0.1", api_key_file=f"{d}/k", token_file=f"{d}/t", state_file=f"{d}/s.json",
                               stale_after=30.0, ring_burst=15.0, doorbell_id=B.DOORBELL)
        self.b = B.Bridge(a)
        async def noop(): pass
        self.b.ws_loop = noop
        self.procs = []
        async def fake_open(rate):
            p = FakeProc(); self.procs.append(p); return p
        self.b._live_open = fake_open
        self.c = TestClient(TestServer(self.b.app())); await self.c.start_server()
        self.h = {"Authorization": "Bearer secret-t"}
    async def asyncTearDown(self): await self.c.close()

    async def test_auth_and_rate(self):
        r = await self.c.get("/audio/live"); self.assertEqual(r.status, 401)
        r = await self.c.get("/audio/live?rate=8000", headers=self.h); self.assertEqual(r.status, 400)

    async def test_stream_warm_idle_and_single(self):
        ws = await self.c.ws_connect("/audio/live?rate=24000&idle=0.3", headers=self.h)
        await ws.send_bytes(b"\1\0" * 480)
        m = await ws.receive_json(); self.assertEqual(m["event"], "session_open")
        await ws.send_bytes(b"\2\0" * 480)
        r = await self.c.get("/audio/live", headers=self.h); self.assertEqual(r.status, 409)       # one at a time
        r = await self.c.post("/audio", data=b"x", headers={**self.h, "X-Request-ID": "q", "Content-Type": "audio/wav"})
        self.assertIn(r.status, (400, 409))
        m = await ws.receive_json(timeout=2); self.assertEqual(m, {"event": "session_closed", "reason": "idle"})
        self.assertTrue(self.procs[0].stdin.closed); self.assertGreaterEqual(len(self.procs[0].stdin.buf), 1920)
        await ws.send_bytes(b"\3\0" * 480)                       # new utterance reopens
        m = await ws.receive_json(); self.assertEqual(m["event"], "session_open"); self.assertEqual(len(self.procs), 2)
        await ws.send_str("close"); await ws.close()
        await asyncio.sleep(0.05); self.assertIsNone(self.b.live)

    async def test_barge_in_cancels_clip(self):
        p = FakeProc(); self.b.audio["clip"] = {"id": "clip", "state": "playing", "proc": p}; self.b.current = "clip"
        ws = await self.c.ws_connect("/audio/live", headers=self.h)
        await ws.send_bytes(b"\0\0" * 480)
        m = await ws.receive_json(); self.assertEqual(m.get("cancelled_clip"), "clip")
        self.assertEqual(self.b.audio["clip"]["state"], "cancelled"); self.assertEqual(p.returncode, -9)
        await ws.close()
if __name__ == "__main__": unittest.main()
