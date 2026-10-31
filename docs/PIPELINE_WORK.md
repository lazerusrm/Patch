# Porch integration — deployed 2026-10-24

Owner: main PumpkinTalk conversation. Active isolated checkout:
`/mnt/runner-fast/agent-builds/tmp/pumpkin-encounters-20261024/worktree`,
branch `feat/visitor-ceremonies`, based on d7dd5a1 plus a snapshot of existing
uncommitted voice/music/effects work. No child workers. Preserve this checkout:
the live host backend runs from it. The shared source checkout is untouched.
Do not cherry-pick the whole dirty tree; it includes other agents' work.

Coordination: `/home/admin/Documents/PumpkinTalk/coordination.md`.
HAL owns the separate Protect bridge and API guide `PROTECT_BRIDGE_API.md`.
No credentials belong in these documents or patches.

## Installed behavior

- C920 microphone retained; trigger lowered from400 to100 using measured speech
  levels (normal p95 RMS258, quiet156). Adaptive DC-removed energy gate,400ms
  onset buffer, separate7sec start wait/10sec speaking allowance,700ms end silence.
  Tiny clicks rejected; quiet pauses no longer disable ordinary conversation.
- Three chronological webcam frames over0.8sec, bounded contact sheet; fresh
  doorbell snapshot fallback. Media stays in memory or `/dev/shm`.
- Independent ASR, vision and dialogue locks; bounded vision wait after greeting.
  Late visual results cannot speak over the ongoing encounter. Short-word VAD and
  low-confidence ASR rejection. This is half-duplex gating, not full-duplex AEC.
- Varied Hat openings, group opening, visual assessment, two endings per house,
  shuffled houses. Requested sorting keeps the Hat for follow-up conversation.
- Farewells after2sec of confirmed absence following a near visitor; camera
  failure or motion-ended events alone cannot trigger them. Shrinking-box retreat
  detection exists but remains disabled until the porch view is calibrated.
- One worker controls music, listening, pumpkin and doorbell. Ring events interrupt
  idle capture/music and run one of three short non-repeating scenes at a pause.
  Failed cues skip their dependent punchlines. Stale/repeated rings are suppressed.
- Separate doorbell butler persona, provisionally using the existing approved Hat
  voice. Optional `DOORBELL_VOICE` selects another existing character voice.
 54 fixed lines pre-rendered, three original short effects generated locally.

## Actual capabilities and limits

Protect ring events and doorbell output work. Fresh snapshot→vision request passed.
HAL fixed truncated uploads and cancellation races. Live three-line expression
scene completed in15.6sec; snapshot/vision completed in9.22sec.
`finished` means RTP sending completed, not a speaker acknowledgement.
The G4 speaker was reported quiet; bridge compression is enabled, but human
outdoor audibility still needs checking. No owner-intercom detection is available.
The doorbell microphone is not connected to recognition; C920 remains the input.
Protect person/motion events have not been observed live, so webcam presence
remains authoritative. A real end-to-end ring→new controller scene and the new
mic threshold still need an owner field check.

Indoor UP Chime supports custom tones on real button presses, but no remote cue
playback on this API. HAL reports the owner asked to retain the default ringtone;
it remains default at volume80/repeat1. Uploaded fart+ding is available for later.
Scenes route unavailable chime effects to the doorbell; Hat ceremony fanfare is
skipped when remote chime playback is unavailable.

## Deployment and verification

Pi `/home/pi/pumpkintalk`: owned controller files installed with checksum checks,
backup `.pipeline-backup-20261024` (private), original env preserved. No gain,
Bluetooth pairing, voice-profile or saved control edits. Bridge token provisioned
in a private600 file. `evidence/deployed-files.json` lists installed source hashes.

Host backend override:
`~/.config/systemd/user/pumpkin-backend.service.d/30-visitor-pipeline.conf` points
to this checkout, reusing original model runtime. Separate enabled service
`pumpkin-unifi-tunnel` exposes host8768 on Pi loopback; original tunnel unchanged.
Original unit/override absence recorded in `runtime/host-service-backup/`.

