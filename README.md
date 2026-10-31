# PumpkinTalk

A funny, cheeky, gently spooky porch pumpkin: Patch the ancient pumpkin, Boo the
stage-fright ghost, and Nibbles the dubious candy inspector. Hailo detects people
locally; Sol can comment on visible costumes from a temporary snapshot. Breeze
TTS 2 performs three original character voices, with ten LEDs following speech.

## Running installation

- Pi 5 + Hailo-8: `ssh pumpkin`, `pi@192.168.0.49`, Wi-Fi only; reserved address.
- Pi application: `/home/pi/pumpkintalk`; configuration `pumpkin.env`.
- Host source: `/mnt/runner-fast/agent-builds/pumpkintalk-20261023` (workspace `source/`).
- Pi: `pumpkin.service`, local fallback `pumpkin-tts.service`, `bluealsa.service`,
  `pumpkin-bluetooth.timer`. Bounded auditions use `pumpkin-audition.service`.
- Host user services: `pumpkin-backend`, `pumpkin-voices`, `pumpkin-tunnel`.
- Camera and microphone: Logitech C920, capture gain 5/15, threshold 400.
- Speaker: Pathfinder Go, classic Bluetooth `B1:2E:84:76:00:D9`, BlueALSA A2DP.
  Its BLE companion is not the audio device. The reconnect timer checks every 10s.
- Volume: Bluetooth defaults to 100%; use the speaker’s physical volume control.
  Voice adjustments change by 10 points (Bluetooth 50–100%, USB 50–90%).
  Saved volume and sleep state survive restart.
- Hailo driver, firmware and library: 4.19.0; local YOLOv8s person detector.

The host must remain on for transcription, VLM/dialogue and new character speech.
Prepared lines cache locally; Pocket TTS provides a simpler local fallback.
Fleet and administrator public keys authenticate SSH; no private keys or Codex
account credentials were copied to the Pi. Loopback HTTP ports 8766/8767 require
a separate mode-600 token and travel through a host-owned reverse SSH tunnel.

Crowsnest previously claimed the webcam at boot. Only `crowsnest.service` was
disabled to dedicate the camera to PumpkinTalk; other printer controls remain.
To restore its webcam use, stop both pumpkin services, then run
`sudo systemctl enable --now crowsnest` on the Pi.

## Voice commands

Speak in the listening gaps; playback is half duplex and has no barge-in.

- “Hey Pumpkinhead sleep” / “Hey Pumpkinhead wake up”
- “Hey Pumpkinhead I can't hear you” / “Hey Pumpkinhead be quiet”
- “Hey Pumpkinhead tell me a joke” / “Hey Pumpkinhead tell me a story”
- “Trick or treat”

Sleep stops automatic speech and lights while preserving wake listening. There
are 24 jokes, nine stories (playback capped at one minute), and six tricks/treats,
and an optional chocolate offering gag. (The custom jingles were retired on 2026-10-31.)
Visitors always keep their candy. One character stays with a group until departure.
On arrival, clearly visible costumes get affectionate cheeky verdicts, silly awards
or generous scores in that character’s style. Unclear views prompt a question.

## Check or stop

On the Pi:

```sh
cat ~/pumpkintalk/status.json
cat ~/pumpkintalk/camera-status.json  # camera telemetry during auditions only
sudo systemctl status pumpkin pumpkin-audition pumpkin-bluetooth.timer
```

Stopping an audition automatically resumes normal porch mode. To silence both:

```sh
sudo systemctl stop pumpkin-audition
sudo systemctl stop pumpkin
```

After stopping both, manual samples and a camera check are available:

```sh
cd ~/pumpkintalk
python3 pumpkin.py --say patch
python3 pumpkin.py --say boo
python3 pumpkin.py --say nibbles
python3 pumpkin.py --check-camera
sudo systemctl start pumpkin
```

The 2026-10-23 audition uses an absolute deadline of 19:28:31 MDT in
`audition.env`; restarting preserves that deadline. It rotates all characters,
greetings, jokes and stories with six-second listening gaps. Sleep pauses samples.
Its child camera monitor records counts/brightness only, never images.

