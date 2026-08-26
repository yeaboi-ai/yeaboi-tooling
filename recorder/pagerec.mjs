/**
 * Capture a scripted browser or Electron session as timestamped frames.
 * Reads one JSON spec on argv, writes JPEG frames plus an ffmpeg concat file
 * into a directory, and prints a summary as JSON on stdout. Assembling the GIF
 * is ffmpeg's job, in record.py — this file only produces pixels and timings.
 *
 * Frames come from CDP's Page.startScreencast, not a `page.screenshot()` loop.
 * A screenshot of a full-size page costs well over a frame interval, so a loop
 * either blocks or drops frames; dropping them silently rescales the whole
 * timeline, and a 15-second take plays back in three. The screencast is
 * push-based and carries a real timestamp per frame, so the concat file below
 * reproduces the original wall-clock timing exactly.
 *
 * Electron specifically: the desktop renderer throws `preload bridge missing`
 * when `window.yeaboi` is absent, so it cannot be captured by pointing a
 * browser at the dev server. `_electron.launch()` drives the real app and
 * hands back an ordinary Page, which everything below then treats like any
 * other.
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const spec = JSON.parse(process.argv[2]);
const outDir = process.argv[3];

mkdirSync(outDir, { recursive: true });

const frames = []; // { name, t } — t is seconds since the first frame

async function startScreencast(page) {
  const cdp = await page.context().newCDPSession(page);
  let n = 0;
  let t0 = null;
  cdp.on('Page.screencastFrame', async ({ data, metadata, sessionId }) => {
    const t = metadata.timestamp;
    if (t0 === null) t0 = t;
    const name = `f${String(n++).padStart(5, '0')}.jpg`;
    writeFileSync(join(outDir, name), Buffer.from(data, 'base64'));
    frames.push({ name, t: t - t0 });
    // Acking is what asks for the next frame; without it the stream stalls
    // after the first few. A frame that arrives after teardown will throw.
    try {
      await cdp.send('Page.screencastFrameAck', { sessionId });
    } catch {
      /* screencast already stopped */
    }
  });
  await cdp.send('Page.startScreencast', {
    format: 'jpeg',
    quality: spec.quality ?? 90,
    maxWidth: spec.width,
    maxHeight: spec.height,
    everyNthFrame: 1,
  });
  return cdp;
}

async function runSteps(page, steps) {
  for (const step of steps) {
    const [kind, ...rest] = step;
    switch (kind) {
      case 'goto':
        await page.goto(rest[0], { waitUntil: 'load' });
        break;
      case 'hash':
        // Hash routing: assigning location.hash never reloads the document,
        // which is what keeps the Electron window's state across steps.
        await page.evaluate((h) => {
          window.location.hash = h;
        }, rest[0]);
        break;
      case 'await':
        await page.waitForSelector(rest[0], { timeout: (rest[1] ?? 15) * 1000, state: 'visible' });
        break;
      case 'click':
        await page.click(rest[0], { timeout: (rest[1] ?? 15) * 1000 });
        break;
      case 'type':
        // pressSequentially, not fill: a value that appears all at once reads
        // as a glitch, and any UI that reacts per keystroke would never show it.
        await page.click(rest[0]);
        await page.locator(rest[0]).pressSequentially(rest[1], { delay: 1000 / (rest[2] ?? 18) });
        break;
      case 'press':
        await page.keyboard.press(rest[0]);
        break;
      case 'scroll':
        // Smooth-scroll in steps so the screencast has motion to send; a single
        // jump emits one frame and reads as a discontinuous cut.
        await page.evaluate(async (px) => {
          const stepPx = px < 0 ? -18 : 18;
          for (let done = 0; Math.abs(done) < Math.abs(px); done += stepPx) {
            window.scrollBy(0, stepPx);
            await new Promise((r) => setTimeout(r, 16));
          }
        }, rest[0]);
        break;
      case 'pause':
        await page.waitForTimeout(rest[0] * 1000);
        break;
      default:
        throw new Error(`unknown step: ${JSON.stringify(step)}`);
    }
  }
}

let close = async () => {};
let page;

if (spec.electron) {
  const { _electron } = await import('playwright');
  // executablePath is required: Playwright resolves Electron from its own
  // node_modules by default, and the recorder deliberately does not carry a
  // ~100MB binary that the desktop repo already has.
  const app = await _electron.launch({
    executablePath: spec.electron.executable,
    args: spec.electron.args,
    cwd: spec.electron.cwd,
    env: { ...process.env, ...(spec.electron.env ?? {}) },
  });
  page = await app.firstWindow();
  // The shell shows a splash until the Python sidecar's YEABOI_APP_READY
  // handshake lands; capturing before that yields frames of the splash duck.
  await page.waitForSelector(spec.ready ?? 'body', { timeout: (spec.ready_timeout ?? 40) * 1000 });
  close = () => app.close();
} else {
  const { chromium } = await import('playwright');
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: spec.width, height: spec.height },
    deviceScaleFactor: spec.scale ?? 1,
    colorScheme: spec.color_scheme ?? 'dark',
    reducedMotion: 'no-preference',
  });
  page = await context.newPage();
  close = () => browser.close();
}

const cdp = await startScreencast(page);
try {
  await runSteps(page, spec.steps);
} finally {
  try {
    await cdp.send('Page.stopScreencast');
  } catch {
    /* the page may already be gone */
  }
  await close();
}

if (frames.length < 2) {
  process.stdout.write(JSON.stringify({ frames: frames.length }) + '\n');
  process.exit(0);
}

// An ffmpeg concat list, so playback keeps the original wall-clock timing
// rather than assuming a constant rate the capture never actually achieved.
// The last entry needs its file repeated: concat gives the final entry no
// duration of its own.
const lines = [];
for (let i = 0; i < frames.length; i++) {
  const next = frames[i + 1];
  const dur = next ? Math.max(next.t - frames[i].t, 0.01) : (spec.tail ?? 1.5);
  lines.push(`file '${frames[i].name}'`, `duration ${dur.toFixed(4)}`);
}
lines.push(`file '${frames[frames.length - 1].name}'`);
writeFileSync(join(outDir, 'frames.txt'), lines.join('\n') + '\n');

process.stdout.write(
  JSON.stringify({ frames: frames.length, seconds: frames[frames.length - 1].t, concat: 'frames.txt' }) + '\n',
);
