# Live experience audit — 2026-10-24

Owner reported long delays on repeated walks and degraded Dobby delivery. Earlier
unit tests and source-only voice checks did not establish acceptable porch timing.
This pass follows the live camera→capture→upload→ASR→reply→voice→speaker path.

| Area | Finding | Current action / evidence |
|---|---|---|
| Porch network | Pi on2412MHz, RSSI−75dBm.12sec raw WAV upload/ASR round trip30.09sec; recognizer0.05sec. Same network5GHz much weaker. | No Wi-Fi config change. Compact audio both ways; network-transport-audit.json. |
| Initial speech | Two Dobby greetings and other special-character openings absent from cache. | All29 greetings/fallbacks verified present. greeting-cache-audit.json + greeting-warm-timing.jsonl. |
| Other fixed lines |74 of170 audited short lines absent: jokes, reactions, controls, cast lines and Hat verdicts. | All170 initially audited entries plus28 new quick replies now present (198). fixed-cache-before-audit.json, fixed-cache-audit.json, fixed-precache.jsonl. Stories, non-cast game prompts and arbitrary conversation were not fully precached in this live pass. |
| Mic transport | Lossless zlib worked well for silence, but full-level speech still161KB→147KB/5.77sec. |32kbps Opus upload, bounded decode back to16kHz PCM. Zlib/raw remain accepted. Quiet reference at RMS156: raw and Opus each recognized5words; quiet-codec-audit.jsonl. |
| Common exchanges | Hello/how are you/thanks/trick-or-treat and explicit goodbyes previously reached the model. |28 precached replies plus existing farewell bank now bypass model and synthesis. Mixed questions remain generative. Quick-route integration test verifies only ASR is requested. |
| ASR | Recognition itself is usually much shorter than network delay. Confidence/no-speech filters remain. | Existing small.en model retained. Capture/VAD and network/ASR phase timing now logged without transcripts. |
| Dialogue | Sol/low4.57sec vs Luna/none2.44sec on one identical synthetic Dobby request. | Active isolated backend uses Luna/none. Prompt requests6–14words, answers actual visitor first, avoids forced verdicts. A later generative greeting probe was8.897sec for text and14.557sec total audio-ready, before speaker startup; that greeting is now on the cached path. Model latency remains variable. Fast-tier trial2.751sec vs standard2.487sec did not justify enabling it; no fast tier deployed. reply-model-benchmark.jsonl, compact-end-to-end-probe.json, fast-tier-benchmark.jsonl. |
| Vision pacing | Generated visual speech could follow greeting before listening began. Contact sheet and snapshot traffic competed with audio. | Observation runs in background and becomes context for next visitor reply. No extra unsolicited spoken turn.384px sheet;640px doorbell snapshots; audio requests use320px presence snapshots at most every2sec rather than starving detection; otherwise640px/1Hz. Text-only model wait does not hold camera priority. |
| Dobby identity | Live profile/reference/seed/engine match earlier selected user-reference setup. Existing two cached greetings cosine0.9456/0.8808 vs reference; earlier audition0.8825; Patch control0.5417. | No voice reference, seed or model changed in this pass. Identity similarity does NOT establish natural delivery or resolve owner feedback. dobby-live-identity-audit.jsonl. Await identification of offending greeting/reply/scene for a matched perceptual comparison. |
| Voice fallback | Client could fall back to another synthesizer after timeout/outage. | Removed silent alternate-engine fallback; selected renderer identity header required. No claim that historical fallback actually caused reported Dobby regression. |
| Voice transport | Full PCM downloads can add seconds over weak link. | Host backend authenticated /tts proxy calls unchanged voice server locally, sends64kbps Opus; Pi decodes/normalizes into ordinary mono24kHz WAV. Fresh Dobby6word probe1.41sec/15881bytes, selected Qwen1.7B header preserved. |
| Bluetooth start | Every utterance had3sec preparation. Shortening it blindly loses onsets. | Corrected recorder-ready test:3sec tone delay0.22sec;0.2sec lead loses beginning (delay1.38sec);0.7sec lead preserves onset (delay0.18sec). The full-cast follow-up did NOT validate0.8sec: four voices transcribed nothing and Dobby/Nibbles missed initial words. Default therefore restored to3sec. Shorter lead remains experimental, not accepted. Continuous-output probe also inconclusive and not deployed. tone-ready-onset-audit.jsonl, current-cast-acoustic-audit.jsonl, continuous-output-probe.jsonl. |
| Sorting Hat pacing | Separate opening and verdict reopened the speaker and could wait for VLM/TTS between lines. |Cached opening+verdict now joined into one PCM file with250ms beat. Live file ready0.139sec,23.21sec continuous performance,27.052sec total including cold preparation. Observation remains background context for the follow-up. continuous-hat-live.json. |
| Physical voice move | Dobby outside, post-spell Voldemort inside pumpkin. | Continuous two-track routine retained; USB90% cap,60ms relative delay unchanged. Earlier36.32sec transformation/12.90sec roommates verified. |
| Coming/going | Real walks logged an incoming crossing, but no verified outward crossing. Column can occlude visitors. | Actions remain disabled. Shadow logic is conservative; no farewell on lost/stale/ambiguous track. Anonymous footpoint/frame-age metadata is now logged during ordinary walks, avoiding a narrow test window. Need an observed outward pass before enabling. |
| Doorbell speech | Earlier raw/padded sound quality variable; raw upload also uses same slow radio. | HAL deployed compact input. Parent live test:30KB audio/ogg uploaded0.277sec, decoded83ms, finished5.512sec total. Existing output codec/pacing/padding remain. No claim that doorbell acoustic clarity is solved; compact-doorbell-live.json. |
| Indoor chime | Clip Speaker abandoned by owner; UniFi chime default retained. | Local-chime path disabled, no pairing retries. HAL now reads the physical UniFi chime assigned to fart_short at80%, changed outside its bridge; parent preserved that concurrent setting. |
| Strong Bad | Supplied MP4 has no audio. | Owner finding replacement; no new voice tuning performed. |

