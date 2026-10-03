"""Soundtrack for the parcel-sorter video: 16.000 s = 8 bars at exactly 120 BPM.

Reuses the helpers from tools/audio.py (decode, grid measurement, UI sounds).
Usage: python3 sorter/audio.py song.mp3 out/beats.json out/sorter/audio.wav
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import audio as base  # noqa: E402

base.T = 16.0
SR, T = base.SR, base.T
START_BEAT = 112          # first chorus downbeat, 32 beats stay inside the chorus

# (time, sound): every event matches an animation event in sorter/index.html
EVENTS = (
    [(0.0, "pop")]
    + [(2.0 + 0.5 * i, "soft") for i in range(11)]            # a parcel hits the sorter on every beat
    + [(2.0, "pop"), (4.0, "pop"), (5.0, "pop"), (6.0, "click"), (7.5, "release"), (8.0, "pop")]
    + [(8.5 + 0.5 * i, "tick") for i in range(6)]             # six words
    + [(11.5, "release"), (12.0, "pop"), (12.5, "pop"), (13.0, "pop"), (13.5, "pop")]
    + [(14.0, "soft"), (14.5, "soft"), (15.0, "soft"), (15.5, "soft")]
)


def main(song, beats_json, out):
    b = json.load(open(beats_json))
    period, first = b["period"], b["first_beat"]
    s0 = first + START_BEAT * period
    ratio = period / 0.5
    margin = 1.0
    seg = base.ff_decode(["-ss", f"{s0 - margin:.6f}", "-t", f"{32 * period + 2 * margin:.6f}", "-i", song,
                          "-af", f"rubberband=tempo={ratio:.8f}:transients=crisp:detector=percussive"])
    cut = lambda off: seg[int(round((margin / ratio + off) * SR)):][:int(T * SR)]
    music = cut(0.0)
    off = base.grid_offset(music)
    if abs(off) > 0.0015:
        music = cut(off)
    residual = base.grid_offset(music)

    rng = np.random.default_rng(11)
    ui = np.zeros(len(music))
    peaks = []
    for et, name in sorted(EVENTS):
        s = base.sound(name, rng)
        pk = int(np.argmax(np.abs(s)))
        i0 = max(0, int(round(et * SR)) - pk)
        n = min(len(s), len(ui) - i0)
        ui[i0:i0 + n] += s[:n]
        peaks.append((et, name))
    mix = music * 0.62 + (ui * 0.30)[:, None]
    peak = np.abs(mix).max()
    if peak > 0.97:
        mix *= 0.97 / peak
    fi, fo = int(0.01 * SR), int(0.6 * SR)       # short fade in, 0.6 s fade out (not a loop)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]
    mix[-fo:] *= np.linspace(1, 0, fo)[:, None]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-c:a", "pcm_s24le", out], input=mix.astype(np.float32).tobytes(), check=True)
    print(json.dumps(dict(source_start=round(s0, 4), stretch=round(ratio, 6),
                          grid_offset_before_ms=round(off * 1000, 2), grid_offset_after_ms=round(residual * 1000, 2),
                          seconds=len(mix) / SR, events=len(peaks))))


if __name__ == "__main__":
    main(*sys.argv[1:4])
