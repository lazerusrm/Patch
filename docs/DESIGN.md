# Porch design

Pi 5 at 192.168.0.49 owns the C920 camera/mic, Hailo-8 person detection, stable
presence/departure debounce, encounter character, half-duplex listening, BlueALSA
Pathfinder Go output and ten WS2812B LEDs. The host at 192.168.0.73 provides
Faster Whisper small.en CPU INT8, ephemeral Sol image/text replies and Breeze
TTS 2 original character performances on RTX5090. Two authenticated loopback
HTTP services cross a reverse SSH tunnel; account credentials stay on the host.

Patch is a pompous ancient pumpkin reduced to porch furniture. Boo is a theatrical
ghost with opening-night nerves. Nibbles is a scruffy, self-appointed candy
inspector. All interactions are family-friendly, cheeky and optional; visitors
keep their candy. No threats, identity inference or sensitive-attribute guesses.
Sol may describe visible costume details and uses generic welcomes when uncertain.

An encounter starts after stable presence; eight seconds without a person rearms
the next group. Generation checks invalidate stale rendered speech and preserve
pending new arrivals. One character stays for the encounter. After three dialogue
turns or silence, explicit keywords continue interaction. Idle and sleep listening
also accept operator commands. Camera arrival cancels idle capture promptly.

Bluetooth output defaults to 100% and persists in the 50–100% range; the owner
controls physical speaker volume. The USB output retains its 50–90% range. Sleep persists and silences
speech/lights while retaining wake listening. Authored speech caches locally;
dynamic dialogue stays in RAM. TTS fallback is local Pocket TTS. Perceived audio
loudness is matched with bounded peaks; Bluetooth LED latency remains uncalibrated.
Ten LEDs use GPIO10/SPI0 at a maximum 15% brightness.

A bounded audition service temporarily replaces normal encounters with rotating
samples and six-second listening gaps; a child process checks camera/Hailo without
saving images. An absolute deadline and systemd runtime cap prevent endless
playback. Exiting automatically resumes normal porch mode.

Only visitor snapshots needed for an encounter are temporarily sent to the
backend. No visitor video/audio is saved. Explicit calibration clips are separate.
Only public SSH keys are installed. Crowsnest camera autostart was disabled to
resolve webcam ownership; other printer services are preserved.
