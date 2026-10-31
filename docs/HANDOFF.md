# PumpkinTalk handoff

## 2026-10-24 ~21:30 — latency follow-up (Claude Code; read docs/NEXT_TASKS.md Status)

Live: Sol low on Codex fast tier with Luna-none hedge after 3.5 s; first-sentence split replies;
host-side loudness; funnier reactions plus inside-speaker Voldemort heckles. Pi files installed with the
manifest pattern (unifi_client.py original added to `.porch-refresh-backup-20261024/`). Pi tests 55 OK;
host 134 (only the known missing-cv2 error; speaker-bus timing test is flaky). Doorbell first words
verified intact on the C920 (`evidence/latency-20261024.md`). Mic recordings were RAM-only and deleted.

## 2026-10-24 evening — porch refresh (Claude Code session; supersedes the state below)

Owner chose this session to take over from the parent Codex integration agent
(coordination.md 18:30 MT). Branch `feat/visitor-ceremonies` in this worktree.

Live on the Pi (installed via `runtime/deploy_porch_refresh.py`, backup and manifest in
`/home/pi/pumpkintalk/.porch-refresh-backup-20261024`; rollback:
`python3 .porch-refresh-stage/deploy_porch_refresh.py rollback`):
- `speaker_bus.py`: one always-open Bluetooth stream for speech and music. Measured with the
  C920: ~0.40 s write-to-sound, no lost onsets after 25 s of keepalive (cold aplay lost a
  0.25 s beep entirely), keepalive 180 Hz at amplitude 120 is inaudible at the mic.
  `SPEAKER_BUS=0` restores the old per-clip path. Music gain `MUSIC_GAIN` (default 1.2).
- `porch_zones.py`: G4 footpoint zones measured on real walks (path < .80 <= porch < .95 <= door),
  departures need a clear downhill path frame (y <= .76) confirmed by another path frame or 1.5 s
  absence. Replayed against the logged walks. Farewells are now enabled through it.
- Doorstep bits (4 s at the door, no ring in 20 s): fake ding-dong on the porch speaker,
  doorbell redirect. Ring bits, filler bits (up to 6 per visit, doorbell banter preferred
  while someone is on the porch), sidewalk lures (webcam, every 75 s at most).
- Voldemort trapped inside the pumpkin (USB speaker, 90% cap) as a running gag; inside speaker
  gets a 0.45 s wake tone (owner reported clipped first syllable). Bus/USB offset measured and
  corrected (INTERNAL_BUS_DELAY_SECONDS .39).
- Rewritten greetings, replies, jokes, farewells and LLM comedy direction; Nibbles is a real
  candy inspector; Trogdor routines (candy, hat, rescue) with synthesized fx in assets/effects.
- Lines already speaking finish even if a departure is detected; generated replies over 7 s
  are abandoned for a cached joke (`REPLY_TIMEOUT_SECONDS`).
- loudness.py fix: loudnorm silently under-normalized clips < 3 s (about -40 LUFS). 121 quiet
  cache files were moved to `/home/pi/pumpkintalk/cache-quiet-20261024` and re-rendered.

Voices (host primary checkout voices.json, backup `runtime/voices-backup-20261024-porch`):
Strong Bad candidate C, Dobby candidate B2 from `/home/admin/Documents/PumpkinTalk/voice-auditions`
(README there has metrics). Cache epochs bumped via core.py voice_revision.

Not yet verified by the owner: humor, synthesized Trogdor fx, sidewalk lures with a real
passer-by, farewell timing on a real departure.


Written 2026-10-24, America/Denver. This document supersedes older runtime-state
claims in the transcript. Read `docs/LEDGER.md` for detailed evidence history.

## Current verified state

- Owned checkout: `/mnt/runner-fast/agent-builds/pumpkintalk-20261023`, branch
  `feat/porch`. `/home/admin/Documents/PumpkinTalk/source` points here. Work here;
  preserve this dirty, resumable checkout and its runtime/model caches.
- Latest commit: `d6efc2a` (voice profiles, loudness, sorting ceremonies, comedy).
  Further tested/deployed changes listed below are **uncommitted**.