Validation:74 host tests,62 overlapping system tests,67 Pi staged tests passed.
After the final Hat follow-up fix, all7 focused input-pipeline tests passed on both host and the installed Pi runtime.
See `evidence/integration-*-tests.txt`, `evidence/pipeline-tests.txt`,
`evidence/live-integration-check.txt`, and `evidence/pi-deploy.txt`.
Guided dual-mic test favored C920 over USB at existing gains; raw recordings
removed. Follow-up threshold field check timed out without a visitor; no capture
was made. No pending diagnostic jobs or stored visitor images.

## Selective integration and rollback

`evidence/visitor-pipeline.patch` is the complete source/test integration diff
against `base/{pumpkin,backend,core}.py` and unchanged test baselines. It excludes
other agents' preexisting content/music/voice changes. Generate the three effects
with `python3 make_porch_effects.py`, then render fixed lines with `warm_porch.py`
using the normal runtime environment. Do not overwrite another agent's checkout.
`git apply --check` passed against current shared source. Patch application checks are separate from behavior verification.

Pi rollback (from this checkout):
`ssh pumpkin 'python3 -' < rollback_pi_pipeline.py`.
It verifies installed code hashes before restoring original owned files and only
the three integration env keys. It preserves later unrelated env changes, caches,
controls and voices. A later owned-code edit blocks rollback for manual review.

Host rollback: remove only the owned `30-visitor-pipeline.conf`, run
`systemctl --user daemon-reload` then `systemctl --user restart pumpkin-backend`.
Stop/disable `pumpkin-unifi-tunnel`; remove its owned unit if desired, then reload.
HAL owns bridge rollback; do not alter its service or credentials automatically.
These rollback instructions are prepared, not executed. The isolated runtime,
Pi backups and token files must remain while this installation is active.


## Live walk-up follow-up

Owner heard pumpkin clearly. Guided threshold100 check captured/recognized speech
and both expected key words (`evidence/guided-walkup-check.txt`). Sorting and
farewell states observed. Real ring reached bridge while visitor left webcam view;
this exposed ring cancellation by the departure predicate. Installed fix honors
fresh bridge presence and holds positive presence30sec during a ring scene.
Eight focused porch tests pass on host/Pi; updated rollback hashes recorded.
Protect person events are now verified live (HAL correction09:22), ordinary motion
is not emitted. person.ended is not vacancy evidence.

Owner heard explicit doorbell samples but reported low quality and clipped ends.
Installed250ms leading/500ms trailing silence for doorbell playback (total bounded
to20sec), with payload framing assertions. Webcam acoustic measurements retained
as metrics only; no raw recording saved. Source speech recognizes7/7 words;
acoustic speech recognized1/7 then0/7. Padded processed/raw comparison both0/7.
Human clarity feedback remains authoritative; loudness/compression is not yet
confirmed as the cause. HAL asked to review codec/packet metadata read-only.
Evidence: doorbell-{source,acoustic,quality}-check.txt, doorbell-samples.txt,
{pi-,}doorbell-padding-tests.txt. Normal controller restored after every test.


## Latest live state: voice audit and indoor Bluetooth routing

Doorbell now uses X-Loudness:raw with250ms leading/500ms trailing silence. User
preferred it to heavy compression. HAL deployed real-time packet pacing
(initial_burst0.001) and>=1sec session gap; codecs preserved. After pacing, webcam
recognized5/7 then0/7 words. One earlier raw trial scored7/7; recognition remains
inconsistent, so doorbell acoustic quality is not fully resolved. No further EQ
or attenuation selected. Main porch speaker audit is complete for all7 actors:
no source/capture clipping, peaks about-6dBFS, largely intelligible. Patch/Boo
recordings transcribed perfectly. See docs/VOICE_AUDIT.md and metrics summary.

Nibbles content rewrite DEPLOYED:8 short jokes,3 greetings, fallback, boo reactions
and personality direction; original voice preserved.15 new lines pre-rendered
and copied under live cache version reference-v4-L20-matched. Original
entertainment.json added to Pi rollback manifest and backup. Installed hashes
updated. All54 earlier fixed porch lines already exist in the live cache version.

