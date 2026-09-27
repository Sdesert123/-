"""Beat-grid analysis with numpy only.

Usage: python3 tools/analyze.py song.mp3 > out/beats.json

1. Decode to mono 22.05 kHz.
2. Onset envelope = half-wave rectified log-spectral flux.
3. Tempo: autocorrelation of the envelope, then a fine grid search of
   (period, phase) that maximises onset energy on a rigid grid over the
   whole song (the track is programmed, so the tempo is constant).
4. Bar phase: section boundaries (large jumps in per-beat loudness) land on
   downbeats; their beat index mod 4 votes for the bar phase.
5. Candidate 7-bar windows are scored by loudness and steadiness.
"""
import json
import subprocess
import sys

import numpy as np

SR = 22050
HOP = 128
NFFT = 2048


def decode(path):
    raw = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-i", path, "-ac", "1", "-ar", str(SR),
         "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def stft_mag(x):
    win = np.hanning(NFFT).astype(np.float32)
    n = 1 + (len(x) - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    out = np.empty((n, NFFT // 2 + 1), np.float32)
    for s in range(0, n, 4096):  # chunked to keep memory flat
        out[s:s + 4096] = np.abs(np.fft.rfft(x[idx[s:s + 4096]] * win, axis=1))
    return out


def main(path):
    x = decode(path)
    mag = stft_mag(x)
    logm = np.log1p(100 * mag)
    flux = np.maximum(0, np.diff(logm, axis=0)).sum(1)
    flux = np.concatenate([[0], flux])
    flux -= np.convolve(flux, np.ones(64) / 64, "same")  # remove slow trend
    flux = np.maximum(flux, 0)
    fps = SR / HOP
    times = (np.arange(len(flux)) * HOP + NFFT / 2) / SR

    # coarse tempo from autocorrelation (100..140 BPM)
    f = flux - flux.mean()
    ac = np.fft.irfft(np.abs(np.fft.rfft(f, 2 * len(f))) ** 2)[:len(f)]
    lags = np.arange(len(ac))
    bpm_of = 60 * fps / np.maximum(lags, 1)
    m = (bpm_of > 100) & (bpm_of < 140)
    lag = lags[m][np.argmax(ac[m])]
    coarse = 60 * fps / lag

    # fine grid search: period and phase maximising envelope on the grid
    def score(period, phase):
        bt = np.arange(phase, times[-1], period)
        return np.interp(bt, times, flux).sum()

    best = (0, None, None)
    for period in np.linspace(60 / coarse - 0.004, 60 / coarse + 0.004, 161):
        for phase in np.linspace(0, period, 200, endpoint=False):
            s = score(period, phase)
            if s > best[0]:
                best = (s, period, phase)
    _, period, phase = best
    # local refinement
    for _ in range(3):
        cand = [(score(p, ph), p, ph)
                for p in np.linspace(period - 2e-5, period + 2e-5, 21)
                for ph in np.linspace(phase - 0.004, phase + 0.004, 41)]
        _, period, phase = max(cand)

    beats = np.arange(phase, times[-1] - period, period)
    # per-beat loudness (RMS over the beat) and low band (kick) energy
    rms = np.array([np.sqrt(np.mean(x[int(b * SR):int((b + period) * SR)] ** 2))
                    for b in beats])
    db = 20 * np.log10(rms + 1e-9)
    jump = np.concatenate([[0], np.diff(db)])
    top = np.argsort(jump)[-12:]
    votes = np.bincount(top % 4, minlength=4)
    bar_phase = int(np.argmax(votes))

    # how tight is the grid? offset of the strongest onset near each beat
    offs = []
    for b in beats[::4]:
        w = (times > b - 0.05) & (times < b + 0.05)
        if flux[w].max() > np.percentile(flux, 90):
            offs.append(times[w][np.argmax(flux[w])] - b)
    offs = np.array(offs)

    # 7-bar windows starting on a downbeat
    cands = []
    for i in range(bar_phase, len(beats) - 28, 4):
        seg = db[i:i + 28]
        cands.append(dict(beat=i, t=round(float(beats[i]), 4),
                          mean_db=round(float(seg.mean()), 2),
                          spread_db=round(float(seg.std()), 2),
                          entry_jump=round(float(jump[i]), 2)))
    cands.sort(key=lambda c: -(c["mean_db"] - c["spread_db"]))

    print(json.dumps(dict(
        bpm=round(60 / period, 4), period=period, first_beat=phase,
        bar_phase=bar_phase, bar_votes=votes.tolist(),
        grid_offset_ms=dict(median=round(1000 * float(np.median(offs)), 2),
                            p90_abs=round(1000 * float(np.percentile(np.abs(offs), 90)), 2)),
        section_starts=[round(float(beats[i]), 3) for i in sorted(top)],
        best_windows=cands[:8],
        beat_db=[round(float(v), 1) for v in db],
    ), indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
