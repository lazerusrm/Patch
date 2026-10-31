"""Comic chime (CC0, self-generated): short fart, brief pause, then a clear pleasant ding.
Built from tools/make_sfx.py outputs. Usage: python3 tools/make_comic_chime.py [assets/protect_sfx]"""
import numpy as np, wave, os, subprocess, sys
d = sys.argv[1] if len(sys.argv) > 1 else "assets/protect_sfx"; R = 24000
def rd(n):
    with wave.open(f"{d}/{n}.wav") as w:
        assert w.getframerate() == R and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float) / 32767
fart, ding = rd("fart_short"), rd("ding")
fart = fart / np.max(np.abs(fart)) * 0.55          # comedy slightly under the ding
ding = ding / np.max(np.abs(ding)) * 0.85          # household notice stays the loudest, clearest part
x = np.concatenate([np.zeros(int(.03 * R)), fart, np.zeros(int(.15 * R)), ding, np.zeros(int(.05 * R))])
p = f"{d}/fart_ding.wav"
with wave.open(p, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(R); w.writeframes((x * 32767).astype("<i2").tobytes())
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", p, "-c:a", "libmp3lame", "-b:a", "128k", f"{d}/fart_ding.mp3"], check=True)
print(p, round(len(x) / R, 2), "s")
