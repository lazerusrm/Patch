"""Self-generated (CC0) comic SFX for PumpkinTalk. Writes 24k mono PCM16 WAV + MP3."""
import numpy as np, wave, os, subprocess, sys
R = 24000; out = sys.argv[1] if len(sys.argv) > 1 else "assets/protect_sfx"; os.makedirs(out, exist_ok=True)
rng = np.random.default_rng(31)
def env(n, a=0.01, r=0.1):
    e = np.ones(n); ai, ri = int(a*R), int(r*R); e[:ai] = np.linspace(0,1,ai); e[-ri:] = np.linspace(1,0,ri); return e
def save(name, x, peak=0.95):
    x = x / (np.max(np.abs(x)) + 1e-9) * peak
    p = f"{out}/{name}.wav"
    with wave.open(p, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(R); w.writeframes((x*32767).astype("<i2").tobytes())
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",p,"-c:a","libmp3lame","-b:a","96k",f"{out}/{name}.mp3"], check=True)
def fart(d=0.9):
    n = int(d*R); t = np.arange(n)/R
    f = 95 - 35*t/d + 12*np.sin(2*np.pi*7*t) + rng.normal(0, 4, n).cumsum()/np.sqrt(np.arange(1,n+1))
    ph = 2*np.pi*np.cumsum(f)/R
    x = np.sign(np.sin(ph))*0.6 + 0.4*np.sin(2*ph) + 0.25*rng.normal(0,1,n)
    am = 0.6 + 0.4*np.sign(np.sin(2*np.pi*(18 + 6*t)*t))
    x = np.convolve(x*am, np.ones(12)/12, "same")
    return x*env(n, .02, .25)
def tone(f, d, harm=(1,.5,.3), vib=0):
    n=int(d*R); t=np.arange(n)/R; ph=2*np.pi*f*t + vib*np.sin(2*np.pi*5*t)
    return sum(a*np.sin((i+1)*ph) for i,a in enumerate(harm))*env(n,.02,.08)
def sad_trombone():
    return np.concatenate([tone(f,d,(1,.7,.5,.3),vib=v) for f,d,v in ((311,.35,0),(294,.35,0),(277,.35,0),(262,1.1,1.2))])
def ding():
    n=int(1.2*R); t=np.arange(n)/R
    return (np.sin(2*np.pi*1046*t)+.5*np.sin(2*np.pi*2093*t)+.25*np.sin(2*np.pi*3135*t))*np.exp(-3.5*t)
def fanfare():
    return np.concatenate([tone(f,d,(1,.6,.4,.3,.2)) for f,d in ((523,.15),(659,.15),(784,.15),(1046,.55))])
for k,v in {"fart_short":fart(),"fart_tiny":fart(.45),"sad_trombone":sad_trombone(),"ding":ding(),"fanfare":fanfare()}.items():
    save(k, v)
print(sorted(os.listdir(out)))
