# PumpkinTalk ⇄ UniFi Protect bridge — self-serve API (v1)

Updated 2026-10-24 09:22 MT by HAL. Code: `/mnt/runner-fast/agent-builds/tmp/pumpkin-protect-20261024/worktree` (branch `feat/protect-bridge`). Mirror: `docs/BRIDGE_CAPABILITIES.md` there.

## Connect
- Base URL: `http://127.0.0.1:8768` (9950X loopback only; reach from the Pi via your SSH tunnel).
- Token **file**: `/home/admin/.config/pumpkin-protect/token` (0600, owner `admin`). Load it, never print or commit it:
  - shell: `T=$(cat /home/admin/.config/pumpkin-protect/token)`; send `-H "Authorization: Bearer $T"`
  - python: `TOK = open("/home/admin/.config/pumpkin-protect/token").read().strip()`
- Every endpoint (incl. `/health`) requires `Authorization: Bearer <token>`; otherwise 401 `{"error":"unauthorized"}`.
- Protect: UCK-G2-PLUS 192.168.0.24, Protect 7.3.70. Doorbell **G4 Doorbell** (original) `6a8e3fd302019203e40008c1`, IP 192.168.0.17. Chime **UP Chime** "Smart WiFi Chime" `6a8e3fd301e89203e40008c0`.

## GET /health
```json
{"ready": true, "instance_id": "864acfe3c232", "cursor": "864acfe3c232.0", "targets": ["doorbell"],
 "capabilities": {"events": true, "events_stream": true, "snapshot": true, "audio": true, "audio_cancel": true, "audio_live": true,
   "microphone": false, "owner_talkback_detection": false, "chime_audio": false, "chime_tones": false,
   "audio_compact": true},
 "audio_input": {"content_types": ["audio/wav", "audio/x-wav", "audio/wave", "audio/ogg", "audio/opus", "application/ogg"],
   "max_bytes": 1000000, "max_seconds": 20.0, "wav": "mono PCM16 24000 Hz", "ogg": "Ogg Opus (any rate/channels) decoded to mono PCM16 24000 Hz"},
 "chime": {"present": true, "model": ["UP Chime"], "remote_play": false, "sounds": [], "ringtone_select": true, "ringtone_upload": true},
 "cameras": {"6a8e3fd302019203e40008c1": "G4 Doorbell", "6ad603f00084c803e40484c4": "Basement - Entry", "...": "..."},
 "audio_active": null, "counts": {"ok": 2, "duplicate": 1}}
```
`ready` = Protect event websocket connected. `instance_id` changes on every bridge restart.

## Events
### Schema
| field | meaning |
|---|---|
| `id` | `<protect event id>:<type>` (stable dedupe key) |
| `type` | `doorbell.ring`, `person.detected`, `person.ended`, `motion.started`, `motion.ended` (motion never emitted on this install); extras `smart.detected` (vehicle/animal/package), `smart.line`, `smart.audio`, `protect.<type>` |
| `camera_id`, `camera_name` | source camera |
| `occurred_at` / `received_at` | UTC ISO-8601 (Protect event start / bridge receive) |
| `zone`, `smart_types` | when Protect provides them (else null) |
| `upstream_id`, `protect_type`, `seq` | raw Protect id/type; bridge sequence |

Real ring (Brad, 2026-10-24 07:48:06 MT). Raw Protect message (arrives ~2 s after press, single `add`, end pre-set +10 s):
```json
{"type":"add","item":{"id":"695c204d-54fd-4b4f-a825-f13cc1447154","modelKey":"event","type":"ring","start":1792849686504,"end":1792849696504,"device":"6a8e3fd302019203e40008c1"}}
```
Bridge event:
```json
{"id":"695c204d-54fd-4b4f-a825-f13cc1447154:doorbell.ring","upstream_id":"695c204d-54fd-4b4f-a825-f13cc1447154","type":"doorbell.ring",
 "camera_id":"6a8e3fd302019203e40008c1","camera_name":"G4 Doorbell","zone":null,"smart_types":null,"protect_type":"ring",
 "seq":2,"occurred_at":"2026-10-24T13:48:06.504Z","received_at":"2026-10-24T13:48:08.673Z"}
```
Gate rules: duplicates dropped (persisted 6 h across restarts); events >30 s old dropped (no replay after reconnect/restart); repeat rings within 15 s per camera suppressed; `person.detected` once per Protect event.

