# Dobby refinement — 2026-10-23

Status: fourth-pass OpenVoice conversions checked and ready; human choice pending. Owner: Astra,
medium effort, requested by the user.
Worktree: `/mnt/runner-fast/agent-builds/pumpkintalk-20261023`, parent-owned `feat/porch`.
Current scope: this report, `runtime/dobby-refinement-v4/`, and
`evidence/dobby-refinement-v4*`. The parent now owns all joke content, application
code, live voice configuration, services, and other characters.

## Fourth pass: convert A's tone color with OpenVoice V2

This pass applies a different model family to the existing Dobby A recordings;
it does not synthesize the text again. The public OpenVoice V2 converter is
131.3 MB. Its converter-only inference path needs the existing torch, librosa,
numpy and soundfile packages, so no additional packages, MeloTTS, language
dictionaries or provider services were installed.

Seven unchanged upstream model/helper files and the MIT license are vendored
under `runtime/dobby-refinement-v4/vendor/`. An isolated virtual environment
reads the existing voice packages without modifying either shared environment.
The minimal runner invokes the official model's reference encoder and
`voice_conversion` directly; the text frontend and optional watermark stack
are not used in this local audition path.

Pinned provenance:

- [OpenVoice source](https://github.com/myshell-ai/OpenVoice/tree/74a1d147b17a8c3092dd5430504bd83ef6c7eb23), revision `74a1d147b17a8c3092dd5430504bd83ef6c7eb23`.
- [OpenVoice V2 checkpoint/model card](https://huggingface.co/myshell-ai/OpenVoiceV2/tree/f36e7edfe1684461a8343844af60babc2efbb727), revision `f36e7edfe1684461a8343844af60babc2efbb727`.
- Code and model are MIT licensed according to the upstream license/model card. Those labels apply to OpenVoice artifacts; the movie reference recordings retain their separate source provenance recorded in earlier sections.

All six conversion WAVs are ready in `runtime/dobby-refinement-v4/`:

| Prefix | Target tone conditioning |
| --- | --- |
| `ov-original-{0,1}.wav` | Full target embedding from the original movie reference |
| `ov-clean-{0,1}.wav` | Full target embedding from the Demucs-cleaned reference |
| `ov-clean60-{0,1}.wav` | Experimental 60% interpolation from A's source embedding toward the cleaned target embedding |

Index 0 is the clothes/free phrase; index 1 is the Bad Dobby / socks joke.
The source embedding is averaged from the two existing A recordings. The
converter's posterior-noise parameter is `tau=0.3`, seed 614. The interpolation
is an experiment in conditioning strength, not an officially calibrated control.
Outputs are 22,050 Hz mono PCM16 WAVs, normalized to peak 0.7. Their durations
are 5.596 and 6.711 seconds, within 10 ms of A, retaining its underlying timing.

Strict checkpoint loading passed. The converter's measured peak GPU allocation
was 388.2 MiB (522.0 MiB reserved), well below its private 3 GiB allocator cap;
conversion ran only when whole-device use was below 24,000 MiB. Generation and
CPU checks finished successfully. Every output is finite and all six recordings
transcribe word for word without hints using independent Whisper.

| Condition | Speaker cosine, phrase / joke | Word errors, phrase / joke |
| --- | --- | --- |
| A control (prior pass) | 0.7991 / 0.8155 | 0 / 0 |
| `ov-original` | 0.7599 / 0.8494 | 0 / 0 |
| `ov-clean` | 0.7960 / 0.8629 | 0 / 0 |
| `ov-clean60` | 0.7738 / 0.8621 | 0 / 0 |

All three are viable listening comparisons. Start with `ov-clean` against A,
then compare `ov-clean60` and `ov-original` if useful. The scores flag no word
failure and show mixed speaker-similarity changes; they do not establish a
human likeness winner. Only two short existing recordings were tested.
Tone conversion can introduce vocoder texture or smooth away useful rasp even
when the words remain exact, so the next meaningful check is the human audition.

The private environment reuses shared packages read-only rather than being
fully self-contained. Tested versions are torch 2.9.1+cu128, numpy 2.5.4,
librosa 1.0.0 and soundfile 0.14.0. Upstream helper files were not modified;
the current torch runtime emits deprecation warnings for weight normalization
and real-valued STFT output, which are future compatibility limits. No runtime
error or checkpoint-key mismatch occurred in this pass.

Reproduction: run `prepare.py`, then `convert.py` with
`runtime/dobby-refinement-v4/.venv/bin/python`, using private runner-fast
temporary/cache paths and nice 19 / ionice class 3. The exact settings are in
`runtime/dobby-refinement-v4/settings.json`; `recommendation.json` maps the
three candidates to the A controls. `evidence/dobby-refinement-v4-provenance.json`
records source URLs, pinned revisions, sizes and hashes, while the matching
`summary`, `asr`, `speaker` and `sha256` JSON files record validation.

No live app, configuration, content, service or audio-device setting changed.
Parent owns all auditions, the existing wake signal and any later integration.
Applying this to future live speech would require a separate conversion stage;
the present deliverable is a reproducible set of local audition WAVs.

## Third pass: clean the preferred reference without changing pitch

The user preferred second-pass A (`q17-freedom`) a little over mixed-reference
B, but said it still needs work. A is the starting point, not an accepted final
voice. Its reference pitch is already reasonably matched; this pass targets
the breathy, strained identity texture rather than another pitch adjustment.

The installed torchaudio Hybrid Demucs separator is applied to the original
stereo performance, with surrounding context, then cropped to the same
57.35–64.35-second reference. Three Qwen 1.7B conditions were compared:
fully separated vocal reference, a 75% vocal / 25% original blend, and the
original acoustic prompt with only its speaker embedding taken from the
separated reference. Generation settings, seed and both test lines match A.
No output pitch shifting or voice effects are added.

The official separator weights are 334.7 MB, downloaded once to the private
runner-fast experiment directory; no dependency install was required.
The quiet interval's RMS fell from 0.00339 to 0.00164, confirming some background
removal. This alone does not demonstrate improved vocal likeness; separation
can also remove useful breath and rasp, which is why the blended and split
prompt conditions are included.

The original/cleaned Qwen speaker-embedding cosine is 0.9805: the cleanup changes
the identity conditioning as well as the audio codes. This does not prove that
the change sounds more like Dobby. The separator is designed for music stems,
so it may also alter speech texture.

Audition the fully cleaned pair against the human-preferred A, using the same
playback normalization and existing wake signal:

| Test | Preferred A control | New clean-reference candidate |
| --- | --- | --- |
| Short clothes/free phrase | `runtime/dobby-refinement-v2/q17-freedom-0.wav` | `runtime/dobby-refinement-v3/q17-clean-0.wav` |
| Novel Bad Dobby / socks joke | `runtime/dobby-refinement-v2/q17-freedom-1.wav` | `runtime/dobby-refinement-v3/q17-clean-1.wav` |

| Condition | Speaker cosine, phrase / joke | Word errors, phrase / joke | Duration, phrase / joke |
| --- | --- | --- | --- |
| A, original reference (prior pass) | 0.7991 / 0.8155 | 0 / 0 | 5.60 / 6.72 s |
| Fully cleaned reference | 0.8458 / 0.7964 | **0 / 0** | 4.96 / 7.52 s |
| 75% clean / 25% original reference | 0.8111 / 0.7778 | 1 / 1 | 5.04 / 6.32 s |
| Original acoustic codes, clean speaker embedding | 0.7908 / 0.8156 | 0 / 2 | 5.92 / 7.52 s |

Both separated/blended source references transcribe exactly. Both final clean
candidate lines also transcribe exactly. The 75% blend adds opening words;
the embedding-only condition drops the “Bad Dobby” opening of the novel joke.
Those two conditions remain archived as fidelity failures. The clean condition
improves the familiar-phrase speaker score and slightly reduces the novel-joke
score; there is no machine-supported claim of uniformly improved identity.
Human perception is still the deciding test.

The clean candidate uses the same pinned Qwen 1.7B model, full ICL conditioning,
seed 614, `non_streaming_mode=True`, generation defaults and output peak 0.7
as A. Its only intended inference change is the reference WAV:
`runtime/dobby-refinement-v3/clean-vocals-reference.wav`. Exact prompt text and
settings are in `runtime/dobby-refinement-v3/profiles.json` and
`recommendation.json`. The split-embedding experiment is implemented explicitly
in `generate.py`; it cannot be reproduced by changing a single reference path.

Evidence is in `evidence/dobby-refinement-v3-{reference-cleanup,summary,speaker,asr,sha256}.json`.
All generation and evaluation processes exited successfully; no content, app,
configuration, playback or service changes were made. The private separator
weights are retained at `runtime/dobby-refinement-v3/torch/hub/torchaudio/models/hdemucs_high_trained.pt`
for reuse without another download.

If the cleaned reference does not improve the next human audition, stop this
Qwen reference-tuning branch. The next useful comparison is a different cloning
model family against the same A control, using the original and cleaned
reference; the parent owns that research and any larger downloads. More small
pitch, guidance or seed changes are not supported by the feedback so far.

## Second pass: identity takes priority

The user rejected the first-pass Dobby voice as insufficiently like Dobby.
Its similarity score therefore does not justify accepting it. The first-pass
results below remain an experiment record, not the current recommendation.

The second pass uses the larger `Qwen/Qwen3-TTS-12Hz-1.7B-Base`, revision
`fd4b254389122332181a7c3db7f27e918eec64e3`, with full reference conditioning,
`non_streaming_mode=True`, seed 614, bfloat16 and SDPA. It compares the old
freedom clip, the more conversational gratitude clip, and an 11.10-second
continuous Dobby-only clip from his first meeting with Harry. The new clip
is aligned to seconds 113.02–124.12 of the official Harry Potter channel's
video `7bOB770FcF4`. Its exact reference transcript stays in local runtime
metadata. No pitch shifting or output voice effects are used.

Ten recordings are ready in `runtime/dobby-refinement-v2/`. Index 0 uses the
short clothes/free phrase; index 1 uses an original Bad Dobby / both-socks
joke. Nine transcribe exactly; one variant adds an extra opening “Dobby.”
All files are finite mono PCM16 WAVs at 24 kHz, peak-normalized to 0.7.

Start the human audition with these two pairs:

| Option | Familiar phrase | Novel joke | Reference |
| --- | --- | --- | --- |
| Larger model, original reference | `q17-freedom-0.wav` | `q17-freedom-1.wav` | Existing 7-second freedom clip |
| Larger model, longer reference | `q17-mixed-0.wav` | `q17-mixed-1.wav` | Existing freedom + gratitude composite |

Both pairs have exact independent transcriptions. The longer reference gives
a distinct pitch distribution on the novel joke. No candidate has yet been
accepted by the user; these are alternatives for listening, not a claim that
the likeness problem has been solved.

Other available contrasts are `q17-gratitude-{0,1}.wav`,
`q17-bedroom-{0,1}.wav`, and `q17-freedom-stream-{0,1}.wav`. The last pair uses
Qwen's default simulated-stream text input (`non_streaming_mode=False`);
it is not a different output streaming implementation. Its novel joke has
the extra opening word. The bedroom and gratitude novel lines have diagnostic
concerns described below, so they are not the first audition choices.

| Profile | Speaker cosine, phrase / joke | Word errors, phrase / joke | Median pitch Hz, phrase / joke |
| --- | --- | --- | --- |
| `q17-freedom` | 0.7991 / 0.8155 | 0 / 0 | 312.5 / 243.8 |
| `q17-mixed` | 0.7870 / 0.7750 | 0 / 0 | 288.2 / 272.0 |
| `q17-freedom-stream` | 0.8138 / 0.8256 | 0 / 1 | 307.1 / 218.4 |
| `q17-gratitude` | 0.7977 / 0.7237 | 0 / 0 | 221.0 / 166.5 |
| `q17-bedroom` | 0.8298 / 0.5697 | 0 / 0 | 226.1 / 222.2 |

The same held-out Dobby evaluation clip and Patch negative control (0.5268)
are used for WavLM checks. In particular, the bedroom joke's 0.5697 warns of
possible speaker drift even though its words are clear. The gratitude joke's
estimated pitch is substantially below its reference. These checks flag
problems; they cannot choose the voice that a human recognizes as Dobby.

Pitch is estimated with pYIN at 16 kHz, 70–650 Hz search, keeping voiced frames
with probability at least 0.5. Source medians are 324.4 Hz (freedom), 298.4 Hz
(gratitude) and 221.0 Hz (bedroom). The rejected Breeze clothes/price-tag
sample measures 396.0 Hz; Qwen's original-reference familiar phrase measures
312.5 Hz. The recordings contain different words, and breathiness/music can
confuse pitch estimation. The bedroom source has only 28 confident frames,
so its pitch summary is especially weak evidence. No signal was pitch-shifted.

The new continuous source is [the official Harry Potter Dobby compilation](https://www.youtube.com/watch?v=7bOB770FcF4).
Local word timestamps align the selected 113.02–124.12-second window exactly
with the corresponding first-meeting upload. Source dialogue transcripts and
the exact clone prompt text remain in local runtime JSON, not this report.

Reproduction and integration:

- `runtime/dobby-refinement-v2/profiles.json` stores exact references and prompt transcripts.
- `model-settings.json` stores the pinned snapshot and resolved generation defaults; `recommendation.json` includes per-profile overrides and audition notes.
- `generate_qwen.py` accepts profile names and resumes existing samples. It uses full ICL reference conditioning, no instruction and no pitch/resonance effects.
- `evidence/dobby-refinement-v2-{summary,speaker,asr,acoustics}.json` stores checks; `evidence/dobby-refinement-v2-sha256.json` stores sample and profile hashes.
- Historical second-pass limitation: the server then hardcoded Qwen 0.6B. It now supports pinned per-profile 0.6B/1.7B models, and production Dobby A uses 1.7B. Keep the original observations below as an experiment record.

Every generation, source-analysis and evaluation process finished successfully.
GPU use returned to the existing daemon's approximately 14.9 GiB. No app,
content, voice configuration, Bluetooth, service or Voldemort setting changed
in this pass. Parent owns playback, the existing audio wake signal and any
deployment. The larger model cache was downloaded once by the parent and reused.

## First pass archive

The initial machine-based recommendation was to keep the Breeze profile. It produced the best average and worst
speaker similarity across three new lines, with every word transcribed correctly.
The directed variants and longer references did not establish an improvement.
The gentlest directed variant is available for a human comparison of expression.

Ten short jokes have been added as `dobby-joke-5` through `dobby-joke-14`.
They use harmless mishaps, mismatched socks, clothing and freedom; the requested
short catchphrases appear with new comic continuations. Examples:

- “Bad Dobby! Dobby put the sweets in the socks again. Now the candy has a dress code.”
- “Master has given Dobby clothes. Dobby is free! Unfortunately, the shirt still has a price tag.”
- “Dobby is a free elf! Dobby answers to nobody. Except the microwave. That one beeps.”
- “One sock means freedom. Two socks means laundry. Dobby did not read the small print.”

## Voice comparison

Six profiles each rendered the first three examples above, using seed 614 and
the production `VoiceEngine.render` path in an isolated process. The live daemon,
Bluetooth volume and services were not changed. New caches and temporary files
were confined to runner-fast; generation ran at nice 19 / ionice class 3.

| Profile | Mean speaker cosine | Minimum cosine | Word errors / 48 | Mean duration |
| --- | ---: | ---: | ---: | ---: |
| Current reference, no instruction, CFG 1 | **0.8813** | **0.8739** | **0** | 7.39 s |
| Current reference, direction, CFG 1 | 0.8676 | 0.8541 | **0** | 9.12 s |
| Current reference, direction, CFG 2 | 0.8599 | 0.8021 | 2 | 9.52 s |
| Current reference, direction, CFG 4 | 0.8572 | 0.8525 | 1 | 8.45 s |
| Sock + freedom reference, CFG 1 | 0.8497 | 0.7999 | 2 | 8.03 s |
| Freedom + gratitude reference, CFG 1 | 0.8379 | 0.8161 | 2 | 8.19 s |

Speaker similarity uses `microsoft/wavlm-base-plus-sv` against the separate
`runtime/wizard-references/dobby-evaluation.wav` (source seconds 81.25–85.45).
That recording was never used in a generation prompt. The existing Patch voice
has cosine 0.5268 against this evaluation recording. Transcriptions use the
independent `small.en` Whisper model on CPU, beam size 5, with no text hint.
Word errors ignore punctuation and case, and retain spelling/name errors.
For example, directed CFG 2 produced two “Dopey” transcriptions; directed CFG 4
added “The” before “Master.” All 18 WAVs are finite mono audio, peak 0.7, and
within the production duration limit.

These are machine measures, not listening judgments. Three lines at one seed
cannot establish general perceptual equivalence or whether breathiness and
comic timing sound preferable. The directed CFG 1 samples are consistently
longer despite the instruction requesting quick phrases; audition them before
considering that delivery a benefit. A single high score from the longer sock
reference (0.9103 on the clothes line) does not justify its less consistent
overall result.

## Recommended profile and audition files

Retain these existing settings; no configuration integration is necessary:

```json
{
  "engine": "breeze",
  "reference": "assets/voices/dobby.wav",
  "text": "Master has presented Dobby with clothes. Dobby is free.",
  "instruct": "",
  "seed": 614,
  "cfg": 1
}
```

The existing source is `https://www.youtube.com/watch?v=8DTb-lseCdQ`; the
recommended reference uses seconds 57.35–64.35. Longer reference candidates
combine 51.15–54.92 + 57.35–64.35, or 57.35–64.35 + 116.70–121.90, with
10 ms fades and a 180 ms join pause. Their exact transcripts are in
`runtime/dobby-refinement/profiles.json`.

| Line | Recommended recording | Optional directed comparison |
| --- | --- | --- |
| Bad Dobby / candy dress code | `runtime/dobby-refinement/baseline-0.wav` | `runtime/dobby-refinement/directed-1-0.wav` |
| Clothes / free / price tag | `runtime/dobby-refinement/baseline-1.wav` | `runtime/dobby-refinement/directed-1-1.wav` |
| Free elf / microwave | `runtime/dobby-refinement/baseline-2.wav` | `runtime/dobby-refinement/directed-1-2.wav` |

The optional direction, with the original reference and CFG 1, is:

> Keep the reference voice. Speak with its light, breathy rasp and rounded British vowels. Be delighted and a little flustered, with quick excited phrases and brief pauses before the punchlines.

The installed Breeze clone-only template rejects CFG values other than 1
without an instruction, so no invalid no-instruction CFG comparison was run.

## Validation and reproduction

The full `Library('entertainment.json')` accepts the changes. There are 14
unique Dobby jokes, with 10 additions of at most 19 words each; a full Dobby
draw cycle has no repeats. `python -m unittest tests.test_entertainment` passes.
Only Dobby joke entries were changed in `wizarding.json`; facts, stories and
other personas are preserved.

Generation and evaluation scripts are in `runtime/dobby-refinement/`.
Run `generate.py` and `evaluate.py speaker` with `.venv-voice/bin/python`,
and `evaluate.py asr` with `.venv/bin/python`, under nice 19 / ionice class 3.
The generator resumes existing sample files. Models are read from the existing
local cache in offline mode. No dependencies were added.

Evidence:

- `evidence/dobby-refinement-summary.json`: aggregate comparison.
- `evidence/dobby-refinement-speaker.json` and `evidence/dobby-refinement-asr.json`: per-recording scores and full transcriptions.
- `evidence/dobby-refinement-validation.txt`: library validation.
- `evidence/dobby-refinement-sha256.json`: content, reference and sample hashes.
- `runtime/dobby-refinement/recommendation.json`: profile and audition handoff.

All generation/evaluation processes completed. Samples, scripts and private
compilation caches remain together in `runtime/dobby-refinement/` for replay.
Parent owns deployment and any human audition.