## Lighting and audio

Ten 5V WS2812B: red physical pin 2 (5V), black pin 6 (ground), green DIN pin 19
(GPIO10/SPI0 MOSI). Power off before touching wiring. SPI0 is enabled and `pi`
belongs to `spi`. Brightness is capped at 15%; orange Patch, blue Boo, green
Nibbles. Direct 3.3V data worked in physical tests. A 74AHCT125 level shifter and
series data resistor improve reliability; use a separate regulated supply before
expanding the strip. With separate supplies, share ground, not their 5V positives.
The software brightness limit is not a power fuse.

Speech uses perceived loudness matching (-20 LUFS target), a -6dB true-peak target,
and a final 0.5 sample limiter. Cache version `breeze-v2-L20` distinguishes the
balanced audio. Bluetooth adds latency; exact LED alignment still needs acoustic
calibration. USB speaker tests above 90% previously caused peripheral dropouts.

## ESP32 WLED strip

An ESP32 running WLED (0.15, 290 LEDs, local Wi-Fi) joins the porch show through
`wled_strip.py`. Set `WLED_HOST=<address>` in the Pi's `pumpkin.env` (give the controller a
DHCP reservation); leave it unset to disable. While a character speaks, the whole strip glows
in their colour and swells with the voice; doorbell lines, dragon effects and scene cues
(blackout, lightning, fire, ghost, houses, lumos, house colours) use the whole strip. Frames
are WLED realtime UDP (DNRGB, port 21324) with a 2-second timeout, so between moments WLED
runs its own idle fire (Candle Multi: every LED a candle) or `WLED_IDLE_PRESET=<preset id>`. Sleep turns the strip
off; stopping the pumpkin restores the controller's previous state. `WLED_DELAY_SECONDS`
(default `WIZ_DELAY_SECONDS`) lines it up with the speakers. WLED's own brightness and
current limit still apply: WLED reserves about 1 mA per LED, so a 425 mA output limit leaves
only ~135 mA for 290 LEDs and everything looks dim. Set the limit to match the power supply
(this install: 5 V supply rated about 10 A, limit set to 7000 mA). "Receive UDP realtime" must stay enabled in WLED's Sync settings.

