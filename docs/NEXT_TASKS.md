# Next tasks — talking latency (owner request 2026-10-24 ~20:40 MT)

Read `docs/HANDOFF.md` top section first (live state, deploy and rollback).
Worktree: `/mnt/runner-fast/agent-builds/tmp/pumpkin-encounters-20261024/worktree`, branch
`feat/visitor-ceremonies`. Pi install helper pattern: stage file in
`/home/pi/pumpkintalk/.porch-refresh-stage/`, hash-check against
`.porch-refresh-backup-20261024/manifest.json` `installed`, replace, update manifest, restart
`pumpkin` only when status.json shows nobody on the porch. Render new fixed lines with
`set -a; . ./pumpkin.env; set +a; python3 warm_porch.py [characters...]` in the Pi live dir.
Host backend: `systemctl --user restart pumpkin-backend` (runs backend.py from this worktree;
restarting it interrupts Pi renders that go through it).

Measured baseline (Pi logs 2026-10-24, generated-reply turns): ASR median 0.54 s (p90 2.1),
reply LLM median 2.9 s (p90 6.9), TTS render+download median 5.4 s (p90 7.4), bus 0.4 s.
Cached lines start in ~0.4 s. `REPLY_TIMEOUT_SECONDS` (7) falls back to a cached joke.

Owner approved all four, in this order:
1. Instant cached reaction while the reply is generated (porch_bits REACTIONS, played on the
   bus in a thread before the reply turn; never for quick replies/commands).
2. More quick replies (cached answers for common visitor phrases, no LLM/TTS) and plain
   "tell me a joke"/"story" intents without the wake word.
3. One round trip: backend /turn with `speak` renders the first sentence on the host and returns
   compact audio with the text; Pi plays it immediately, renders the rest in parallel.
4. Local LLM on the RTX 5090 for replies (check what is installed: ollama / vLLM / llama.cpp;
   GPU has ~16 GB used by the voice server). Keep the hosted model as fallback.

Status of each is recorded below by the session that works on it.

