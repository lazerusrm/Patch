"""HAL 2026-10-24: optional compact Ogg Opus input on POST /audio. No playback: play() is mocked."""
import asyncio, io, os, shutil, subprocess, sys, tempfile, time, unittest, wave, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from protect_bridge import bridge as B
from protect_bridge.core import validate_wav

def wav(sec=1.0, rate=24000, ch=1, tone=True):
    import math
    b = io.BytesIO(); w = wave.open(b, "wb"); w.setnchannels(ch); w.setsampwidth(2); w.setframerate(rate)
    n = int(rate * sec); fr = bytearray()
    for i in range(n):
        v = int(8000 * math.sin(2 * math.pi * 440 * i / rate)) if tone else 0
        fr += v.to_bytes(2, "little", signed=True) * ch
    w.writeframes(bytes(fr)); w.close(); return b.getvalue()

def ffmpeg_enc(src_wav: bytes, *args) -> bytes:
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "pipe:0", *args, "-f", "ogg", "pipe:1"],
                          input=src_wav, capture_output=True, check=True).stdout

def opus(sec=1.0, rate=24000, ch=1, br="64k"):
    return ffmpeg_enc(wav(sec, rate, ch), "-c:a", "libopus", "-b:a", br)

@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
class CompactAudio(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp.test_utils import TestClient, TestServer
        d = tempfile.mkdtemp()
        for f in ("k", "t"): open(os.path.join(d, f), "w").write("secret-" + f)
        a = argparse.Namespace(protect_host="127.0.0.1", api_key_file=f"{d}/k", token_file=f"{d}/t", state_file=f"{d}/s.json",
                               stale_after=30.0, ring_burst=15.0, doorbell_id=B.DOORBELL)
        self.b = B.Bridge(a)
        async def noop(): pass
        self.b.ws_loop = noop
        self.played = []
        async def fake_play(j, data):          # NO talkback session, NO RTP: nothing reaches the doorbell
            self.played.append((j["id"], data, j.get("raw"))); j["state"] = "playing"
        self.b.play = fake_play
        self.c = TestClient(TestServer(self.b.app())); await self.c.start_server()
        self.h = {"Authorization": "Bearer secret-t"}
    async def asyncTearDown(self): await self.c.close()
    def H(self, rid, ct="audio/ogg", **kw): return {**self.h, "X-Request-ID": rid, "Content-Type": ct, **kw}

    async def test_health_flag(self):
        j = await (await self.c.get("/health", headers=self.h)).json()
        self.assertIs(j["capabilities"]["audio_compact"], True)
        self.assertIn("audio/ogg", j["audio_input"]["content_types"]); self.assertEqual(j["audio_input"]["max_bytes"], 1_000_000)

    async def test_valid_opus_decoded_24k_mono(self):
        for rid, data in (("o1", opus(1.0)), ("o2", opus(1.0, 48000, 2, "64k"))):
            r = await self.c.post("/audio", data=data, headers=self.H(rid, "audio/ogg; codecs=opus"))
            self.assertEqual(r.status, 202, await r.text()); j = await r.json()
            self.assertEqual((j["id"], j["request_id"], j["input"]), (rid, rid, "ogg_opus")); self.assertIn("decode_ms", j["timings"])
            got = self.played[-1][1]; self.assertEqual(validate_wav(got), (True, None))
            w = wave.open(io.BytesIO(got)); self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 24000))
            self.assertAlmostEqual(w.getnframes() / 24000, 1.0, delta=0.03)
            fr = w.readframes(w.getnframes())
            self.assertGreater(max(abs(int.from_bytes(fr[i:i+2], "little", signed=True)) for i in range(0, len(fr), 2)), 3000)
            self.b.audio[rid]["state"] = "finished"

    async def test_x_loudness_raw_preserved(self):
        r = await self.c.post("/audio", data=opus(0.5), headers=self.H("raw1", **{"X-Loudness": "raw"})); self.assertEqual(r.status, 202)
        self.assertTrue(self.played[-1][2])

    async def test_oversize_body_413(self):
        r = await self.c.post("/audio", data=b"OggS" + b"\0" * 1_100_000, headers=self.H("big")); self.assertEqual(r.status, 413)
        self.assertEqual(self.played, [])

    async def test_too_long_rejected(self):
        data = opus(21.0, br="16k"); self.assertLess(len(data), 1_000_000)
        r = await self.c.post("/audio", data=data, headers=self.H("long")); self.assertEqual(r.status, 413)
        self.assertIn("too long", (await r.json())["error"]); self.assertEqual(self.played, [])
        r = await self.c.post("/audio", data=opus(19.5, br="16k"), headers=self.H("ok20")); self.assertEqual(r.status, 202)

    async def test_malformed(self):
        good = opus(1.0)
        cases = {"junk": (b"definitely not audio" * 10, 415), "wavasogg": (wav(0.5), 415),
                 "vorbis": (ffmpeg_enc(wav(0.5), "-c:a", "libvorbis") if self._has("libvorbis") else b"RIFF....", 415),
                 "trunc_hdr": (good[:40], 415)}
        bad = bytearray(good); bad[200:] = os.urandom(len(bad) - 200); cases["corrupt"] = (bytes(bad), 400)
        cases["head_only"] = (good[:good.index(b"OggS", 4)], 400)   # OpusHead page only, no audio
        for rid, (data, st) in cases.items():
            r = await self.c.post("/audio", data=data, headers=self.H(rid)); self.assertEqual(r.status, st, (rid, await r.text()))
        r = await self.c.post("/audio", data=good, headers=self.H("vid", "video/ogg")); self.assertEqual(r.status, 415)
        self.assertEqual(self.played, [])
    def _has(self, enc):
        return enc in subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout

    async def test_idempotent_and_busy_and_cancel(self):
        data = opus(0.5)
        r = await self.c.post("/audio", data=data, headers=self.H("same")); self.assertEqual(r.status, 202)
        r = await self.c.post("/audio", data=data, headers=self.H("same")); self.assertEqual(r.status, 200)       # no replay
        r = await self.c.post("/audio", data=wav(0.5), headers=self.H("same", "audio/wav")); self.assertEqual(r.status, 200)
        self.assertEqual([p[0] for p in self.played], ["same"])
        r = await self.c.post("/audio", data=data, headers=self.H("other")); self.assertEqual(r.status, 409)
        d = await (await self.c.delete("/audio/same", headers=self.h)).json(); self.assertEqual(d["state"], "cancelled")
        r = await self.c.post("/audio", data=data, headers=self.H("after")); self.assertEqual(r.status, 202)

    async def test_wav_path_unchanged(self):
        w = wav(0.5); r = await self.c.post("/audio", data=w, headers=self.H("w1", "audio/wav")); self.assertEqual(r.status, 202)
        j = await r.json(); self.assertNotIn("input", j); self.assertNotIn("decode_ms", j["timings"])
        self.assertEqual(self.played[-1][1], w)   # byte-identical, no re-encode
        self.b.audio["w1"]["state"] = "finished"
        r = await self.c.post("/audio", data=wav(0.5, rate=16000), headers=self.H("w2", "audio/wav")); self.assertEqual(r.status, 400)
        r = await self.c.post("/audio", data=b"x", headers=self.H("w3", "audio/mpeg")); self.assertEqual(r.status, 415)

    async def test_decode_timeout_bounded(self):
        t = time.monotonic()
        with self.assertRaises(B.DecodeError) as cm: await B.decode_ogg_opus(opus(15.0), timeout=0.001)
        self.assertEqual(cm.exception.status, 400); self.assertLess(time.monotonic() - t, 2)

    async def test_decoder_args_pipe_only(self):
        seen = []
        real = asyncio.create_subprocess_exec
        async def spy(*a, **k): seen.append(a); return await real(*a, **k)
        import unittest.mock as um
        with um.patch.object(B.asyncio, "create_subprocess_exec", spy): await B.decode_ogg_opus(opus(0.3))
        a = list(seen[0]); i = a.index("-i")
        self.assertEqual(a[a.index("-protocol_whitelist") + 1], "pipe"); self.assertEqual(a[a.index("-f") + 1], "ogg")
        self.assertLess(a.index("-f"), i); self.assertEqual(a[i + 1], "pipe:0"); self.assertEqual(a[-1], "pipe:1")
if __name__ == "__main__": unittest.main()
