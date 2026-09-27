"""Build the 14.000 s soundtrack.

Usage: python3 tools/audio.py song.mp3 out/beats.json out/audio.wav

1. Cut 7 bars from the first chorus (beat 112, a downbeat), with 1 s margins.
2. Time-stretch with rubberband so the measured period becomes exactly 0.5 s
   (118.997 → 120 BPM, +0.84 %). Trim the margin away.
3. Re-measure the beat grid on the result; if the stretcher shifted it, trim
   again by the measured offset.
4. Synthesize UI sounds and place each one so its measured peak (argmax of
   |signal|) lands on its event time.
"""
import json
import subprocess
import sys

import numpy as np
from scipy.signal import butter, sosfilt

SR = 48000
T = 14.0
START_BEAT = 112

# (time, sound) — must match the event times in index.html
EVENTS = [
    (0.5, "click"), (1.5, "tick"), (2.0, "pop"), (2.5, "click"), (3.0, "click"),
    (3.5, "tick"), (4.25, "release"), (5.0, "tick"), (5.5, "max"), (5.75, "release"),
    (6.5, "click"), (7.5, "click"), (8.0, "click"), (9.5, "soft"), (10.0, "soft"),
    (10.5, "click"), (11.0, "key0"), (11.25, "key1"), (11.5, "key2"), (12.0, "click"),
    (12.5, "pop"),
]


def ff_decode(args, ch=2):
    raw = subprocess.run(["ffmpeg", "-v", "error", *args, "-ac", str(ch), "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, ch).copy()


def onset_env(x, hop=128, nfft=2048):
    m = x.mean(1)
    win = np.hanning(nfft)
    n = 1 + (len(m) - nfft) // hop
    idx = np.arange(nfft)[None, :] + hop * np.arange(n)[:, None]
    mag = np.log1p(100 * np.abs(np.fft.rfft(m[idx] * win, axis=1)))
    flux = np.maximum(0, np.diff(mag, axis=0)).sum(1)
    times = (np.arange(1, n) * hop + nfft / 2) / SR
    return times, flux


def grid_offset(x):
    """Best constant shift of a 0.5 s grid against the onset envelope."""
    times, flux = onset_env(x)
    shifts = np.linspace(-0.04, 0.04, 161)
    score = [np.interp(np.arange(0, T - 0.1, 0.5) + s, times, flux).sum() for s in shifts]
    return float(shifts[int(np.argmax(score))])


def bp(x, lo, hi):
    return sosfilt(butter(2, [lo, hi], "bandpass", fs=SR, output="sos"), x)


def sound(name, rng):
    t = np.arange(int(0.12 * SR)) / SR
    noise = rng.standard_normal(len(t))
    if name in ("click", "release"):
        f = 1900 if name == "click" else 1250
        s = bp(noise, 2000, 6500) * np.exp(-t / 0.0035) * 0.7 + np.sin(TAU * f * t) * np.exp(-t / 0.009)
        return s * (1.0 if name == "click" else 0.7)
    if name in ("tick", "max", "soft"):
        f = {"tick": 3300, "max": 4400, "soft": 2600}[name]
        s = np.sin(TAU * f * t) * np.exp(-t / 0.0045) + bp(noise, 5000, 11000) * np.exp(-t / 0.0015) * 0.5
        return s * (0.55 if name == "soft" else 0.75)
    if name == "pop":
        f = 340 + 300 * np.exp(-t / 0.025)
        ph = TAU * np.cumsum(f) / SR
        s = np.sin(ph) * np.minimum(1, t / 0.002) * np.exp(-t / 0.028)
        return s * 1.1
    if name.startswith("key"):
        k = int(name[3])
        s = bp(noise, 1400 + 250 * k, 5200) * np.exp(-t / 0.003) + 0.45 * np.sin(TAU * (190 + 15 * k) * t) * np.exp(-t / 0.012)
        return s * 0.7
    raise ValueError(name)


TAU = 2 * np.pi


def main(song, beats_json, out):
    b = json.load(open(beats_json))
    period, first = b["period"], b["first_beat"]
    s0 = first + START_BEAT * period
    ratio = period / 0.5
    margin = 1.0
    seg = ff_decode(["-ss", f"{s0 - margin:.6f}", "-t", f"{28 * period + 2 * margin:.6f}", "-i", song,
                     "-af", f"rubberband=tempo={ratio:.8f}:transients=crisp:detector=percussive"])
    cut = lambda off: seg[int(round((margin / ratio + off) * SR)):][:int(T * SR)]
    music = cut(0.0)
    off = grid_offset(music)
    if abs(off) > 0.0015:
        music = cut(off)
    residual = grid_offset(music)

    rng = np.random.default_rng(7)
    ui = np.zeros(len(music))
    placed = []
    for et, name in EVENTS:
        s = sound(name, rng)
        pk = int(np.argmax(np.abs(s)))
        i0 = int(round(et * SR)) - pk
        ui[i0:i0 + len(s)] += s[:len(ui) - i0]
        placed.append((et, name, round((i0 + int(np.argmax(np.abs(ui[i0:i0 + len(s)])))) / SR, 5)))
    mix = music * 0.62 + (ui * 0.30)[:, None]
    peak = np.abs(mix).max()
    if peak > 0.97:
        mix *= 0.97 / peak
    fade = int(0.003 * SR)  # 3 ms edge fades so the loop seam never clicks
    mix[:fade] *= np.linspace(0, 1, fade)[:, None]
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-c:a", "pcm_s24le", out], input=mix.astype(np.float32).tobytes(), check=True)
    print(json.dumps(dict(source_start=round(s0, 4), stretch=round(ratio, 6),
                          grid_offset_before_ms=round(off * 1000, 2), grid_offset_after_ms=round(residual * 1000, 2),
                          seconds=len(mix) / SR, ui_peaks=placed), indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:4])