Optional local chime routing DEPLOYED and disabled until CHIME_AUDIO_OUTPUT is
configured. CHIME_PREROLL_SECONDS defaults to0.25. A local chime receives the fart,
fanfare and spell ding; pumpkin dialogue retains its own output. Disconnected
chime failures skip cues without breaking sorting. Host10 porch integration,
14 runtime and9 mode tests pass; latest Pi integration checks also pass.

Speaker supplied by owner is named Clip Speaker. Pathfinder Go is the only paired
speaker. Auto scans did not discover Clip Speaker; owner confirmed pairing mode.
A classic-Bluetooth scan is the next diagnostic; do not reset/re-pair Pathfinder.
Pairable was initially off; preserve it after commissioning if temporarily enabled.
No CHIME env keys or Bluetooth settings have been changed yet.

## Current checkpoint — dual cameras and continuous spatial scenes

This section supersedes older speaker-pairing and deployment status above.
Clip Speaker pairing was abandoned at the owner's request. No bond was created;
scan/pairable are off and the original Pathfinder reconnect timer remains active.
Optional chime routing is disabled. UniFi chime keeps its default sound.

Continuous cast routines and spatial USB routing are deployed. The entire scene
is rendered before playback, with180ms reply gaps and quiet-edge trimming. No ASR
windows or Bluetooth reconnections occur between scripted pairs. Dobby stays on
Bluetooth; post-transformation Voldemort moves to the internal USB speaker.
The USB PCM mixer is enforced at90%, below the owner's92% reset threshold.
Measured relative timing offset is60ms; live transformation36.32sec and roommates
12.90sec completed. Evidence: continuous-bit-live.txt, speaker-alignment.json,
continuous-routing-tests.txt, pi-continuous-routing-tests.txt. Individual spoken
conversation still uses energy-based input detection, not full acoustic echo
cancellation; noise can consume the10sec capture limit. Do not claim that solved.

Both cameras now feed the same Hailo detector sequentially. Doorbell snapshots
arrive on a separate bounded worker at no more than1Hz, so a camera request does
not block local detection or event polling. Cached frames expire after3sec.
Per-camera counts remain separate; combined presence uses their maximum, not a
sum. Doorbell images are used for visual replies when it sees people and the
webcam does not. Positive porch presence prevents a webcam-only false departure.

`porch_crossing.py` uses anonymous, short-lived footpoint continuity, a deadband,
two observations on each side, and a bounded path segment. Ambiguous associations,
lost interior tracks, remaining group members, camera gaps and turnarounds suppress
farewells. Candidate PORCH_GATE is `.48,.74,.78` (x1,x2,y). Direction actions remain
OFF (`PORCH_CROSSING_ENABLED` absent); all automatic departure cues are paused
while the connected camera pair is uncalibrated. A bridge failure also cannot
manufacture a departure. Explicit person.ended is never vacancy evidence.
Hailo coordinate order was checked against the upstream model-zoo detection
postprocessing: ymin,xmin,ymax,xmax. No new detector dependency was installed.

The owner tilted the webcam down: it now shows the walkway and street, replacing
the nearly-all-sky view. Doorbell retains the better porch-edge view. A guided60sec
walk window collected53 doorbell and58 webcam frames; neither saw a person.
Doorbell frame age median0.63sec/max2.30sec. Therefore no real crossing has yet been
validated; do NOT enable farewell actions from this empty run. User has been asked
when ready for another guided pass. Metrics only: evidence/camera-walk-summary.json
and camera-walk.jsonl. HAL confirmed native Protect events lack coordinates and
direction; no Protect line or recording settings were changed.

42 host dual-camera/runtime/mode/presence tests and31 Pi tests passed. Live service
is active. Installed hashes are evidence/deployed-files.json and Pi backup
installed.json. The existing backup manifest includes porch_crossing.py and earlier
routine_audio.py/games.py additions. Updates use runtime/update_owned_files.py,
which refuses concurrent edits. Primary/shared source remains untouched.

StrongBad reference remains blocked: owner's strongbad.mp4 has no audio stream;
owner will find another. No Strong Bad voice profile was changed. Broader Patch/Boo
joke rewrite and short clarification fallbacks are being precached; see the next
checkpoint for deployment confirmation. Seven-voice audit caveat is now explicit
in docs/VOICE_AUDIT.md (representative staged clips, not every live cached WAV).

