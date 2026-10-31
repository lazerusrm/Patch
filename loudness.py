"""Shared, measured speech loudness matching using the installed FFmpeg."""
import json
import math
import subprocess

COMPRESS = 'acompressor=threshold=0.08:ratio=2.5:attack=3:release=90'
TARGET = 'loudnorm=I=-20:TP=-6:LRA=9'


def normalize_wav(source, target, boost_db=0):
    if not math.isfinite(boost_db) or not 0 <= boost_db <= 6:
        raise ValueError('Voice boost must be between 0 and 6 dB')
    # loudnorm needs about 3 s of audio; shorter clips silently fall back to its
    # dynamic mode and come out ~20 dB quiet. Pad for the measurement, then trim.
    try:  # ffprobe also reads float and extensible WAV from the cloned voices.
        seconds = float(subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(source)],
            check=True, capture_output=True, text=True, timeout=10).stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        seconds = None
    pad = 'apad=whole_dur=4,' if seconds is not None and seconds < 3.5 else ''
    trim = f',atrim=end={seconds:.4f}' if pad else ''
    # Gentle compression gives peaky creature voices room to reach the same LUFS.
    measured = subprocess.run(
        ['ffmpeg', '-hide_banner', '-nostdin', '-i', str(source), '-af',
         pad + COMPRESS + ',' + TARGET + ':print_format=json', '-f', 'null', '-'],
        check=True, capture_output=True, timeout=30)
    stats, _ = json.JSONDecoder().raw_decode('{' + measured.stderr.decode().rsplit('{', 1)[1])
    fields = {'measured_I': 'input_i', 'measured_TP': 'input_tp',
              'measured_LRA': 'input_lra', 'measured_thresh': 'input_thresh',
              'offset': 'target_offset'}
    if not all(math.isfinite(float(stats[key])) for key in fields.values()):
        raise ValueError('Cannot normalize silent or invalid audio')
    matching = TARGET + ':linear=true' + ''.join(':' + key + '=' + stats[value]
                                               for key, value in fields.items())
    subprocess.run(
        ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source), '-af',
         pad + COMPRESS + ',' + matching + f',volume={boost_db}dB,aresample=24000,aformat=channel_layouts=mono,'
         'alimiter=limit=0.5:level=false' + trim, '-ar', '24000', '-ac', '1',
         '-c:a', 'pcm_s16le', str(target)],
        check=True, capture_output=True, timeout=30)
