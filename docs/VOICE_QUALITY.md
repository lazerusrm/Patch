# Reference-clone selection, 2026-10-23

Recovered the existing unfinished feature and preserved the three approved original
voices. Public source clips initially contained several speakers; selection now
uses only the intended speaker. `voices.json` records sources, transcripts,
references, model revisions, engine selection and seeds. Runtime downloads and
comparison clips remain in the owned fast-drive checkout.

Compared 22 new clips: two original test lines for each of four characters through
Breeze and Qwen, then two further clips per wizard character using an alternate
reference. Earlier Strong Bad work additionally compared calm/expressive references
with and without direction and both synthesis engines. No visitor recordings were
used in these checks.

Selected Qwen with the expressive Strong Bad reference. Selected Breeze without
extra acting instructions for Sorting Hat, Dobby and Voldemort. Shorter alternate
wizard references produced less consistent timbre or word accuracy. Keep reference
pitch and speaker placement; do not apply the old fallback pitch/reverb effects to
reference clones. Accio is expanded phonetically at synthesis to avoid a soft-c
reading. Qwen is warmed before the voice HTTP endpoint becomes ready.

`evidence/voice-speaker-comparison.json` contains WavLM speaker similarities against
separate source passages and an unrelated Patch negative control. Wizard evaluation
passages are separate from both candidate reference windows. The Strong Bad
comparison uses the previous held-out source passage. These values distinguish
candidates in this setup; they are not percentages or universal quality ratings.

`evidence/voice-intelligibility.json` contains small.en ASR transcripts and word-error
rates for the same authored test lines. Dobby's selected reference was word-perfect
on both lines. Fantasy names and invented words create spelling errors in ASR, so
word-error rates alone do not establish pronunciation or performance quality.
`runtime/voice-quality/manifest.json` records generation timing and clip paths;
`reference-windows.json` records the first/alternate wizard source windows.

A bounded live Pi preview exercises the actual mode parser, persistent controls,
HTTP synthesis, shared -20 LUFS / -6 dBTP processing, Bluetooth output and character
lighting at 50%. User listening feedback remains the acceptance check for likeness,
rasp, accent, timing and outdoor intelligibility. Objective checks do not establish
that the clones are indistinguishable from the source performances.


## Human feedback and larger-model candidates

The owner approved Voldemort's likeness and rejected the likeness of the initial
Dobby and Strong Bad choices, despite their machine scores. Preserve Voldemort's
reference, engine and settings. New comparisons use Qwen3-TTS-12Hz-1.7B-Base at
revision `fd4b254389122332181a7c3db7f27e918eec64e3`, documented in the
[official model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base).
No numeric result substitutes for the owner's selection.

Strong Bad versions 1–4 use calm, expressive, frustrated, and expressive
speaker-vector-only references, respectively. All speak the same new dragon joke;
all four transcribe it exactly. Familiar fantasy catchphrases are less reliable in
ASR. `evidence/strongbad-v2-{intelligibility,speaker}.json` and
`runtime/strongbad-v2/` preserve results, generation settings and candidates.

Dobby A uses the original freedom speech, Dobby B a longer freedom/gratitude
reference. Each supplies the same short familiar phrase and new joke. See
[Dobby refinement](DOBBY_REFINEMENT.md) for ten new candidates and rejection
checks, including pitch drift in some alternatives. The audition clips are
normalized identically before playback, using the shared Bluetooth preparation
signal and 100% digital output. The owner preferred Strong Bad version 2 and Dobby A as starting points, while
requesting further work. Those two now use the larger model in production; the
approved Hat and Voldemort profiles are unchanged. The host engine now supports either
pinned Qwen model, separate per-character clone prompts, and the exact selected
input mode; this avoids substituting the small model for a larger-model audition.


## Playback consistency

The earlier one-pass processing left the eight comparison files between -19.93
and -22.20 LUFS despite nominally identical targets. `loudness.normalize_wav`
now measures each compressed signal and applies a second measured normalization
pass, followed by the same mono 24 kHz conversion and -6 dB peak ceiling. The
matched test set spans 0.6 LU; the regression requires different voice dynamics to
stay within 1 LU. The new cache epoch prevents reuse of the old processing, and
musical clips have been matched from their preserved original assets too.
`evidence/review-loudness-{before,after}.json` contains the measurements.

The owner also reported intermittent cutouts in Dobby and the Hat. No disconnect,
Pi power warning, CPU overload or BlueALSA underrun was observed during the review.
The debug message `PCM dropped: 14` identifies a PCM descriptor/drop operation,
not a count of lost Bluetooth packets (see the
[BlueALSA source](https://github.com/arkq/bluez-alsa/blob/v4.0.0/src/ba-transport.c)).
The Pi uses 2.4 GHz Wi-Fi; an automatically rolled-back 5 GHz trial failed network
authentication. The original network/profile and Bluetooth bond remain intact.
The stutter report remains open pending the matched replay and further evidence;
loudness matching is not proof of reliable wireless delivery.


Routines now join each two-line exchange with a 180 ms reply gap in one audio
stream, with the lighting color following the speaking character. Listening gaps
remain between pairs. The combined cache includes source PCM hashes; temporary
fallback voices stay temporary and are cleaned up on cancellation. All nine scene
pairs rendered successfully. A microphone comparison had inadequate pickup and
was inconclusive about acoustic cutouts (`evidence/routine-acoustic-check.json`).

The official [Pathfinder Go support instructions](https://support.ionaudio.com/en/support/solutions/articles/69000836712-ion-audio-pathfinder-go-how-do-i-link-a-second-speaker-)
identify double-pressing Stereo-Link / Repeat as the way to cancel searching for
a second speaker. The manual associates that search with possible audio dropouts.
The owner has been asked whether its Stereo-Link icon is flashing; this physical
state has not been verified. No factory reset or further Bluetooth restart was
performed.

Dobby tone-conversion candidates and Strong Bad tone variants are comparison
artifacts, not automatically selected production profiles. Human likeness feedback
is still needed. Strong Bad's TTS spelling now uses “consummate V's”: the checked
sample preserved the letter name whereas “Vs” was pronounced as “these”. The
approved Hat and Voldemort reference profiles remain unchanged.