## Status
- 2026-10-24 ~21:00 MT (Claude Code):
  1. DONE, live. `porch_bits.REACTIONS` (3 per character, cached), `Pumpkin.start_reaction` plays one
     on the bus in a thread while the generated reply is fetched; never for quick replies/commands.
     Disable with `REACTIONS_ENABLED=0`. Not yet heard by the owner.
  2. DONE, live. `porch_bits.MORE_REPLIES` (favorite candy, are you real, you're funny, compliments,
     are you scary, what's up) matched on short utterances; plain "tell me a joke", "tell me a story",
     "do a routine" intents without the wake word (games.intent). All lines pre-rendered.
  3. DONE (single-shot, not sentence-streamed), live. Pi sends `speak: true`; backend `/turn` renders the
     reply via `render_compact` and returns `voice` (base64 Ogg Opus) + `voice_model`; Pi
     `Speech.render(..., prefetched=...)`. Host test: Dobby reply text+voice in 7.1 s end to end on host.
     Fallback to the separate /tts request if inline voice is missing. Next improvement: split the
     reply at the first sentence, render/return sentence 1 first (needs streaming response or two calls).
     Measure on the Pi: grep "Backend turn: phase=reply" and compare with the baseline above.
  4. NOT STARTED. Nothing local is installed (no ollama/vLLM/llama.cpp; no instruct model in
     HF caches; /mnt/runner-fast has ~280 GB free; GPU has ~16 GB free beside the voice server).
     Plan: small instruct model (e.g. a 3-8B Qwen/Llama class model, 4-bit or bf16 within ~10 GB)
     served on loopback by a new user service; backend `respond()` tries it first with a ~2 s budget
     and the same prompt (core.CHARACTERS personality + pumpkin_instructions.txt), falling back to
     the current hosted model. Evaluate joke quality against the hosted model with the owner before
     making it the default: the owner's main complaint is unfunny LLM-sounding lines.

Other owner feedback addressed tonight: Voldemort doorbell bit timing (doorbell clips now launch
`DOORBELL_LEAD_SECONDS`=1.2 s before the preceding line ends, `Pumpkin.perform_scene`).
Known voice-server limitation: Breeze (patch/boo/nibbles) returns 503 on very short inputs such as
"Every time."; keep authored lines to roughly three words or more.
- 2026-10-24 ~21:30 MT (Claude Code, follow-up session). All live; evidence `evidence/latency-20261024.md`.
  - LLM: Codex `service_tier=fast` (`PUMPKIN_SERVICE_TIER`, default fast). Backend drop-in
    `~/.config/systemd/user/pumpkin-backend.service.d/40-fast-replies.conf` sets Sol low (overrides the
    30-visitor-pipeline Luna/none). Hedge: if Sol has not answered in `PUMPKIN_HEDGE_SECONDS` (3.5) the
    backend also starts `PUMPKIN_HEDGE_MODEL` (gpt-6-luna, effort none) and keeps the first good reply;
    a failed primary hedges immediately. AGY and Cursor `agent` were benchmarked and are slower.
  3. Sentence streaming DONE: Pi sends `split: true`; backend `split_lead` returns `voice_text` + `rest`
     only when the opening is >= 40% of the rest's words (so the rest renders while it plays), renders the
     rest in the background, and the Pi's `/tts` for the rest collects it (`PENDING`). Old Pis unaffected.
  - Loudness matching moved to the host (`render_compact`, `X-Loudness: matched`); Pi only decodes.
  - Reactions rewritten as funny in-character stalls; ~50% add a trapped-Voldemort heckle on the inside
    speaker (`porch_bits.HECKLES`, `HECKLE_CHANCE`). Reactions play only when already cached, so they never
    take the single-lock voice server from the real reply. All pre-rendered by warm_porch.py.
  4. Local LLM: NOT pursued. Hosted fast tier is ~3 s and the owner's main complaint is humor; a small local
     model would likely be less funny. Remaining latency is mostly TTS (Breeze RTF ~0.4, Qwen 1.7B slower);
     next lever is streaming Breeze chunks (`FastBreezeStreamingRuntime.iter_audio_chunks`) to the bus.
  Not yet heard by the owner: new reactions/heckles, split replies, Sol-vs-Luna humor choice.
- 2026-10-24 ~21:50 MT: Trogdor mentions (owner request). `games.intent` returns `trogdor_scene` when a
  visitor says Trogdor / Burninator / Strong Bad (also "trog door") and it is not a question; questions go
  to Strong Bad's real trivia answer. `Pumpkin.trogdor_scene` rotates six new `porch_bits.TROGDOR_BITS`
  (summon, drawing_lesson, door_visit, dark_lord_vs_dragon, cardboard, frog_door: Strong Bad on the porch,
  the G4 doorbell as deadpan narrator, trapped Voldemort inside, roar/chomp effects) plus the three existing
  Trogdor routines, skips inside-speaker scenes when unavailable, and has a `TROGDOR_COOLDOWN_SECONDS` (45)
  cooldown. All lines pre-rendered; summon and frog_door verified acoustically (every line heard, C920).
  Not yet heard by the owner.
- 2026-10-24 ~22:20 MT: WiZ porch bulbs (owner request). Two ESP25_SHRGB_01 RGB bulbs, MACs
  cc40858a23ec and cc408589ff2a (were 192.168.0.11 / .96). Pi `pumpkin.env` has `WIZ_LIGHTS=<macs>`
  (backup `.porch-refresh-backup-20261024/pumpkin.env.before-wiz`); the bulbs are found by broadcast
  (`Lights.find_wiz`), so DHCP changes are fine. Local UDP 38899, unsigned setPilot works; the WiZ cloud
  export (home key) is private at `../wiz-export/export.json` and is not used. `Lights.run_wiz` mirrors the
  pumpkin's state (idle flame, speaker colour/level, Strong Bad flicker, Voldemort-inside green), fire and
  forget at <=5 Hz; restores warm white 2700 K on exit; sleep = warm white `WIZ_SLEEP_DIMMING` (30).
  Cues: doorbell lines blue, dragon effects fire, scene step kind `light` ('blackout:6', 'lightning', 'fire',
  'green', 'ghost', 'houses', '<house>'), sorting cycles house colours then locks on the house, Boo strobes.
  New bulb-only fillers `lights_out`, `seance` (`NEEDS_BULBS`). Delay knob `WIZ_DELAY_SECONDS` (0 now).
  NEXT: owner is relocating the bulbs above the pumpkin; then calibrate: flash white + speaker click while a
  camera that sees the bulbs (G4 or C920) records, measure light-vs-sound offset, set WIZ_DELAY_SECONDS.
- 2026-10-25 (Claude Code, long porch session with the owner). Live unless noted:
  - Voices: Strong Bad = Breeze, ref A (owner option one). Dobby = Breeze, user recording without the
    opening squeal, '!' softened; quality pass re-took 94/142 authored lines (pitch + ASR scored, seeds
    614/3/13/21; originals in .porch-refresh-backup-20261024/dobby-cache-before-quality); owner picks:
    "Dobby! Dobby is a free elf!" seed 21, "The doorbell is sleeping!..." seed 13. Boo 1.15x + bass cut.
    Nibbles reworked as a goblin candy critic. Voldemort/Hat untouched (approved).
  - Speech: Whisper on GPU; C920 capture gain 9 (MIC_CAPTURE_GAIN), WebRTC AEC3+NS+AGC front end
    (audio_frontend.py, reference delay .24, barge-in coded but BARGE_IN=0 until a better detector);
    short command words kept when unsure, re-transcribe when Whisper VAD drops a gated clip, hinted
    second listen for 1-2 word clips, Lumos/Nox/Trogdor spellings from real ASR (Lima, Not, Burning).
    Owner approved transcript/ASR debug logging while testing: DEBUG_TRANSCRIPTS (Pi drop-in
    95-debug-transcripts.conf) and PUMPKIN_DEBUG_ASR (backend drop-in 60-debug-asr.conf, keeps the last
    20 clips in runtime/debug-asr). Remove both drop-ins when testing ends.
  - Porch: webcam moved/tilted; WEBCAM_VISITOR_FEET .52, WEBCAM_VISITOR_SCORE .40; webcam walk-away
    departure (visitor_motion.WebcamDeparture); mapping walks in evidence/porch-mapping-20261025.md;
    visitors sent to the corner of the path for camera bits.
  - Pose: YOLOv8s-pose (Hailo-8, models/yolov8s_pose.hef, ~12 ms) replaces the detector; raised hand ->
    host calls on them and listens patiently; Hands-up poll, Pumpkin Says, Flex; hints filler.
  - WiZ porch bulbs follow the cast and the bits (WIZ_LIGHTS MACs, WIZ_DELAY_SECONDS .15).
  - Audit (log + independent review) fixes in 545d45d and 68278af. Pending owner checks: Lumos/Nox after
    the ASR fixes, pose games on the porch, doorbell used more while people are on the porch (requested).