### Person events (verified 2026-10-24 09:18 MT)
This install emits for the G4 only `ring`, `smartDetectZone` (person/vehicle/animal/package), `smartAudioDetect` — **no plain motion events**, so `motion.started/ended` never fire here. Real raw person messages:
```json
{"type":"add","item":{"id":"f8bf825d-775a-4d2d-b91c-f9046426c40a","modelKey":"event","type":"smartDetectZone","start":1792855087482,"device":"6a8e3fd302019203e40008c1","smartDetectTypes":["person"]}}
{"type":"update","item":{"id":"18811cb6-bc77-4504-8b38-62112ca4cf74","type":"smartDetectZone","start":1792849871118,"end":1792849909625,"device":"6a8e3fd302019203e40008c1","smartDetectTypes":["person"],"modelKey":"event"}}
```
Bridge output: `{"id":"f8bf825d-…:person.detected","type":"person.detected","camera_id":"6a8e3fd302019203e40008c1","camera_name":"G4 Doorbell","smart_types":["person"],"protect_type":"smartDetectZone","occurred_at":"2026-10-24T15:18:07.482Z","received_at":"2026-10-24T15:18:10.074Z"}` (≈2.6 s after detection). `person.ended` is emitted when Protect closes the event (typically 25–40 s later) — it means detection stopped, **not** porch empty. `smart.audio` arrives ~16 s late; ignore for timing.

### PRIMARY: live stream `GET /events/stream` (SSE)
```
id: 864acfe3c232.2
event: doorbell.ring
data: {...event JSON...}

: keepalive            (every 15 s)
```
- Start without cursor → live tail. Reconnect with `Last-Event-ID: <last id>` (or `?after=<cursor>`) → you get everything after it.
- Cursor from a previous bridge instance, malformed, or older than the 200-event window → first message is
  `event: reset` / `data: {"reason":"bridge_restarted|cursor_expired|bad_cursor"}` with a fresh `id:`; then live only. History is never replayed.

### Fallback: polling (contract v1), same cursors
- `GET /events?after=latest` → `{"cursor":"864acfe3c232.2","events":[]}`
- `GET /events?after=864acfe3c232.2` → `{"cursor":"864acfe3c232.3","events":[{...}]}` (max 50 per call)
- dead cursor → `{"cursor":"<tail>","events":[],"reset":true,"reason":"bridge_restarted"}`

## GET /snapshot?camera_id=<id>[&width=640][&hq=1]
Default camera = doorbell. Returns `image/jpeg` (1600×1200 on G4) with headers `X-Camera-Id`, `X-Camera-Name`, `X-Captured-At`, `X-Fetch-Started-At`, `X-Fetch-Ms`, `Cache-Control: no-store`. 404 unknown camera (body lists cameras); 400 bad width; 503 `{"error":"unavailable (...)"}`. Nothing is stored.
- `width=<64..1920>` (added 2026-10-24 11:0x MT): bridge downsizes in memory (aspect kept, never upscales; JPEG q80). `width=640` → 640×480, ~39 KB instead of ~185 KB; resize ~10 ms. Extra headers `X-Source-Size: 1600x1200`, `X-Image-Size: 640x480`, `X-Resize-Ms`. `X-Captured-At` is the same as for the full image (time of the Protect read, not of the resize).
- Timestamp meaning: `X-Captured-At` = when the bridge finished reading the JPEG from Protect (`X-Fetch-Started-At` = request start). Protect does not report sensor time. Measured: Protect refreshes its snapshot ~2–3×/s (identical bytes for ~0.3–0.5 s), so true frame age at `X-Captured-At` is roughly 0.1–0.6 s.
- Measured 2026-10-24 ~11:00 MT on the 9950X (localhost): bridge→client 115–350 ms (median ~140 ms), age-at-client ≤1 ms after response. `hq=1` returns the same 1600×1200 image on this G4. Protect has no size parameter (`width`/`w` → 400), so resizing is bridge-side. Rate limit 10 req/s per key; keep ≤1–2/s.