- Host user services `pumpkin-voices`, `pumpkin-backend`, `pumpkin-tunnel`: active.
- SSH alias `pumpkin`, Pi `/home/pi/pumpkintalk`: normal service active,
  Bluetooth reconnect timer active. Pathfinder Go connected, classic MAC
  `B1:2E:84:76:00:D9`. `F1:2E:84:76:60:D9` is its BLE companion, not audio.
- **Actual current saved controls: volume 100, sleeping false, mode normal.**
  Earlier handoffs said sleeping true; readback now differs. Do not overwrite
  this state based on old assumptions. No state changed while writing this handoff.
- Latest bounded comparison `pumpkin-latest-review` completed successfully at
  Oct 23 22:22:26 MDT; inactive now. Its log confirms Hat and Voldemort played.
  No hour-long audition remains scheduled; original 90-minute deadline expired.
- Latest recorded verification: **55 host tests and 45 Pi tests passed** in
  `evidence/verification-host.txt` and `evidence/verification-pi.txt`.
- Astra worker `/root/astra_medium__dobby_refinement` is completed. All owned
  offline conversion jobs exited; do not spawn a duplicate or restart them.

## User requirements and choices

- Digital Bluetooth output defaults to **100%**. User controls loudness on the
  physical speaker. Preserve volume commands and saved adjustments.
- User approves **Sorting Hat** and **Voldemort** voices. Keep their exact
  `voices.json` reference profiles/settings intact.
- **Strong Bad 2** was best but still insufficient likeness. **Dobby A** was
  slightly better than B but still insufficient likeness. These remain current
  provisional profiles; do not equate intelligibility/speaker scores with approval.
- User reported missing first approximately two seconds, then intermittent
  cutouts/stutters especially Dobby and Hat, plus uneven volume. These are separate
  issues. Loudness improvements do not prove wireless stutter resolved.
- User wants sharper jokes, funny character arguments, actual Hat ceremonies and
  all four mode commands. No new feedback yet on latest converted voice candidates.
- User paused, then resumed refinements and explicitly authorized audible testing.
  Do not restart an unbounded audition. Keep samples bounded and announced.

## Implemented and deployed

- Camera/Hailo person detection and VLM costume judging, character-specific cheeky
  verdicts; short fictional house ceremonies based on costume/described choices.
- Mode commands: “Hey Pumpkinhead Trogdor mode”, “… Dobby mode”, “… Sorting Hat
  mode”, plain “Voldemort mode”, and “… normal mode”. “Pumpkin head” works too.
  Hat/Dobby occasionally appear in normal rotation; Trogdor/Voldemort explicit.
- Plain “trick or treat”, “Boo!”, sleep/wake, volume, jokes/stories, “sort me/us/next”,
  “Hey Pumpkinhead do a routine” / “argue”. Four-house shuffle avoids immediate
  repeats; house is remembered within the encounter, cleared for a new encounter.
- Four authored cast routines: scare-shift moth punchline, Voldemort/Dobby welcome
  mat, dragon/googly comic exchange, Hat sorting the vacuum. Explicit special
  characters are not silently added to normal routines.
- Sharper authored jokes for all seven characters, Dobby additions, Voldemort
  jokes/stories, improved generated-comedy direction. Preserve strong early lines.
- Idle warm flame breathing below lighting cap; sleep lights off; actor-colored
  speech and Voldemort entrance flourish.
- Shared measured two-pass loudness matching in `loudness.py`, target -20 LUFS,
  -6 dB peak ceiling, gentle compression. Eight-sample spread 0.6 LU; regression
  requires less than 1 LU. Songs/operator clips matched too. Cache epoch
  `reference-v4-L20-matched` prevents old audio reuse.
- Bluetooth initial-syllable preparation: three-second quiet 180 Hz lead-in within
  the same PCM stream, LED envelope delayed accordingly, BlueALSA keepalive 60.
  Field checks restored full opening; do not claim a proven amplifier-gating cause.
- Host supports pinned Qwen 0.6B/1.7B profiles with per-character clone prompts;
  current Dobby A and Strong Bad 2 use 1.7B. Shared service memory limit 12 GiB.

## Latest uncommitted work (already deployed where applicable)

