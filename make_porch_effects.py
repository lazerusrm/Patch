"""Generate three short original mono effects, without external audio assets."""
from array import array
import math
from pathlib import Path
import random
import tempfile
import wave

from loudness import normalize_wav


def make_effects(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rate = 24000
    rng = random.Random(24)
    for name, seconds in (('button-fart', .65), ('small-fanfare', 1.0), ('polite-ding', .8)):
        samples = array('h')
        phase = 0
        for index in range(round(rate * seconds)):
            t = index / rate
            if name == 'button-fart':
                phase += 2 * math.pi * (95 - 45 * t / seconds) / rate
                envelope = min(1, t / .02) * max(0, 1 - t / seconds)
                flutter = .6 + .4 * math.sin(2 * math.pi * 23 * t)
                value = envelope * flutter * (math.tanh(3 * math.sin(phase)) * .7 + rng.uniform(-.12, .12))
            elif name == 'small-fanfare':
                note = min(2, int(t / .28))
                frequency = (392, 523.25, 493.88)[note]
                local = t - note * .28
                envelope = min(1, local / .025) * max(0, 1 - local / .4)
                value = envelope * (math.sin(2 * math.pi * frequency * t)
                                    + .2 * math.sin(4 * math.pi * frequency * t)) * .6
            else:
                envelope = min(1, t / .008) * math.exp(-t * 7)
                value = envelope * (math.sin(2 * math.pi * 880 * t)
                                    + .25 * math.sin(2 * math.pi * 2370 * t)) * .6
            samples.append(round(max(-1, min(1, value)) * 18000))
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            raw = Path(tmp) / 'raw.wav'
            with wave.open(str(raw), 'wb') as wav:
                wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                wav.writeframes(samples.tobytes())
            normalize_wav(raw, directory / (name + '.wav'))


if __name__ == '__main__':
    make_effects(Path(__file__).resolve().parent / 'assets/effects')


def make_trogdor_effects(directory):
    """Doorbell ding-dong and Trogdor's roar, chomps and burp (numpy synthesis + sox)."""
    import subprocess
    import numpy as np
    directory = Path(directory)
    rate = 24000
    rng = np.random.default_rng(31)

    def bell(freq, seconds, t):
        partials = ((1, 1, 1.6), (2.0, .35, 2.6), (2.76, .25, 3.4), (5.4, .12, 6), (8.9, .05, 9))
        return sum(a * np.sin(2 * np.pi * freq * m * t) * np.exp(-d * t) for m, a, d in partials) * np.minimum(1, t / .004)

    def lowpass(x, cutoff):
        a = np.exp(-2 * np.pi * cutoff / rate)
        y = np.empty_like(x)
        acc = 0.0
        for i, v in enumerate(x):
            acc = (1 - a) * v + a * acc
            y[i] = acc
        return y

    def save(name, x, effects=()):
        x = x / max(1e-6, np.max(np.abs(x))) * .85
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            raw = Path(tmp) / 'raw.wav'
            with wave.open(str(raw), 'wb') as wav:
                wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                wav.writeframes((x * 32767).astype('<i2').tobytes())
            if effects:
                done = Path(tmp) / 'fx.wav'
                subprocess.run(['sox', str(raw), '-r', str(rate), '-b', '16', '-c', '1', str(done), *effects,
                                'norm', '-1'], check=True, capture_output=True, timeout=30)
                raw = done
            normalize_wav(raw, directory / (name + '.wav'))

    # Classic two-tone door chime: E5 then C5.
    t = np.arange(int(rate * 2.0)) / rate
    ding = bell(659.25, 2.0, t)
    dong = np.zeros_like(t)
    offset = int(rate * .55)
    dong[offset:] = bell(523.25, 2.0, t[:len(t) - offset])
    save('ding-dong', ding + dong * 1.05)

    # Roar: rough voiced growl, falling pitch, shaped noise, distortion and a big room.
    seconds = 1.9
    t = np.arange(int(rate * seconds)) / rate
    f0 = 150 - 70 * (t / seconds) ** .7 + 6 * np.sin(2 * np.pi * 5.5 * t) + rng.normal(0, 4, t.size).cumsum() / 60
    phase = 2 * np.pi * np.cumsum(f0) / rate
    voiced = sum(np.sin(k * phase) / k for k in range(1, 30))
    rough = 1 + .6 * np.sin(2 * np.pi * 31 * t) * rng.uniform(.6, 1, t.size)
    noise = lowpass(rng.normal(0, 1, t.size), 1800)
    envelope = np.minimum(1, t / .12) * np.clip((seconds - t) / .7, 0, 1) ** 1.3
    roar = np.tanh(2.5 * (voiced * .5 + noise * .9) * rough) * envelope
    save('roar', roar, ('lowpass', '3200', 'overdrive', '8', 'bass', '+6', 'reverb', '55', '50', '80'))

    def chomp_hit(length=.16, weight=1.0):
        n = int(rate * length)
        tt = np.arange(n) / rate
        crunch = rng.normal(0, 1, n) * (rng.uniform(0, 1, n) > .55)
        thump = np.sin(2 * np.pi * (110 - 260 * tt) * tt) * weight
        return (lowpass(crunch, 2600) * .9 + thump) * np.exp(-tt * 22) * np.minimum(1, tt / .003)

    out = np.zeros(int(rate * 1.05))
    for at in (0, .33, .66):
        hit = chomp_hit()
        start = int(rate * at)
        out[start:start + hit.size] += hit
    save('chomp', out, ('bass', '+4',))

    out = np.zeros(int(rate * 1.6))
    for at, weight in ((0, 1.4), (.22, 1.0), (.42, 1.2), (.7, 1.6)):
        hit = chomp_hit(.28, weight)
        start = int(rate * at)
        out[start:start + hit.size] += hit
    tail = rng.normal(0, 1, int(rate * .6)) * (rng.uniform(0, 1, int(rate * .6)) > .9)
    out[int(rate * .95):int(rate * .95) + tail.size] += lowpass(tail, 3000) * np.linspace(.8, 0, tail.size)
    save('big-chomp', out, ('bass', '+5', 'reverb', '20'))

    # Burp: slow irregular low glottal pulses through a throaty formant.
    seconds = .95
    t = np.arange(int(rate * seconds)) / rate
    f0 = 72 - 18 * t / seconds + rng.normal(0, 6, t.size).cumsum() / 90
    phase = 2 * np.pi * np.cumsum(f0) / rate
    pulses = np.maximum(0, np.sin(phase)) ** 6 * rng.uniform(.6, 1.2, t.size)
    envelope = np.minimum(1, t / .04) * np.clip((seconds - t) / .35, 0, 1)
    save('burp', pulses * envelope, ('bandpass', '420', '300h', 'bass', '+8', 'overdrive', '6', 'reverb', '15'))


if __name__ == '__main__':
    make_trogdor_effects(Path(__file__).resolve().parent / 'assets/effects')


def make_spell_effects(directory):
    """Voldemort's spell: a rising zap, then breaking glass (crack, thud and falling tinkles)."""
    import numpy as np
    directory = Path(directory)
    rate = 24000
    rng = np.random.default_rng(13)

    def save(name, x):
        x = x / max(1e-6, np.max(np.abs(x))) * .85
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            raw = Path(tmp) / 'raw.wav'
            with wave.open(str(raw), 'wb') as wav:
                wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                wav.writeframes((x * 32767).astype('<i2').tobytes())
            normalize_wav(raw, directory / (name + '.wav'))

    seconds = .7
    t = np.arange(int(rate * seconds)) / rate
    freq = 300 * (1800 / 300) ** (t / seconds)
    chirp = np.sin(2 * np.pi * np.cumsum(freq) / rate)
    shimmer = np.sin(2 * np.pi * np.cumsum(freq * 1.5) / rate) * .4
    whoosh = np.diff(rng.normal(0, 1, t.size + 1)) * .5
    envelope = np.minimum(1, t / .05) * np.clip((seconds - t) / .12, 0, 1)
    save('spell-zap', (chirp + shimmer + whoosh * (t / seconds)) * envelope)

    seconds = 1.6
    n = int(rate * seconds)
    t = np.arange(n) / rate
    out = np.zeros(n)
    crack = np.diff(rng.normal(0, 1, int(rate * .09) + 1))  # bright, sharp
    out[:crack.size] += crack * np.exp(-np.arange(crack.size) / rate * 45) * 1.6
    thud = np.sin(2 * np.pi * 85 * t[:int(rate * .2)]) * np.exp(-t[:int(rate * .2)] * 25)
    out[:thud.size] += thud * .8
    for _ in range(42):  # shards hitting the ground
        start = int(rate * rng.uniform(.03, 1.25))
        length = int(rate * rng.uniform(.04, .16))
        tt = np.arange(length) / rate
        ping = sum(np.sin(2 * np.pi * rng.uniform(2200, 7500) * tt) for _ in range(3))
        hit = ping * np.exp(-tt * rng.uniform(25, 60)) * rng.uniform(.15, .55) * (1 - start / n)
        out[start:start + length] += hit[:max(0, min(length, n - start))]
    save('glass-break', out)