## Comedy deployment checkpoint

Patch/Boo's16 short joke slots have been revised around the porch, failed scares,
and being stuck in a pumpkin. Seven error fallbacks now ask for repetition in
character instead of launching unrelated stock jokes.23 fixed lines were rendered
under the exact live cache version and copied before activation; core.py and
entertainment.json are deployed with updated ownership hashes.17 host content/core
checks and19 Pi content/core/crossing checks passed. These are authored improvements,
not a claim that the owner has approved their humor or audited all new performances.

The selective integration patch was regenerated and `git apply --check` passed
against the current shared source without modifying it. It excludes other agents'
preexisting dirty voice/music/content work. It includes continuous/spatial routines,
dual-camera tracking, and current authored content. Later VAD changes require one
final regeneration. Initial deployment helper is for an unmodified first install;
existing live installation uses the hash-guarded update helper instead.

## Speech detector deployment checkpoint

WebRTC VAD mode1 is now enabled with `MIC_VAD=webrtc`, retaining MIC_THRESHOLD100
and0.7sec trailing silence. Every20ms frame reaches VAD, including quiet frames;
the VAD path uses the measured fixed threshold instead of escalating it after
noise. Ambient sound can no longer extend an utterance merely by being loud.
This remains half-duplex input gating, NOT acoustic echo cancellation.

Pinned `webrtcvad-wheels==2.0.14.post1` is installed in the private Pi directory
`/home/pi/pumpkintalk/.visitor-vad`; system Python packages are unchanged. The pin
and install command are requirements-visitor-audio.txt. `MIC_VAD=energy` restores
the previous energy gate. Rollback removes the owned env setting; the small private
package directory remains inactive and can be removed after rollback if desired.
Upstream package/API: https://github.com/daanzu/py-webrtcvad-wheels and
https://pypi.org/project/webrtcvad-wheels/2.0.14.post1/ .

Second acoustic comparison processes EVERY frame through the real detector:
8sec ambient:4.44sec energy activity vs0.20sec VAD speech activity;
12sec speaker recording:7.16sec energy activity vs4.16sec VAD speech activity;
quiet reference scaled to RMS156:3.46sec active in both. These are short-sample
activity measures, not recognition accuracy or proof of improved human latency.
No raw recording retained. Evidence: vad-acoustic-comparison-every-frame.json.
First comparison short-circuited quiet frames and is diagnostic only, superseded
by the every-frame comparison. Eight input pipeline tests passed on host and Pi.
Real quiet human speech, music rejection and conversation timing still need a walk-up
check; no claim that all latency/echo issues are solved. The old process logged
microphone disconnect during service stop; the replacement is active and the
installed version/import/silence check and all owned file hashes pass.

Final selective patch regenerated again after VAD changes; apply-check PASS against
current shared source. Final live evidence is evidence/live-final-check.json:
service active, all13 owned file hashes match, VAD enabled, USB PCM90%, crossing
actions false. Active isolated checkout and Pi backups retained for resumption;
no worktree cleanup or commit of other agents' changes was performed.

## Owner regression report and audit continuation

Owner walked several times after the previous checkpoint, reports severe lag and
Dobby sounding wrong, and requests audit of everything/tighter responses. Do not
repeat the prior claim that timing is acceptable based on unit tests alone.
Current durable findings/actions are docs/EXPERIENCE_AUDIT.md. Concrete major issue:
12sec raw audio round trip30.09sec vs recognizer0.05sec on weak2.4GHz porch Wi-Fi.
All170 fixed short lines now precached; no silent alternate voice engine; compact
Opus uplink32k/downlink64k; nonblocking visual context; smaller camera payloads;
warm Bluetooth preparation0.8sec after PCM-ready tone check. Dobby reference remains
selected user sample; reported delivery regression still needs perceptual check.

