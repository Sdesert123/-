# One Shape

A 14-second, 1440×1440, 60 fps UI-motion loop. One element morphs through 12 states on a
120 BPM beat grid: button → loader → check → dynamic island → player (play/pause) → scrub →
volume slider (rubber-band past max) → toggle → liquid tabs → chart (+ tooltip) → ⌘K → toast → button.

## Files

| File | Role |
|---|---|
| `index.html` | The scene. `seek(t)` computes every style from `t` alone. `?t=3.2` shows one moment, `?play&audio=out/audio.wav&debug` plays it live. |
| `tools/analyze.py` | numpy beat grid: spectral-flux onsets → tempo → phase → downbeats → 7-bar windows. |
| `tools/audio.py` | Cuts 7 bars from the chorus, stretches to exactly 120 BPM, re-measures the grid, places synthesized UI sounds by their peaks. |
| `tools/render.mjs` | Playwright renderer: `beats` (one frame per beat), `at <t…>`, `full` (4 subframes/frame → ffmpeg `tmix`). |

## Build

```bash
npm i
python3 -m pip install numpy scipy imageio-ffmpeg   # ffmpeg with libx264 + rubberband
python3 tools/analyze.py song.mp3 > out/beats.json
python3 tools/audio.py song.mp3 out/beats.json out/audio.wav
node tools/render.mjs beats 0.3                     # contact sheet: out/beats_0.3.png
node tools/render.mjs full 4                        # out/video_silent.mp4
ffmpeg -i out/video_silent.mp4 -i out/audio.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 256k -shortest out/one-shape.mp4
```

The song and every rendered file stay in `out/` and are git-ignored. The current soundtrack is a
copyrighted track, so the video is for private use; swap in a royalty-free track at ~120 BPM
before you publish.

## How time works

- **Springs are closed form.** `S(τ)` is the step response of a damped spring (damping 0.8–0.86,
  so overshoot ≤ 1.5 %). A value with many targets is the sum of one step per change.
- **Loop by construction.** `ptrack` sums the steps of the current loop and the previous one, so
  position and velocity at `t = 14` equal those at `t = 0`.
- **Direct manipulation.** `chain` switches between spring phases and drag phases. A drag phase
  reads the cursor. The next spring phase starts from the drag's exact position and velocity.
- **Two-edge indicator.** The toggle knob and tab indicator have separate left and right edges.
  The leading edge uses a fast spring and the trailing edge a slow one, so the pill stretches.
- **Camera.** A log-scale spring zooms each state to fill the frame. The cursor lives in screen
  space but targets world points through the camera. No `will-change`, so text re-rasterizes crisp.
- **Shadow in screen space.** Chrome clips box-shadow blur radii above ~110 px to a rectangle, so
  the shadow is a separate element outside the camera with a capped radius.
