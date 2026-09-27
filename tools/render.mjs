// Renderer.
//   node tools/render.mjs beats [offset]   → out/beats/beat_XX.png + out/beats.png contact sheet
//   node tools/render.mjs at 3.2 5.1 ...   → out/at/t_3.200.png
//   node tools/render.mjs full [workers]   → out/video_silent.mp4 (60 fps, 4 subframes / frame)
//
// Full render: every output frame i is the average of 4 subframes at
// t = (i + (k + 0.5) / 4 - 0.5) / 60, k = 0..3 (360° shutter centred on the
// frame). Subframes stream as PNG into ffmpeg at 240 fps; tmix=frames=4 blends
// each group and select keeps one blended frame out of four.
import { chromium } from 'playwright';
import { spawn, execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const OUT = path.join(ROOT, 'out');
const URL_ = 'file://' + path.join(ROOT, 'index.html');
const SUB = 4, FPS = 60;

async function page(browser) {
  const p = await browser.newPage({ viewport: { width: 1440, height: 1440 }, deviceScaleFactor: 1 });
  await p.goto(URL_);
  await p.evaluate(() => window.ready);
  const cdp = await p.context().newCDPSession(p);
  return { p, cdp };
}
async function shot({ p, cdp }, t) {
  await p.evaluate(t => window.seek(t), t);
  const r = await cdp.send('Page.captureScreenshot', { format: 'png', optimizeForSpeed: true,
    clip: { x: 0, y: 0, width: 1440, height: 1440, scale: 1 } });
  return Buffer.from(r.data, 'base64');
}
const launch = () => chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' }).catch(
  () => chromium.launch());

const [mode = 'beats', ...args] = process.argv.slice(2);
const browser = await launch();

if (mode === 'beats' || mode === 'at') {
  const dir = path.join(OUT, mode);
  rmSync(dir, { recursive: true, force: true }); mkdirSync(dir, { recursive: true });
  const pg = await page(browser);
  const times = mode === 'beats'
    ? Array.from({ length: 28 }, (_, n) => n * 0.5 + parseFloat(args[0] ?? '0.3'))
    : args.map(Number);
  for (const [n, t] of times.entries()) {
    const f = mode === 'beats' ? `beat_${String(n + 1).padStart(2, '0')}.png` : `t_${t.toFixed(3)}.png`;
    writeFileSync(path.join(dir, f), await shot(pg, t));
  }
  if (mode === 'beats') {
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-framerate', '1', '-i', path.join(dir, 'beat_%02d.png'),
      '-vf', 'scale=360:360,tile=4x7:padding=4:color=0xB8B3AB',
      '-frames:v', '1', path.join(OUT, `beats${args[0] ? '_' + args[0] : ''}.png`)]);
  }
} else if (mode === 'full') {
  const workers = parseInt(args[0] ?? String(Math.max(1, os.cpus().length - 1)), 10);
  const frames = Math.round(14 * FPS);
  const chunk = Math.ceil(frames / workers);
  const dir = path.join(OUT, 'chunks');
  rmSync(dir, { recursive: true, force: true }); mkdirSync(dir, { recursive: true });
  const t0 = Date.now();
  await Promise.all(Array.from({ length: workers }, async (_, w) => {
    const a = w * chunk, b = Math.min(frames, a + chunk);
    if (a >= b) return;
    const pg = await page(browser);
    const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', String(FPS * SUB), '-i', '-',
      '-vf', `tmix=frames=${SUB},select='eq(mod(n\\,${SUB})\\,${SUB - 1})',setpts=N/(${FPS}*TB)`,
      '-r', String(FPS), '-c:v', 'libx264rgb', '-crf', '0', '-preset', 'ultrafast',
      path.join(dir, `c${String(w).padStart(2, '0')}.mkv`)], { stdio: ['pipe', 'inherit', 'inherit'] });
    for (let i = a; i < b; i++) {
      for (let k = 0; k < SUB; k++) {
        const t = (i + (k + 0.5) / SUB - 0.5) / FPS;
        const buf = await shot(pg, t);
        if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
      }
      if (w === 0 && (i - a) % 30 === 0) console.log(`worker0 ${i - a}/${b - a}  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    }
    ff.stdin.end();
    await new Promise(r => ff.on('close', r));
  }));
  const list = Array.from({ length: workers }, (_, w) => `file 'c${String(w).padStart(2, '0')}.mkv'`).join('\n');
  writeFileSync(path.join(dir, 'list.txt'), list);
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', path.join(dir, 'list.txt'),
    '-c:v', 'libx264', '-crf', '12', '-preset', 'slow', '-pix_fmt', 'yuv420p', '-r', String(FPS),
    '-movflags', '+faststart', path.join(OUT, 'video_silent.mp4')]);
  console.log(`done in ${((Date.now() - t0) / 1000).toFixed(0)}s`);
}
await browser.close();