New rollback custody: idle_music.py original preserved after hash verification,
manifest includes it (14 owned files total). Backup guard remains active. Host
backend owned drop-in now sets PUMPKIN_MODEL=gpt-6-luna and
PUMPKIN_REASONING_EFFORT=none. Pi TTS_URL now localhost8766/tts; original voice server
8767/profile unchanged. Rollback KEYS includes TTS_URL and warm-preroll setting.
Current-cast acoustic audit running via runtime/audit_live_cast_short.py, with
180sec controller restore timer; no competing HAL playback requested. Fixed-cache
warm/copy jobs completed. Need collect final cast audit, actual-speech compact
roundtrip/voice reply timing, HAL compact-input response, regenerate selective
patch and update installed hashes before handoff. Do not claim all latency or
Dobby quality fixed without those limits stated.

## Final audit checkpoint — owner latency/voice regression follow-up

78 host/58 Pi focused checks pass. All198 audited short phrases (170 existing
slots +28 quick replies) are present. Cached hello/how-are-you/thanks/trick-or-treat
and explicit goodbye bypass text generation and speech generation. Complex/mixed
questions still use the model. Source warm_porch.py now reconstructs greetings,
quick replies, reactions, controls, jokes, and cast/non-cast fixed game prompts
under the normal service environment; non-cast games/stories were NOT exhaustively
precached in this live pass, so do not claim every possible path is warm.

Sorting Hat is now one cached composite waveform (250ms beat), rather than separate
speaker opens and VLM/TTS gaps. Live: file ready0.139sec,23.21sec actual continuous
performance,27.052sec total including preparation. This is a theatrical performance,
not27sec dead time. Background costume observation is carried into conversation.
Dobby/Voldy continuous spatial scenes and USB90% ceiling remain unchanged.

Short0.8sec warm preparation failed the full-cast acceptance and was reverted to
3sec. Pure-tone success did not establish real voice onset quality. Persistent-output
probe also transcribed no words, so NO new persistent audio engine was deployed.
Main speaker likeness/delivery therefore needs owner listening, not another claim
based on ASR. Selected Dobby profile/reference/seed/engine remain exactly unchanged;
silent alternate-engine fallback removed.0.3sec acoustic tail guard retained.

Compact doorbell input verified live with HAL:30KB Opus upload0.277sec, decode83ms,
complete5.512sec. No proof of improved doorbell acoustic clarity. Chime current
assignment is fart_short80%, changed outside HAL; preserved, not restored blindly.

Network controlled test: controller paused in both cases, BT connected1.638sec vs
disconnected0.705sec for3sec raw audio. Earlier3.85vs0.633 also stopped camera/music
and is confounded. Original speaker reconnected and timer/controller restored.
HAL mapped a single U6 LR AP and separate MikroTik gateway; both AP/Pi see−74dBm.
Owner says a powerful router is5ft away. Asked which physical box; pending. No
Ethernet cable available now (owner answer).5GHz cloned-profile trial timed out;
original UUID0bbcf27c-… restored automatically; clone4345e372-… deleted. No permanent
Wi-Fi/AP change. Failed transient unit reset; dummy TCP listeners closed.

Actual generative greeting probe (before quick routing): ASR1.449sec, model8.897sec,
Dobby synthesis/download4.211sec →14.557sec audio-ready before speaker startup.
That greeting is now cached. Novel question timing remains variable. Fast-tier
benchmark did NOT improve (2.751 vs2.487sec), so NOT enabled. Other model trials
were about2.9sec; no further model swap on those one-off results. Backend remains
Luna/none. Restarted final backend to load strict Opus decoding changes.

Pi owned files14; original idle_music.py preserved before its two timestamp fields.
All owned hashes and live state verified in evidence/audit-live-final-check.json.
Selective patch regenerated with current core/backend/idle/music/Hat/quick/codec
changes; apply-check PASS against untouched shared source. Active isolated checkout,
source snapshots, rendered cache, evidence, and Pi backup retained for resumption.
Remaining: owner Dobby listening feedback, general-response latency, microphone
experience with a real visitor, verified outward crossing, and StrongBad audio
sample. True AEC remains unimplemented; current capture is half duplex + VAD.


## Microphone-measured arrival latency follow-up

