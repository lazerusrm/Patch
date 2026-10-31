# Main speaker acoustic audit

All seven existing voices tested through Pathfinder Go and recorded using C920. Metrics-only retention; raw recordings discarded. No source or capture clipping was detected. Source peaks measured approximately -6dBFS. ASR is an intelligibility proxy, not a complete perceptual quality score.

Scope: representative clips using the current character definitions. The audit
script imported the staging cache; existing live cached waveforms can differ.
This does not certify every cached utterance byte-for-byte. Cache parity evidence
is in `evidence/audit-cache-parity.json`.

| Character | Source word error | Webcam word error | Webcam vs source |
|---|---:|---:|---:|
| nibbles | 0.0% | 13.3% | 13.3% |
| sorting_hat | 7.7% | 7.7% | 0.0% |
| dobby | 0.0% | 17.6% | 17.6% |
| voldemort | 15.4% | 15.4% | 8.3% |
| trogdor | 0.0% | 12.5% | 12.5% |
| patch | 7.1% | 0.0% | 7.1% |
| boo | 0.0% | 0.0% | 0.0% |

Patch/Boo initial attempts were invalidated by a deployment overlap; both repeated after services stabilized. Boo capture was capped to the ASR twelve-second input limit. Final table uses only valid samples.

Hat and Voldemort opening interjections were absent from source ASR as well, so missing-word flags do not establish onset clipping. All other final samples contained the first and last expected words. No voice profile, main speaker level, or Bluetooth pairing was changed by this audit.

Nibbles uses the revised greeting. Character differences in acting and delivery remain; no attempt was made to flatten every performance into the same voice.
