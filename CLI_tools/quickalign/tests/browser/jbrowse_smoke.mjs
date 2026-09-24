#!/usr/bin/env node
// Render a quickalign bundle in pinned JBrowse Web 4.3.0, using the same
// default-session model as Desktop. Adapted from gcev's bundle smoke recipe.
import { createReadStream, existsSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { extname, join, normalize, resolve } from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const [bundleArg, artifactArg, webRootArg = '/opt/jbrowse'] = process.argv.slice(2);
if (!bundleArg || !artifactArg) throw new Error('Usage: jbrowse_smoke.mjs BUNDLE ARTIFACT_DIR [WEB_ROOT]');
const bundle = resolve(bundleArg);
const artifactDir = resolve(artifactArg);
const webRoot = resolve(webRootArg);
if (readFileSync(join(webRoot, 'version.txt'), 'utf8').trim() !== '4.3.0') {
  throw new Error('This acceptance recipe requires JBrowse Web 4.3.0');
}
const mime = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.wasm': 'application/wasm', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.gz': 'application/gzip', '.bw': 'application/octet-stream',
  '.bam': 'application/octet-stream', '.bai': 'application/octet-stream',
  '.fasta': 'text/plain', '.fai': 'text/plain', '.delta': 'text/plain',
  '.bed': 'text/plain', '.tsv': 'text/tab-separated-values',
};

function safePath(root, requested) {
  const path = resolve(root, `.${normalize(`/${requested}`)}`);
  if (!(path === root || path.startsWith(`${root}/`))) throw new Error('path traversal');
  return path;
}

function serveFile(req, res, path) {
  const size = statSync(path).size;
  const range = req.headers.range;
  res.setHeader('Accept-Ranges', 'bytes');
  res.setHeader('Content-Type', mime[extname(path)] || 'application/octet-stream');
  if (range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(range);
    if (!match) { res.writeHead(416); res.end(); return; }
    const start = match[1] ? Number(match[1]) : 0;
    const end = match[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
    res.writeHead(206, { 'Content-Range': `bytes ${start}-${end}/${size}`, 'Content-Length': end - start + 1 });
    createReadStream(path, { start, end }).pipe(res);
  } else {
    res.writeHead(200, { 'Content-Length': size });
    createReadStream(path).pipe(res);
  }
}


const config = JSON.parse(readFileSync(join(bundle, 'config.json'), 'utf8'));
const visible = config.defaultSession.views[0].init.tracks;
const annotationId = 'annotation';
const bamIds = config.tracks.filter(t => t.type === 'AlignmentsTrack').map(t => t.trackId);
if (!bamIds.length || !visible.includes(annotationId) || !visible.includes(bamIds[0])) {
  throw new Error('Default session must initialize annotation and first BAM');
}
const failures = [];
const requested = new Set();
const server = createServer((req, res) => {
  try {
    const pathname = decodeURIComponent(new URL(req.url, 'http://127.0.0.1').pathname);
    const isBundle = pathname.startsWith('/bundle/');
    const root = isBundle ? bundle : webRoot;
    const requestedPath = (isBundle ? pathname.slice(8) : pathname.slice(1)) || 'index.html';
    const path = safePath(root, requestedPath);
    if (!existsSync(path) || statSync(path).isDirectory()) { res.writeHead(404); res.end(); return; }
    if (isBundle) requested.add(requestedPath);
    serveFile(req, res, path);
  } catch (error) { res.writeHead(500); res.end(String(error)); }
});
await new Promise(ready => server.listen(0, '127.0.0.1', ready));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
page.on('pageerror', error => failures.push(error.message));
page.on('response', response => {
  if (response.url().startsWith(origin) && response.status() >= 400) {
    failures.push(`HTTP ${response.status()}: ${response.url()}`);
  }
});
page.on('requestfailed', req => {
  if (req.url().startsWith(origin)) failures.push(`requestfailed: ${req.url()}`);
});
try {
  await page.goto(`${origin}/?config=bundle/config.json`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(ids => {
    const view = window.JBrowseSession?.views[0];
    return view?.initialized && ids.every(id => view.tracks.some(track =>
      track.configuration.trackId === id && track.displays.length));
  }, visible, { timeout: 60_000 });
  const displays = await page.evaluate(() => window.JBrowseSession.views[0].tracks.map(track => ({
    trackId: track.configuration.trackId,
    displays: track.displays.map(display => ({
      displayId: display.configuration.displayId, type: display.configuration.type,
    })),
  })));
  for (const track of displays) {
    for (const display of track.displays) {
      await page.locator(`[data-testid="display-${display.displayId}"]`).waitFor({ state: 'visible' });
    }
  }
  // The alignments parent delegates rendering to its coverage/pileup children.
  // JBrowse also retains hidden "Loading" accessibility labels after completion.
  // Require completed, visibly painted feature and pileup canvases themselves.
  const rendered = await page.waitForFunction(({ annotationId, bamId }) => {
    const view = window.JBrowseSession.views[0];
    const targets = [
      { trackId: annotationId, suffix: '[data-testid="canvas-feature-overlay"] canvas' },
      { trackId: bamId, suffix: '[data-testid="pileup-overlay-normal"] canvas' },
    ];
    const reports = [];
    for (const { trackId, suffix } of targets) {
      const track = view.tracks.find(item => item.configuration.trackId === trackId);
      const display = track.displays[0];
      if (display.error || display.PileupDisplay?.error || display.SNPCoverageDisplay?.error) return null;
      const container = document.querySelector(`[data-testid="display-${display.configuration.displayId}"]`);
      const canvases = [...container.querySelectorAll(suffix)];
      let paintedPixels = 0;
      for (const canvas of canvases) {
        if (!canvas.dataset.testid?.endsWith('_done') || !canvas.width || !canvas.height) continue;
        const { data } = canvas.getContext('2d', { willReadFrequently: true })
          .getImageData(0, 0, canvas.width, canvas.height);
        for (let index = 3; index < data.length; index += 4) {
          if (data[index]) paintedPixels += 1;
        }
      }
      if (!paintedPixels) return null;
      reports.push({ trackId, displayId: display.configuration.displayId, paintedPixels });
    }
    return reports;
  }, { annotationId, bamId: bamIds[0] }, { timeout: 60_000 });
  const details = {
    jbrowseVersion: '4.3.0',
    displays,
    rendered: await rendered.jsonValue(),
    initialLocus: config.defaultSession.views[0].init.loc,
    configuredBams: bamIds,
    requested: [...requested].sort(),
  };
  writeFileSync(join(artifactDir, 'render.json'), JSON.stringify(details, null, 2));
  await page.screenshot({path:join(artifactDir, 'default.png'), fullPage:true});
  for (const uri of ['annotation/features.gff3.gz', `alignments/${bamIds[0]}.bam`]) {
    if (!requested.has(uri)) throw new Error(`Visible track did not request ${uri}`);
  }
  for (const id of bamIds.slice(1)) {
    if (displays.some(track => track.trackId === id)) throw new Error(`Additional BAM ${id} is initially visible`);
  }
  if (failures.length) throw new Error(failures.join('\n'));
  console.log(`jbrowse-render-ok version=4.3.0 tracks=${displays.map(t=>t.trackId).join(',')}`);
} catch (error) {
  await page.screenshot({path:join(artifactDir, 'failure.png'), fullPage:true});
  writeFileSync(join(artifactDir, 'failure.txt'), `${error.stack}\n${await page.locator('body').innerText()}\n${failures.join('\n')}`);
  throw error;
} finally {
  await browser.close();
  await new Promise(closed => server.close(closed));
}