- `pumpkin.py`: each two-line routine exchange is one stream with a 180 ms reply
  gap, light cues follow actors, listening/control gaps remain between pairs.
  Pre-rendered all nine pairs successfully. Combined cache hashes actual PCM;
  temporary fallback voices remain RAM-only and clean up on cancellation.
- `tests/test_pi_runtime.py`: meaningful pair/cue/cache/fallback regression checks.
- `voice_server.py` + test: Trogdor-specific spelling “consummate Vs” becomes
  “consummate V's”. Checked old spelling produced “these”; apostrophe version
  preserved the letter name. Do not apply broad phonetic rewrites to other voices.
- Dobby v4 report/provenance/ASR/hash evidence, routine acoustic report, Strong Bad
  word checks, docs and current verification logs. Run `git status --short`.
- Pre-existing untracked `evidence/sol_high__review.txt` and
  `evidence/sol_high__controls_review.txt` were deliberately left alone. Do not
  include or delete them accidentally when committing this task's work.

## Voice candidates ready; human decision pending

Latest audible order: Dobby A, Dobby candidate one (full clean-reference tone
conversion), candidate two (gentler conversion), Strong Bad 2, three converted
Strong Bad variants, approved Hat and Voldemort. All announced and matched.

- Dobby: `runtime/dobby-refinement-v4/`, OpenVoice V2 tone conversion of Dobby A,
  `ov-original`, `ov-clean`, `ov-clean60`, each familiar and novel text. All six
  word checks pass. Astra recommends comparing `ov-clean` with A first.
  See `docs/DOBBY_REFINEMENT.md` and `evidence/dobby-refinement-v4-*`.
- Strong Bad: `runtime/strongbad-v4/`, `ov-expressive`, `ov-calm`, `ov-calm60`.
  Index **1** novel joke is word-perfect; index **0** retains the old Vs pronunciation
  error, so avoid using index 0 as a new final sample. Production spelling is fixed.
- Matched playback files: `runtime/likeness-v4-audition/`, uploaded to Pi
  `/home/pi/pumpkintalk/auditions/likeness/`.
- Bounded operator script: `runtime/play_latest_review.py`, Pi root counterpart.
  It plays authored content only; no camera/microphone recording.
- No OpenVoice conversion selected in production. Preserve A/2 until human choice.
  Strong Bad v3 nasal/gravel EQ alternatives also exist; no feedback yet.
- Worker model/code provenance pinned in v4 evidence. Conversion uses a small
  private runtime; no shared environment installs. Do not redownload completed models.

## Playback issue: open investigation and next steps

1. Get human feedback on the latest matched pass: any cutouts, which exact sample,
   and whether either converted Dobby/Strong Bad candidate sounds closer.
2. Ask/check the physical **Stereo-Link icon** on Pathfinder Go. Official ION
   documentation associates searching for another speaker with possible dropouts;
   double-press **Stereo-Link / Repeat** cancels searching. Icon off is desired for
   one speaker. This has not been physically verified. Do not confuse the BLE
   companion or Bluetooth pairing button with Stereo-Link.
   Source: https://support.ionaudio.com/en/support/solutions/articles/69000836712-ion-audio-pathfinder-go-how-do-i-link-a-second-speaker-
   Manual: https://cdn.inmusicbrands.com/ion/products/pathfinder-go/Pathfinder%20Go%20-%20User%20Guide%20-%20v1.3.pdf
3. No Bluetooth disconnect, Pi power/CPU problem, or ALSA underrun was observed
   during earlier stutter reviews. `PCM dropped: 14` is a descriptor/drop operation,
   not a Bluetooth packet-loss counter. Playback now logs ALSA diagnostics.
4. Pi Wi-Fi is 2.4 GHz with weak signal. Two bounded 5 GHz trials failed saved-network
   authentication and automatically rolled back. Original profile/IP restored;
   temporary clone deleted. **Do not repeat these attempts without new evidence.**
5. The routine microphone comparison had inadequate pickup and was inconclusive
   (`evidence/routine-acoustic-check.json`); raw RAM recordings were deleted.
   Avoid repeating low-quality recordings as proof. Distinguish source pauses,
   physical speaker behavior and radio delivery with a specific reproducible sample.