Latest owner priority: minimize first detection → first audible speech, measured
with C920 microphone, not HTTP/player-open timing alone. Controlled benchmark of
old1sec confirmation +3sec padding measured4.183sec to the first coded sound.
Actual staged Pumpkin.run handler with real webcam, real idle-music worker,
actual Speech.play, and a synthetic person-detection result measured0.304sec
(clear/near person) and0.291sec (moderate confidence). First pulse and all10/10
coded pulses survived; neither microphone capture clipped. These are controlled
detection-result tests, not timed real visitor walks or camera exposure latency.

Dobby voice verification used the unchanged cached first greeting. Spectral
source/microphone alignment measured first voice onset0.20sec (zero warm prep),
0.38sec (150ms prep),3.28sec (3sec prep). Zero-prep full/first-second correlation
was0.731/0.706. ASR was unreliable for this quiet self-recording (RMS145), including
the full3sec control; it cannot establish delivery/voice likeness. A separate
known-delay spectral-matcher check recovered the200ms injected offset. The owner
still needs to judge Dobby's performance; no reference/engine/seed changes.

LIVE changes: strong nearby webcam boxes (confidence>=.85, area>=.04) can activate
immediately; other confident people confirm for150ms. Existing8sec absence/reset
and pending-arrival semantics remain. Idle music/listening releases on the first
confident candidate; it cannot restart capture during the short confirmation.
An old idle-ASR retry backoff no longer delays a newly confirmed arrival. Webcam
scan pause reduced200→20ms; live controller consumed49.2% of ONE CPU core in a5sec
sample. Detection→player-open telemetry now accompanies real arrival playback.

Only recently interrupted, established music can skip Bluetooth preparation:
>=3sec played, energetic source audio within750ms, checking actual recent source
PCM so a silent tail does not mark the speaker warm. Cancellation is recognized
independently of aplay's nonzero SIGTERM exit. Cold speaker retains3sec protection;
we did not reenable the earlier broad45sec warm-audio rule. The warm default is0.

Validation:82 host/76 Pi staged checks pass. Three owned Pi files updated with
hash guards; all14 installed hashes match, pumpkin + original Bluetooth timer
active, USB still90%, voice-cache profile unchanged. Current state idle_music.
No diagnostic controller/recorders or restore timers should remain active.
Evidence: detection-audio-mic-baseline.jsonl, controller-detection-mic.jsonl,
controller-dobby-onset-mic.jsonl, controller-dobby-spectral-mic.jsonl,
acoustic-matcher-self-check.json, detection-latency-{host,pi}-tests.txt,
detection-latency-deployed.json. Diagnostic source: runtime/controller_latency_check.py
and runtime/acoustic_match.py. Raw microphone recordings were not retained.
Selective integration patch regenerated and apply-check PASS against shared source.
Primary source remains untouched; worktree/runtime/backup retained for resumption.


## Porch refresh after webcam move (live; owner walk pending)

Owner requests: better jokes/flows/doorbell intelligibility, music+10%, correct
approach/exit and doorstep occupancy. Owner accepted guided test, then explicitly
said to give them time: THEY WILL SAY WHEN READY. Do not start the guided walk
from a presence event or after an arbitrary timeout.

Music LIVE: all30 Pi tracks boosted by amplitude1.1 (+0.83dB), original assets
and per-file original/installed hashes in .pipeline-backup-20261024/music-gain.
Runtime helper boost_idle_music.py is hash-guarded/idempotent. No speech/mixer
volume change; internal USB ceiling90% remains. Music hashes all match. Music
rollback is separate from code rollback: verify current hashes against the music
manifest and restore matching originals; do not overwrite concurrent asset edits.

LIVE content: Nibbles8jokes/3stories/greetings/fallback/stock replies/departures
rewritten as an inept haunter. Removed fake ministries, random objects and
constant candy-theft confessions. Three weak Patch lines tightened. Six short
doorbell scenes, at most a short doorbell setup and pumpkin payoff; fanfare is
chosen only when chime output is really available. Removed the invented30sec
presence hold after a ring.14 new cached identity/hearing replies bypass model
and synthesis. Removed25% random Hat override of other character greetings;
Hat mode/selected Hat still performs its ceremony.109 refreshed cache entries
(including3Nibbles stories) verified present before publishing.