The strip stands in front of the porch, so after dark (webcam night mode) it doubles as a white
work light: it comes on about 0.8 s before each camera look (arrival costume judging, the Sorting
Hat's look) and for the whole "stand over there" step of an interactive sorting, then hands back
to the show. `WLED_WORK_LIGHT=always` lights daytime looks too; `off` disables it;
`WORK_LIGHT_LEAD_SECONDS` sets the lead. If the controller reboots, the pumpkin notices within
30 s and sets up the idle effect again.

The host backend uses `gpt-6.1-terra` at low reasoning effort (owner choice 2026-10-31, about 4 s
replies), with `gpt-6-luna` as the hedge; `PUMPKIN_MODEL` / `PUMPKIN_REASONING_EFFORT` override it.

## Special character modes

Say “Hey Pumpkinhead, Trogdor mode”, “Hey Pumpkinhead, Sorting Hat mode”, or
“Hey Pumpkinhead, Dobby mode”. “Pumpkin head” as two words also works.
“Voldemort mode” works on its own. “Hey Pumpkinhead, normal mode” releases the
selected character. Mode, sleep and volume survive restarts independently.

Normal mode mainly uses Patch, Boo and Nibbles, with occasional Sorting Hat and
Dobby guests; the Hat also sometimes judges a costume. Trogdor and Voldemort are
selected explicitly. Plain “trick or treat” and “Boo!” work without a wake phrase.
Special modes keep answering trivia beyond the normal conversation turn limit.

The Sorting Hat performs a pretend sorting on selection and when it joins costume
judging. Say “sort me” or “Hey Pumpkinhead, sort me” for the next visitor. It cycles
through all four houses before repeating, uses brief familiar ceremonial phrases,
and remembers the house for that conversation. House assignments are a game.

Say “Hey Pumpkinhead, do a routine” for a short scene with different voices:
Patch and Boo lose the scare rota to a moth; Dobby reverses Voldemort's welcome mat;
Boo discovers a dragon with two arms still cannot unwrap chocolate; the Hat sorts
a suspiciously brave vacuum cleaner. Normal trick-or-treat also includes original
cast/guest scenes. Fixed character modes keep their voice unless a routine is
explicitly requested. Sleep, volume and mode controls work in the listening gaps.

Controls are heard during listening gaps between lines.

Idle lights breathe in warm orange with a soft flame flicker; sleep turns them off.
Speech keeps its character colors and amplitude animation. Bluetooth playback uses a
quiet preparation signal before words begin, keeping speech animation aligned.
`AUDIO_PREROLL_SECONDS` tunes that interval (0–5 seconds, default 3 for BlueALSA).

The four fan voices use clean, single-speaker reference clips. The current Strong Bad and Dobby starting voices use Qwen 1.7B reference cloning;
the approved Hat and Voldemort voices use Breeze reference cloning.
The original three voices retain their approved references. All speech passes
through measured two-pass loudness matching, gentle compression and a bounded peak limiter; speaker
volume remains separately adjustable. Voldemort's entrance uses green lighting.
See [voice comparison evidence](docs/VOICE_QUALITY.md) for the selection checks.

## Privacy and voice assets

No visitor recordings are retained. One temporary encounter snapshot and short
microphone input pass to the requested authenticated backend; dynamic speech is
RAM-only. Authored lines and stories cache to disk. Explicitly authorized speaker
calibration recordings are retained under ignored host `runtime/calibration`.
No identity or sensitive-attribute inference. Codex turns are ephemeral with
shell, patch, apps, plugins and optional tools disabled. Provider data handling
is governed by the account/service.

`voices.json` records original and fan reference performances, prompts, seeds and
model revisions; reference audio is in `assets/voices`. Breeze source is Apache-2.0; the model/output terms restrict use
to research/noncommercial use. This installation is a personal porch project.

## Development

Host dependencies: `requirements-host.txt`; voice environment:
`requirements-voice.txt` plus pinned Breeze source/model described in `voices.json`.
Pi dependencies include `python3-opencv`, `python3-requests`, `python3-spidev`,
matching HailoRT, `sox`, `ffmpeg`, ALSA, `bluez-alsa-utils` and the BlueALSA plugin.
All host models, build caches and virtual environments live on the fast drive.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
```

The Protect bridge tests need `aiohttp` (`python3 -m unittest tests.test_protect_bridge`).
Fan-character voice clips are not in this repository; see `assets/voices/README.md`.

Read [character bible](docs/CHARACTER_BIBLE.md), [research](docs/RESEARCH.md),
[design](docs/DESIGN.md), [plan](docs/PLAN.md), and [ledger](docs/LEDGER.md).

## Local voice development

Use this computer’s current desktop audio output to compare matched mono clips
without operating the porch speaker:

```sh
cd /mnt/runner-fast/agent-builds/pumpkintalk-20261023
.venv/bin/python audition_local.py dobby
.venv/bin/python audition_local.py dobby-new
.venv/bin/python audition_local.py strongbad
```

Each comparison is under 90 seconds, speaks and prints the clip labels, and preserves the
desktop and Pi volume settings. Ctrl-C stops it. It requires the retained
`runtime/likeness-v4-audition` files, PulseAudio/PipeWire and the active desktop
user’s audio socket. Reference conversion candidates remain previews until chosen.
Speech WAVs are mono; A2DP may transport the same mono voice in two channels.
Stereo-Link searching is a separate physical speaker feature.

Local comparisons stop before playback if Audacity is recording or monitoring,
so test voices do not get mixed into reference captures. `dobby-new` uses the
user-supplied `dobby1.wav` and the retained user-reference preview files.
