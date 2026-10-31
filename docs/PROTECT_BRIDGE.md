# UniFi Protect -> PumpkinTalk bridge (2026-10-24)

Worktree: /mnt/runner-fast/agent-builds/tmp/pumpkin-protect-20261024/worktree (branch feat/protect-bridge, from d7dd5a1).
New files only: protect_bridge/, tests/test_protect_bridge.py, deploy/, docs/PROTECT_BRIDGE.md, docs/protect-integration.patch.md.

## Live discovery (verified 2026-10-24)
- Console: UniFi Cloud Key Gen2 Plus (UCK-G2-PLUS, "Elk Ridge"), 192.168.0.24, same /24 as 9950X (192.168.0.73).
  Protect 7.3.70, Network 10.6.106 (from integration meta/info). UniFi OS version not exposed to API key (/api/system is unauthenticated-minimal) - check in UI.
- Doorbell: "G4 Doorbell" (type UVC G4 Doorbell, original G4, not Pro/Instant), id 6a8e3fd302019203e40008c1, CONNECTED, IP 192.168.0.17 (from talkback URL).
  Mic+speaker, LED, HDR; smart detect person/vehicle/animal/package; audio detect smoke/CO/baby-cry/speak; NO face/LPR; LCD message currently custom "No Soliciting". Firmware not exposed by Integration API.
- Chime: "Smart WiFi Chime" (UP Chime) paired to the G4, volume 80, repeat 1, ringtoneId 68ee8976021dc503e40003fe.
- Second Protect camera on site: "Basement - Entry" (G6 Pro Entry, face+LPR+package camera). Three other cameras DISCONNECTED (Amcrest, ONVIF).
- Home Assistant: not installed on 9950X (not installed for this).

## API surface on THIS install (Integration API, X-API-KEY)
| Endpoint | Result |
|---|---|
| GET /proxy/protect/integration/v1/meta/info, cameras, chimes, nvrs, liveviews, viewers, lights, sensors | 200 |
| WS  .../subscribe/events, .../subscribe/devices | 101 upgrade, streaming (devices updates observed) |
| GET .../cameras/{id}/snapshot | 200 JPEG 1600x1200 |
| POST .../cameras/{id}/talkback-session | 200 `{"url":"rtp://192.168.0.17:7004","codec":"opus","samplingRate":24000,"bitsPerSample":16}` |
| GET .../files/ringtones | 200 (only 4 built-in tones x mp3[chime,speaker]/ogg[doorbell]) |
| POST .../files/ringtones | exists (400 "Content-Type required" on empty body) - upload not attempted |
| GET .../alarm-manager/webhook | 404 (no outbound-webhook config via API) |
| Legacy /proxy/protect/api/bootstrap with API key | 500 (legacy API needs a UniFi OS user session; not used) |

Alarm Manager outbound webhooks are UI-configured only; no Protect-side changes were made. The bridge
uses the official event websocket instead (lower latency, no inbound port, no UI changes). /webhook is
available if an Alarm Manager webhook is added later (URL http://192.168.0.73:8768/webhook requires --bind 0.0.0.0
plus header `X-Pumpkin-Token` - Alarm Manager custom headers support must be confirmed in UI).

## Talkback (not exercised - no audio sent)
Session endpoint gives an RTP target: Opus, 24 kHz, 16-bit (mono). Expected pipeline:
`ffmpeg -re -i tts.wav -ac 1 -ar 24000 -c:a libopus -b:a 32k -application voip -f rtp rtp://192.168.0.17:7004`
Latency expected ~0.3-0.8 s; G4 speaker is small/quiet, half-duplex. Needs a test with Brad's OK. Keep in pumpkin controller, not bridge.

## Custom Halloween chime (read-only findings)
- Protect 7.3 has a ringtone library (files/ringtones) with an upload endpoint (POST multipart, exact field/limits unverified until a real upload).
  Built-ins come as .mp3 (supportedBy chime, speaker) and .ogg (supportedBy doorbell) - so a custom tone likely needs mp3 for the UP Chime; doorbell-local sound is ogg.