LIVE clear doorbell renderer: explicitly selected local Pocket TTS Alba, not a
Hat clone or a silent fallback for another character. Dedicated doorbell-only
HP280/LP5k/3k presence/compression/-15LUFS TP-3 path; cached prefix doorbell-.
Offline exact client64k Opus + bridge96k/48k→24k path measured-15.37LUFS,
-2.97dBTP, zero clipped samples. No acoustic clarity claim before owner audition.
Short spoken cues avoid long robotic arguments between speaker sessions.

LIVE Bluetooth preparation can run concurrently with first doorbell cue, then
pumpkin waits for preparation completion and uses its <750ms warm hint. This
removes a separate3sec lead-in after the doorbell cue. Physical mic test:3.733sec
preparation, then0.275sec to first sound; first pulse and10/10 coded markers
preserved. First lower-level attempt got9/10 amid noisier capture; retained stderr.
Main voice references, engine and seed untouched. Cold protection remains3sec.

LIVE tracking observations: webcam now sees street/shrubs, not doorstep. Current
webcam walkway filter excludes boxes with bottom<.68. G4 is doorstep authority,
with explicit approaching/at_doorstep/leaving/clear/unknown/uncertain status and
doorstep_people. Crossing no longer requires two frames EACH SIDE at1Hz; it
uses opposite sides across hysteresis with elapsed-time-aware matching. A person
still visible farther down the webcam path no longer vetoes a measured G4 exit.
Groups/occlusions/stale frames still suppress uncertain departure.
AUTOMATIC CROSSING ACTIONS REMAIN OFF pending the guided real walk. Current gate
unchanged (.48,.74,.78), no claim it is calibrated after this new webcam angle.

HAL completed authorized bridge default/live limiter fix C (0.89→0.62) at commit
c45435c on feat/protect-bridge. Raw path unchanged.15 bridge tests pass, five
codec controls below-1dBTP. Restart17:42:37 MT instance aa31ef3f9132. See top-level
coordination.md for rollback. Parent clean renderer continues X-Loudness:raw.
No new API B, no chime/router changes. HAL can passively capture talkback traffic
when parent announces the owner is actually READY; HAL will not generate audio.

Validation:87 host/81 Pi staged tests pass.14 owned installed hashes match, all
109 refreshed cache entries and30 music hashes match. Pi + Bluetooth timer active,
host backend/voices/bridge/both tunnels active; backend ready Luna. Host backend
restarted to load new Nibbles personality; voice service unchanged. Current
status idle_music/porch clear/doorstep_people0/crossing_actions false.
Selective patch regenerated and apply-check PASS; shared source untouched.

Next action after owner says READY:
1. Announce READY acoustic test in /home/admin/Documents/PumpkinTalk/coordination.md
   so HAL can do passive capture; no competing playback.
2. Run Pi stage porch_guided_refresh.py with normal service paused,420sec systemd
   restore watchdog and subprocess timeout360; ALWAYS restore controller in finally.
   Script is already warmed (10 guide clips +2 comparison clips), source matches
   this checkout. It instructs approach/stand/leave/return, compares C920 gain5vs7
   and USB with visitor phrase after an internal chime, auditions old Hat vs clear
   Alba on the doorbell, and plays two revised Nibbles jokes (hound/invisibility).
3. Retain JSON geometry/metrics only, no audio or images. Inspect actual phase
   traces before enabling crossing actions; fix gate/association if needed.
   Compare visitor phrase word matches, clipping and levels before changing live
   microphone gain/input. Test restores C920 gain5 itself. Owner speech stays RAM.
4. Ask owner which doorbell voice/joke worked after they return. Do not declare
   humor, intelligibility, generic AI response latency or exits solved without
   the real evidence. Novel model+TTS turns remain variable and may still be slow.

Evidence: porch-refresh-{host,pi}-tests.txt, porch-refresh-final-warm.jsonl,
porch-refresh-deployed.json, clear-doorbell-codec-audit.json, prepared-output-mic.json,
music-gain-applied.json, porch-guidance-ready.json. Current-camera JPEGs removed
after inspection. Runtime helpers and stage retained; no owned workers.

Digital clear-doorbell source ASR check:6/6 expected words recognized, no hardware
playback. Evidence clear-doorbell-source-asr.json. Physical listening still pending.