6. No further Bluetooth resets/re-pairing/restarts are justified by current evidence.
   User noticed earlier reconnects; preserve the now-working bond.
7. Once human likeness choice is available, integrate only the chosen candidate
   with meaningful checks; keep approved Hat/Voldemort untouched. If still poor,
   change reference/model approach rather than accumulating cosmetic EQ variants.
8. Finish review and commit the tested, owned uncommitted work. No push/publication
   requested. Preserve runtime caches and the resumable worktree.

## Verification and recovery

Host: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v`

Pi suite (from `/home/pi/pumpkintalk`):
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python3 -m unittest test_core test_games test_controls test_entertainment test_pi_runtime test_audition test_bluetooth test_loudness test_mode -v`

Read `/home/admin/.config/agent-guidance/AGENT_OPERATING_BASELINE.md` after recovery.
Use repo guidance and Ponytail skill. Inspect live services/controls before changing
anything; do not trust historical sleeping flags. Never print tokens/env credentials.
Host voice health is authenticated `http://127.0.0.1:8767/health`; read its token in
memory from the existing private runtime file. Keep all hot work on runner-fast.

## 2026-10-24 local-audio continuation

User requested developing/auditioning here instead of outside, and mono output.
All seven comparison WAVs verified mono24kHz. Added `audition_local.py dobby` or
`audition_local.py strongbad`; clips use the desktop default sink and its existing
volume, never SSH or Pi controls. Current desktop sink Sony WH-1000XM5 at43%.
Dobby three-clip and StrongBad four-clip passes completed via paplay; user asked
Dobby to be repeated, replay started with3second gaps. No voice selection made.
Preflight rejects invalid/stereo clips before audio and caps each set at90seconds.
Host55tests/Pi45tests pass; source/deployedPi pumpkin.py SHA256 identical.
Host health8766/8767 authenticated200, Bluetooth connected, savedPi100%/awake/normal.
No new radio/pairing/WiFi changes, no outside audition restarted. Stereo-Link icon
remains unverified; mono voice does not disable physical Stereo-Link searching.
The prior runtime Dobby recommendations are archives; current production A/2
remain unchanged while local likeness feedback is pending.

## Local recording input — latest

Audacity user Flatpak3.7.8 installed/open, PID3637760, window18874643. User reports
bad recording quality. Default capture was Sony headset mic; desktop default is
now `bluez_output.AC_80_0A_5E_77_05.1.monitor` for original-clip capture. A bounded
observer verified the user's Audacity recording stream on this digital monitor,
float32 stereo44100Hz, while headset remains A2DP. No recording content read or
saved by agent. User is operating recording; do not stop/close unsaved project.
Future mic use needs source `bluez_input.AC:80:0A:5E:77:05` selected again.
Cua desktop daemon runs with DISPLAY:0, WAYLAND_DISPLAY:wayland-0, XDG_RUNTIME_DIR
/run/user/1000 and user bus. Persistent MCP via exec session33209 retains UI
snapshot context; CLI one-shot contexts cannot reuse snapshots for clicks.
No more porch changes or voice candidate selections; new take quality pending.

## New user Dobby reference — 2026-10-24

User exported `/home/admin/Documents/PumpkinTalk/dobby1.wav` (outside source
symlink). Original preserved and copied under runtime/dobby-user-20261024.
45.801sec, stereo44100Hz PCM16, peak-5.78dBFS, zero detected clipped samples,
channel correlation0.9993. User explicitly confirms ENTIRE clip is Dobby. Do not
infer speaker changes from ASR text (parent corrected that mistaken inference).
Two short references at2.35–12.90 and7.15–21.15sec tested with currentQwen1.7
settings;2novel lines each, all4word checks exact. Matched previews and original
reference are ready; `audition_local.py dobby-new` compares original/currentA/
newintro/newspeaking. Whole source retained for other reference choices. No need
to ask for more Dobby samples yet. User says StrongBad still needs work too.
Added neutral spoken labels to local comparisons, and preflight blocks playback
while Audacity has a capture/monitoring stream, avoiding contaminated samples.
Host56tests pass. Production profiles and porch untouched; no winner chosen.