- Per-chime/per-doorbell: chime ringSettings is per (chime, camera) with ringtoneId/volume/repeatTimes -> settable per doorbell on each chime (PATCH /chimes/{id} likely; not tried).
- Note the chime's current ringtoneId is not in the files list (likely a chime-native tone id).
- Limits commonly cited by Ubiquiti (short clip, few seconds, small MB) are UNVERIFIED here; verify in UI (Protect > UP Chime > Ringtone > Upload) or by one upload with approval.

## Bridge contract v1 (DEPLOYED + VERIFIED 2026-10-24)
See the full capabilities block (copied from coordination.md) in docs/BRIDGE_CAPABILITIES.md. Unit: ~/.config/systemd/user/pumpkin-protect-bridge.service -> 127.0.0.1:8768. Secrets ~/.config/pumpkin-protect/{api_key,token} (0600). State ~/.config/pumpkin-protect/state.json.

## Signal semantics (what is trustworthy)
- doorbell_ring start: definitive press. -> one short reaction at next pause.
- person_detected start on G4: approach cue (stop idle music, prep greeting). Reasonable but not occupancy.
- motion/person end: only means detection stopped; NOT porch empty. Departure must be confirmed by webcam (C920) absence for N seconds.
- Direction (approach vs depart): not provided unless smart line-crossing zones are configured in Protect (smartDetectLine); otherwise infer from webcam. Basement - Entry is a different location - not a porch second view unless Brad confirms placement.

## Tests
`cd worktree && python3 -m unittest tests.test_protect_bridge -v` (normalize, dedupe, stale, ring burst, restart replay).
Live: `T=$(cat ~/.config/pumpkin-protect/token); curl -N -H "Authorization: Bearer $T" localhost:8768/events`

## Rollback
`systemctl --user disable --now pumpkin-protect-bridge && rm ~/.config/systemd/user/pumpkin-protect-bridge.service && systemctl --user daemon-reload`;
optionally `rm -r ~/.config/pumpkin-protect`. No Protect-side changes to revert. Worktree removal: `git worktree remove <path>` from main repo.

## LIVE VERIFICATION 2026-10-24
Real ring (Brad, 07:48:06 MT) raw Protect event (only message; arrives as `add` with `end` already set = start+10 s; no follow-up update):
```json
{"type":"add","item":{"id":"695c204d-54fd-4b4f-a825-f13cc1447154","modelKey":"event","type":"ring","start":1792849686504,"end":1792849696504,"device":"6a8e3fd302019203e40008c1"}}
```
Bridge output (emitted once, seq 2; ~2.2 s press->bridge):
```json
{"event_type":"doorbell_ring","phase":"start","protect_type":"ring","event_id":"695c204d-54fd-4b4f-a825-f13cc1447154","source_camera":{"id":"6a8e3fd302019203e40008c1","name":"G4 Doorbell"},"timestamp":1792849686.504,"start":1792849686.504,"end":1792849696.504,"detection":null,"via":"ws","seq":2}
```
No motion/person events appeared on the stream around the press (or in ~20 min of capture) — check G4 recording/smart-detect settings in UI; person cue is unverified.

Talkback test (once, approved): session request 553 ms; 2.37 s espeak clip at volume 0.7 streamed in 1.96 s, ffmpeg exit 0.
```
URL=$(curl -sk -X POST -H "X-API-KEY: $K" https://192.168.0.24/proxy/protect/integration/v1/cameras/<id>/talkback-session | jq -r .url)
ffmpeg -re -i clip.wav -af volume=0.7 -ac 1 -ar 24000 -c:a libopus -b:a 32k -application voip -f rtp "$URL"
```
ffmpeg advertises opus/48000/2 RTP (Opus RTP clock is always 48k) — accepted. No completion ack from device.
