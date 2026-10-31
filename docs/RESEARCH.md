# Research and measured choices — 2026-10-23

## Speech research and final selection

- [Pocket TTS](https://github.com/kyutai-labs/pocket-tts): CPU-based, local voices,
  streaming HTTP. New October 20 small English models are useful for the Pi.
  Selected `english_18m_refl_2026-10`; Rust binary from release `v4.0.1`, packaged
  binary `3.3.0`. ARM64 archive SHA256:
  `2b9a727bffd86ea6d73370d675cbd91a7db118f11b7f5a60343c2d5da12b187a`.
  Pi measured 4.4 seconds of generated speech in 1.014 seconds, excluding cold
  model downloads. Retained only as a local fallback: user rejected preset voices
  as too generic for the intended characters.
- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper): `small.en`, CPU INT8,
  four threads on the host; voice-activity filtering and no previous-text carryover.
  Version 1.2.1 requires a compatible PyAV; pin 16.0.1 because 19.0.2 rejects its
  `metadata_errors` argument. A real WAV decoding regression covers that boundary.
- [Chatterbox Nano/Turbo](https://github.com/resemble-ai/chatterbox): alternatives
  for expressive voice cloning and laughter tags; Nano is 110M, Turbo 350M. Not
  installed or benchmarked here.
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS): voice design and cloning,
  0.6B/1.7B. Installed and auditioned original VoiceDesign references and cloned
  speech. Improved on presets but superseded by the accepted Breeze performances.
- [Fish Speech](https://github.com/fishaudio/fish-speech): Drama 3 is a larger
  expressive model; not selected for this small porch runtime.

## Vision and dialogue

- [Hailo Model Zoo YOLOv8s](https://github.com/hailo-ai/hailo_model_zoo/blob/v2.13/hailo_model_zoo/cfg/networks/yolov8s.yaml)
  with official Hailo-8 v2.13 compiled HEF. Existing driver4.19 was preserved;
  runtime, Python bindings and firmware were aligned down from4.20 to4.19.
  Live C920 frame 640x480: one person detected, inference18.9ms. This is a single
  real-frame measurement, not a sustained benchmark or porch coverage guarantee.
- [Codex authentication](https://developers.openai.com/codex/auth/),
  [non-interactive mode](https://developers.openai.com/codex/noninteractive/), and
  [SDK/app-server guidance](https://developers.openai.com/codex/sdk/) establish
  supported account-backed integration and headless login. Existing host account
  was used; no account tokens copied to Pi. Runtime CLI0.163.0 supports isolated
  config, ephemeral turns, image attachments and final-output files.
- GPT-6.1 Sol produced a live snapshot-based character reply in4.98s. A synthetic
  audio-to-transcription-to-Sol test took6.02s. An injection asking for shell use
  and credentials received a character refusal; this is one behavioral test,
  not a comprehensive security certification.

## Final character engine and Bluetooth

Breeze TTS 2 is the selected host voice engine. Model and inference source are
pinned in `voices.json`; original reference performances are versioned in
`assets/voices`. The user described its Patch audition as a step change better,
then requested equivalent character effort for Boo and Nibbles. Astra contributed
persona direction, scripts, and spectrogram/metric analysis; it did not directly
hear the clips. C920 acoustic capture recovered speech substantially better than
the second USB mic, so C920 is the current input at gain 5/15.

RTX5090 fast inference measured 3.12–3.15s for 7.36s of speech after warmup,
compared with about 9.5s eager. The server primes its CUDA graphs before opening
the HTTP listener; cold startup can take around a minute. Voice design uses
natural-language acting directions and original references, not an impersonation.
Breeze documents nonverbal events including laugh, sigh and throat clearing;
untested claims about arbitrary tags or IndexTTS versions are not dependencies.
Model/output terms are research/noncommercial; personal porch installation.

Pathfinder Go is the commissioned A2DP speaker at 70%; BlueALSA handles 24k mono
to 48k stereo. Its trusted classic Bluetooth bond and 10-second reconnect timer
are persistent. The BLE companion is not an audio endpoint. Live speech is
loudness matched at a -20 LUFS target and limited to 0.5 sample peak after
resampling. A synthetic regression with different dynamics reduced a 13 LUFS gap
to under 3 LUFS; that is a signal check, not final outdoor intelligibility proof.

## Remaining physical acceptance

The user confirmed sleep/wake, volume-down, trick-or-treat and ten-LED pulse tests.
The deployed camera/Hailo/VLM path was tested outdoors after enclosure placement;
Crowsnest was disabled to release the webcam. Actual dusk/night costumes,
background noise, Bluetooth reconnect after another physical power cycle, and
acoustic Bluetooth-to-LED delay calibration remain. Latest Pi checks show no
undervoltage. No unsupported claim about BlueALSA Delay units is used in code.