## Doorbell audio (talkback) — plays ONLY when you POST it
### POST /audio
- Body: `audio/wav` (RIFF PCM16, **mono, 24000 Hz**), ≤ 20 s, ≤ 1 MB (413 if larger; 400 wrong format; 415 wrong content-type).
- **OR (optional, compact, added 2026-10-24) `Content-Type: audio/ogg`** (also `audio/opus`, `application/ogg`; params like `; codecs=opus` OK): Ogg-encapsulated **Opus**, ≤ 1 MB body, ≤ 20 s decoded. See "Compact Opus input" below. Only use it when `/health` → `capabilities.audio_compact == true`.
- Headers: `X-Request-ID` (required, ≤100 chars; idempotent — repeating returns the existing job, never replays), `X-Target: doorbell` (default; `chime` → 501), `X-Camera-ID` (doorbell only, 403 otherwise), optional `X-Loudness: raw` to skip the loudness chain.
- 202 `{"id":"greet-123","request_id":"greet-123","state":"queued","target":"doorbell","camera_id":"6a8e...08c1","timings":{}}`
- 409 `{"error":"busy","active":"<id>"}` if another clip is queued/playing (no queue — retry after finished).
### Compact Opus input (`capabilities.audio_compact`, deployed 2026-10-24)
Why: a 12 s raw 24 kHz WAV is ~576 KB; the same clip as 64 kb/s Ogg Opus is ~122 KB (≈4.7× less over the Pi's weak Wi-Fi/tunnel).
- Request: identical to the WAV path — same headers (`X-Request-ID`, `X-Target`, `X-Camera-ID`, `X-Loudness: raw`), same 202/200/409 responses, same GET/DELETE/cancel, same session gap and pacing. Only `Content-Type` and body differ.
- The bridge decodes in memory (pipes only, nothing written to disk) to **mono PCM16 24000 Hz** (any input rate/channel count is downmixed/resampled), wraps it as WAV and hands it to the unchanged playback path. Any padding/silence you encoded is preserved (Opus pre-skip/end-trim honored, ±a few ms); the bridge adds no padding. Default loudness chain still applies unless `X-Loudness: raw`.
- Decoder hardening: `ffmpeg -nostdin -xerror -protocol_whitelist pipe -f ogg -c:a libopus -i pipe:0 … -f s16le pipe:1` (forced Ogg demuxer + Opus decoder, pipe-only protocols), first page must be an Ogg BOS page carrying `OpusHead`, decoded output capped at 20 s (decoder killed as soon as it exceeds), wall-time cap 5 s, max 2 decodes at once. Measured decode: ~85 ms for a 12 s 64 kb/s clip (≈122 KB vs 576 KB WAV) on the 9950X.
- Idempotency: the `X-Request-ID` check happens before the body is read/decoded (a repeat never re-decodes or replays) and again just before the job is created (concurrent duplicates collapse to one job).
- Job view gains `"input":"ogg_opus"` and `timings.decode_ms` (WAV jobs unchanged — no new fields).
- Errors (JSON `{"error": "..."}`; nothing is played):

| Status | When |
|---|---|
| 413 | body > 1 MB (`too large (max 1MB)`), or decoded audio > 20 s (`too long (max 20s decoded)`) |
| 415 | Content-Type not WAV/Ogg, or body not an Ogg Opus stream (no `OggS` BOS page with `OpusHead`, e.g. Vorbis, WAV sent as ogg, junk) |
| 400 | malformed/corrupt Opus data, header-only stream (no audio), or decode exceeded 5 s |
| 409 / 501 / 403 | unchanged (busy / `X-Target: chime` / wrong camera) |

Make a 64 kb/s Ogg Opus from your already-padded 24 kHz mono PCM/WAV:
```bash
ffmpeg -hide_banner -loglevel error -i clip24k.wav -c:a libopus -b:a 64k -application audio -f ogg clip.opus
# or: opusenc --bitrate 64 --music clip24k.wav clip.opus      (raw PCM: opusenc --raw --raw-rate 24000 --raw-chan 1 --bitrate 64 - clip.opus)
T=$(cat /home/admin/.config/pumpkin-protect/token)
curl -s -X POST -H "Authorization: Bearer $T" -H "X-Request-ID: greet-$(date +%s)" \
     -H "Content-Type: audio/ogg" --data-binary @clip.opus http://127.0.0.1:8768/audio
```
```python
import json, subprocess, urllib.request
TOK = open("/home/admin/.config/pumpkin-protect/token").read().strip()
def post_opus(pcm24k_mono: bytes, rid: str, raw_loudness=False):
    ogg = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", "pipe:0",
                          "-c:a", "libopus", "-b:a", "64k", "-application", "audio", "-f", "ogg", "pipe:1"],
                         input=pcm24k_mono, capture_output=True, check=True).stdout
    h = {"Authorization": f"Bearer {TOK}", "X-Request-ID": rid, "Content-Type": "audio/ogg"}
    if raw_loudness: h["X-Loudness"] = "raw"
    with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8768/audio", data=ogg, headers=h, method="POST"), timeout=15) as r:
        return r.status, json.loads(r.read())   # 202 new job, 200 existing job (idempotent); HTTPError for 4xx
```
Rollback: `git revert <commit>` in the bridge worktree + `systemctl --user restart pumpkin-protect-bridge` (flag disappears; WAV unaffected).

### GET /audio/<id>   (or `/audio/-` with `X-Request-ID` header)
`{"id":"greet-123","request_id":"greet-123","state":"finished","timings":{"session_ms":242,"stream_start_ms":243,"finished_ms":5300}}`
States: `queued → playing → finished | cancelled | failed` (`error` = short non-secret reason). `finished` = our RTP stream finished sending; the doorbell sends no ack (~<0.3 s device buffer). Last 50 jobs kept.
### DELETE /audio/<id>
Kills only the bridge's own ffmpeg/RTP stream (also before it starts — never begins). Returns the job (`cancelled`). Cannot stop someone talking from the Protect app.
### Transport / level facts (verified)
- Protect `POST .../cameras/{id}/talkback-session` → `{"url":"rtp://192.168.0.17:7004","codec":"opus","samplingRate":24000,"bitsPerSample":16}`. Bridge sends Opus mono **48 kHz, 96 kb/s, music mode**, 20 ms frames, RTP PT 97 (48 kHz clock), paced real-time (see Encoding change).
- **Pacing/gap (2026-10-24 09:46 MT):** clips are sent at real-time pacing from the first packet (no initial burst; last packet leaves ~0.04 s ahead of playout instead of ~0.24 s). The bridge enforces **≥1.0 s** between the end of one talkback session and the start of the next (clips and live); a request waiting for the gap stays `queued` (`timings.gap_wait_ms`) and a DELETE during the wait never opens a session. RTP PT 97 is now explicit; each session logs non-secret codec/samplingRate/port. No padding added by the bridge.
- G4 speaker is **very quiet** and its volume is NOT settable via Integration API (no speaker field; UI/legacy only). Bridge therefore applies `highpass 180 Hz → compressor (‑24 dB, 8:1, +14 dB) → limiter 0.62` by default (applies to `/audio` default and `/audio/live`; `X-Loudness: raw` skips it). Limiter lowered 0.89→0.62 on 2026-10-24 (option C): after Opus 48k/96k encode and 24 kHz decode, 0.89 reached 0 dBFS / up to +1.7 dBTP; 0.62 measured ≤ ‑1.6 dBTP on loud speech/music/synthetic material (~2.5 dB quieter integrated). Supply clips already loud (loudnorm I≈‑12…‑14 LUFS, TP ‑1); speech carries better than low bass (fart energy is mostly lost).
- Latency: POST→sound ≈ 0.2–0.55 s (session) + device buffer. Ring→bridge event ≈ 2.2 s.
- Bug fixed 08:1x MT: earlier bodies >~64 KB were truncated (partial read) — clips before then were cut short.
- No owner-talkback detection: keep clips short; owner leaves ≥0.6 s guard after `finished`.

## Live talk — WebSocket `GET /audio/live` (added 2026-10-24 08:23 MT)
Stream TTS as it is generated instead of uploading whole clips.
- Connect: `ws://127.0.0.1:8768/audio/live?rate=24000&idle=4` with `Authorization: Bearer <token>`. `rate` = 24000 or 48000; `idle` = seconds to keep the talkback session warm after the last frame (default 4, max 15).
- Send **binary** messages of raw PCM16 little-endian mono at `rate` (20 ms = 960 bytes @24k / 1920 @48k recommended), paced in real time.
- Text `flush` = end of utterance (session stays warm `idle` s; reply `{"event":"flushed","warm_s":4}`); text `close` = stop now.
- Server events (JSON text): `{"event":"session_open","open_ms":266[,"cancelled_clip":"<id>"]}`, `{"event":"session_closed","reason":"idle"}`, `{"event":"error","error":"..."}`.
- One live stream at a time (second connect → 409). While live is open, `POST /audio` → 409. **Barge-in:** the first frame of a live stream kills any playing `/audio` clip (reported as `cancelled_clip`).
- During silent gaps the bridge feeds 20 ms silence so the session stays open; after `idle` s it closes the session (next frame reopens).
- Same loudness chain and encoding as clips (Opus 48 kHz, 96 kb/s, music mode, 20 ms, RTP).
- **Measured latency (live, 2026-10-24 08:22 MT):** cold start (first frame → first RTP packet on the wire) **390 ms** (talkback-session open 266 ms + encoder start). Warm (session already open) encoder adds **~80 ms** (+ device buffer). To stay under 300 ms, send one 20 ms silence frame when you start synthesizing so the session is warm when speech arrives.

```python
import asyncio, aiohttp, time
TOK = open("/home/admin/.config/pumpkin-protect/token").read().strip()
async def talk(pcm_chunks, rate=24000):          # pcm_chunks: iterable/async of PCM16 mono bytes
    async with aiohttp.ClientSession() as s, s.ws_connect(f"http://127.0.0.1:8768/audio/live?rate={rate}&idle=4",
                                                          headers={"Authorization": f"Bearer {TOK}"}) as ws:
        await ws.send_bytes(b"\0\0" * (rate // 50))   # pre-warm session (20 ms silence)
        frame = rate // 50 * 2; t = time.monotonic(); buf = b""
        for chunk in pcm_chunks:
            buf += chunk
            while len(buf) >= frame:
                await ws.send_bytes(buf[:frame]); buf = buf[frame:]
                t += 0.02; await asyncio.sleep(max(0, t - time.monotonic()))   # real-time pacing
        if buf: await ws.send_bytes(buf)
        await ws.send_str("flush")                   # keep warm for the next line, or ws.send_str("close")
```

## Encoding change (2026-10-24 08:20 MT)
Brad compared at the door (08:18:57 AAC-ADTS 22.05k UDP vs 08:19:05 Opus 48k): **Opus 48 kHz / 96 kb/s / music mode / 20 ms RTP was louder** → now the default for `/audio` and `/audio/live`. Protect's session response still says opus/24000; the device accepts 48 kHz-encoded Opus (RTP clock is 48 kHz regardless). G4 Speaker Volume confirmed 100% in UI. Even so the G4 speaker is quiet — use loud, speech-band clips.
Confirmation clip via `POST /audio`: 08:20:58.95 MT (5.04 s Halloween line, finished 5.2 s). Live-stream test: 08:22:15.2 MT (same line, 5 s).

## Chime (UP Chime)
No remote play on this install (Integration API has no chime play/test; legacy needs a UniFi OS login). The chime sounds only on a real press, with its per-doorbell `ringSettings`. `POST /chime` → 501.
- `GET /chime/state` → `{"chime":{..."ringSettings":[{"cameraId":"6a8e...08c1","volume":80,"ringtoneId":"68ee8976021dc503e40003fe","repeatTimes":1}]},"default":{"ringtoneId":"68ee8976021dc503e40003fe","volume":80,"repeatTimes":1}}`
- `GET /chime/ringtones` → `[{"id":"6acfb18102a89803e4000411","name":"Default","size":209972,"supported_by":["chime","speaker"],"default":true}, {"id":"e4fce2b0-cfb3-11b1-3817-f4e2c6d9ea27.mp3","name":"fart_ding",...}, ...]`
- `POST /chime/ringtones?name=<a-z0-9_->` body `audio/mpeg` MP3 ≤1 MB → Protect auto-creates `<uuid>.mp3` (chime/speaker) + `<uuid>.ogg` (doorbell). No API delete (Protect UI). Tested OK with 0.9 s/11.8 KB and 2.33 s MP3s; upper limits unknown — keep ≤ ~5 s.
- `POST /chime/select` JSON `{"ringtone_id":"<chime-capable id>","volume":80,"repeat_times":1}` (volume 0–100, repeat 1–5; id must be chime-capable or the default) → returns updated chime.
- `POST /chime/restore` → back to default (68ee8976021dc503e40003fe, vol 80, repeat 1).
- Uploaded so far: `d4b906a0-cfb2-11b1-3817-b9358a2c345f` (fart_short) and `e4fce2b0-cfb3-11b1-3817-f4e2c6d9ea27` (fart_ding).
- G4 native button sound: not selectable via Integration API (UI/legacy only).

## Signal semantics
- `doorbell.ring`: definite visitor at the door. One reaction at next pause.
- `person.detected`: approach cue only. verified live (~2.6 s latency); `person.ended` = detection stopped only.
- `motion.ended` / end of person ≠ porch empty. Departure/stay/direction must come from the porch webcam. No direction unless Protect line-crossing zones exist (`smart.line`). "Basement - Entry" is not a porch view.

## Examples
curl:
```bash
T=$(cat /home/admin/.config/pumpkin-protect/token); U=http://127.0.0.1:8768
curl -s -H "Authorization: Bearer $T" $U/health
curl -N -H "Authorization: Bearer $T" $U/events/stream
curl -s -H "Authorization: Bearer $T" "$U/events?after=latest"
curl -s -H "Authorization: Bearer $T" -o snap.jpg -D - "$U/snapshot?camera_id=6a8e3fd302019203e40008c1"
ffmpeg -i line.wav -af loudnorm=I=-13:TP=-1 -ar 24000 -ac 1 -c:a pcm_s16le clip.wav
curl -s -X POST -H "Authorization: Bearer $T" -H "X-Request-ID: greet-$(date +%s)" -H "Content-Type: audio/wav" --data-binary @clip.wav $U/audio
curl -s -H "Authorization: Bearer $T" $U/audio/greet-123 ; curl -s -X DELETE -H "Authorization: Bearer $T" $U/audio/greet-123
curl -s -X POST -H "Authorization: Bearer $T" -H "Content-Type: audio/mpeg" --data-binary @tone.mp3 "$U/chime/ringtones?name=spooky"
curl -s -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d '{"ringtone_id":"<id>.mp3","volume":80,"repeat_times":1}' $U/chime/select
curl -s -X POST -H "Authorization: Bearer $T" $U/chime/restore
```
Python (stdlib):
```python
import json, time, urllib.request
U = "http://127.0.0.1:8768"; TOK = open("/home/admin/.config/pumpkin-protect/token").read().strip()
H = {"Authorization": f"Bearer {TOK}"}
def req(path, data=None, headers={}, method=None):
    r = urllib.request.Request(U + path, data=data, headers={**H, **headers}, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp: return json.loads(resp.read() or b"null")

def stream(on_event, last=None):
    """Live SSE consumer; reconnects and resumes with Last-Event-ID."""
    while True:
        try:
            r = urllib.request.Request(U + "/events/stream", headers={**H, **({"Last-Event-ID": last} if last else {})})
            with urllib.request.urlopen(r, timeout=60) as s:
                ev = {}
                for raw in s:
                    line = raw.decode().rstrip("\n")
                    if line.startswith("id: "): ev["id"] = line[4:]
                    elif line.startswith("event: "): ev["event"] = line[7:]
                    elif line.startswith("data: "): ev["data"] = json.loads(line[6:])
                    elif line == "" and "data" in ev:
                        last = ev.get("id", last)
                        if ev.get("event") != "reset": on_event(ev["data"])
                        ev = {}
        except Exception: time.sleep(2)

def play(wav_path, rid):
    j = req("/audio", open(wav_path, "rb").read(), {"X-Request-ID": rid, "Content-Type": "audio/wav"})
    while j["state"] in ("queued", "playing"): time.sleep(0.2); j = req(f"/audio/{rid}")
    return j            # then wait >=0.6 s before listening

def cancel(rid): return req(f"/audio/{rid}", method="DELETE")
def upload_and_select(mp3, name):
    req(f"/chime/ringtones?name={name}", open(mp3, "rb").read(), {"Content-Type": "audio/mpeg"})
    tid = next(t["id"] for t in req("/chime/ringtones") if t["name"] == name and "chime" in t["supported_by"])
    return req("/chime/select", json.dumps({"ringtone_id": tid, "volume": 80, "repeat_times": 1}).encode(), {"Content-Type": "application/json"})
def restore(): return req("/chime/restore", b"", method="POST")
```
(urllib raises HTTPError on 4xx/5xx; read `e.code` / `e.read()` for 409 busy etc.)

## Limits
- Protect Integration API rate limit: 10 req/s per key (429 beyond) — bridge calls are few; don't hammer /snapshot (≤1/s).
- Audio: one clip at a time (409), WAV mono PCM16 24 kHz, ≤20 s, ≤1 MB. Chime upload MP3 ≤1 MB.
- Event buffer 200, poll batch 50, stale cutoff 30 s, ring burst 15 s.

## Service
```bash
systemctl --user status pumpkin-protect-bridge
systemctl --user restart pumpkin-protect-bridge        # new instance_id → clients get reset
journalctl --user -u pumpkin-protect-bridge -f          # no secrets logged
```
Unit `~/.config/systemd/user/pumpkin-protect-bridge.service` (from worktree `deploy/`), linger on. Secrets/state in `~/.config/pumpkin-protect/` (api_key, token, state.json; never in git).
Rollback: `systemctl --user disable --now pumpkin-protect-bridge && rm ~/.config/systemd/user/pumpkin-protect-bridge.service && systemctl --user daemon-reload`; chime back to default with `POST /chime/restore` (or Protect UI); delete uploaded ringtones in Protect UI.

## Protect-side change log
| when (MT) | change | rollback |
|---|---|---|
| 07:57 | uploaded fart_short (d4b906a0…) | Protect UI delete |
| ~08:05 | owner agent uploaded fart_ding (e4fce2b0…) and set chime → fart_ding | — |
| ~08:05 | HAL `POST /chime/restore` (per Brad "chime default") → chime back to 68ee8976…, vol 80, repeat 1 (current) | `POST /chime/select {"ringtone_id":"e4fce2b0-cfb3-11b1-3817-f4e2c6d9ea27.mp3"}` |
No recording, detection, notification, webhook or doorbell-speaker settings changed.


## REQ-3 chime change + rollback record (2026-10-24 MT)
Previous UP Chime `6a8e3fd301e89203e40008c0` `ringSettings`, captured live via GET /proxy/protect/integration/v1/chimes/{id} at ~08:04 MT BEFORE the change:
```json
[{"cameraId": "6a8e3fd302019203e40008c1", "volume": 80, "ringtoneId": "68ee8976021dc503e40003fe", "repeatTimes": 1}]
```
New ringtone: `fart_ding` (assets/protect_sfx/fart_ding.mp3, 2.33 s, made by tools/make_comic_chime.py from CC0 make_sfx.py output). Protect upload ids: `e4fce2b0-cfb3-11b1-3817-f4e2c6d9ea27.mp3` (chime/speaker) and `.ogg` (doorbell).
Rollback: `PATCH /proxy/protect/integration/v1/chimes/6a8e3fd301e89203e40008c0` with body `{"ringSettings": <previous JSON above>}` (header X-API-KEY from the bridge api_key file), then GET to confirm; or Protect UI > UP Chime > G4 Doorbell ringtone. Uploaded ringtone files have no API delete (remove in Protect UI if desired).

G4 native button sound (read-only finding): the Integration API camera object for the original G4 Doorbell has no ringtone/speaker/ring-sound field (fields: mic, osd, led, lcdMessage, micVolume, hdr, videoMode, smartDetect, featureFlags hasSpeaker:true), and the public camera PATCH does not accept one. Protect auto-creates a doorbell-side `.ogg` (supportedBy doorbell) per upload, so the product has a doorbell ringtone concept, but selecting it is UI/private-API only (UniFi OS login). Not changed.