78 host and58 Pi targeted checks passed at the final source checkpoint.
New microphone recordings are RAM-only and discarded. The first short-preroll
speech test and first tone test had unreliable recorder startup alignment; they
are retained as diagnostic failures, superseded by the PCM-ready barrier test.
No human likeness approval or complete end-to-end latency acceptance is inferred
from ASR scores, cache inventory, or unit tests.

Active code remains in isolated branch feat/visitor-ceremonies under
/mnt/runner-fast/agent-builds/tmp/pumpkin-encounters-20261024/worktree. Shared primary
source remains untouched. Pi original idle_music.py was hash-checked, backed up,
and added to the owned manifest before its two playback-timestamp additions.
Rollback script restores original source/settings including TTS_URL. Host backend
model/settings live in the existing owned30-visitor-pipeline.conf override.

Official model references consulted for supported effort settings:
https://developers.openai.com/api/docs/models/gpt-6.1-sol and
https://developers.openai.com/api/docs/models/gpt-6-luna . Current application
benchmark, rather than documentation alone, motivated the latency setting change.

Network follow-up: the controlled test paused the controller in BOTH cases;3sec raw audio took1.638sec with BT connected vs0.705sec disconnected. Earlier3.85vs0.633 also paused camera/music, so its larger ratio was confounded. HAL confirms a single U6 LR AP, both AP and Pi measuring about−74dBm, no WLAN rate limit. The gateway is a separate MikroTik. Owner says nearby router is5ft away; identifying which physical device remains pending.5GHz temporary clone timed out, original restored automatically, clone deleted. No persistent Wi-Fi/AP change. Owner has no Ethernet cable now.

Remaining acceptance: Dobby delivery needs owner listening feedback; microphone-back acoustic scores were inconsistent and cannot certify likeness. Open-ended generative responses can still be slow. True acoustic echo cancellation is not implemented (capture is half duplex with VAD). The post-play listening guard is0.3sec. Departure actions await a verified outward pass.

Final live checks:14 owned hashes match, controller and Bluetooth timer active, original Wi-Fi profile restored, USB90%, default preparation3sec. Detailed metrics in evidence/audit-live-final-check.json. Final selective source patch apply-check PASS against the shared source. Normal warm-up helper expanded for reproducible offline pre-rendering.


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


## Research-informed comedy refresh (awaiting porch audition)

[Building a joke, BBC Maestro](https://www.bbcmaestro.com/blog/how-to-write-a-joke)
emphasizes surprise, ruthless editing, delivery, and testing the performed result.
[Chris Head on scene structure](https://www.comedy.co.uk/pro/inside_track/how-to-structure-sitcom-scenes/)
allows a short scene to work as setup/payoff; longer scenes need progression.
[Daniel Page on context and surprise](https://thecomedycrowd.com/the-2-fundamentals-of-comedy-writing/)
distinguishes a surprising but coherent payoff from arbitrary nonsense.

Application here: use real porch props, make the character's own ambition fail,
end on the concrete reveal, omit explanations after it, and give the visitor
space to answer. These are writing choices, not proof an audience will laugh.

Nibbles now wants to run a terrifying haunted house but is spectacularly bad at
it; removed the constant candy-theft confessions, fake ministry, paperwork and
random objects. Eight jokes, three stories, greetings, stock replies and exits
rewritten. Cut explanatory tags after delivery-driver/porch-light payoffs.
Doorbell bits are brief setup+one pumpkin payoff (or fart+payoff), using the
camera, button, carved face, and tiny candy bars. A short plain spoken doorbell
line keeps the little speaker from carrying a long gravelly performance.
Audition delivery and observe human preference before labeling any line a hit.
