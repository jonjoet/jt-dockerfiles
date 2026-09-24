#!/usr/bin/env node
// Installed Streamlit service smoke. Run in the test-only Playwright image.
// Usage: node download_smoke.mjs URL JOB_ID ARTIFACT_DIRECTORY
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdirSync, writeFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const [url, jobId, output] = process.argv.slice(2);
assert(url && jobId && output, 'URL JOB_ID ARTIFACT_DIRECTORY required');
mkdirSync(output, { recursive: true });
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const context = await browser.newContext({ acceptDownloads: true });
const page = await context.newPage();
const errors = [];
const mediaRequests = [];
page.on('pageerror', error => errors.push(String(error)));
page.on('request', request => {
  if (new URL(request.url()).pathname.startsWith('/media/')) mediaRequests.push(request.url());
});
try {
  await page.goto(url);
  await page.getByRole('heading', { name: 'Previous results', exact: true }).waitFor();
  const result = page.getByTestId('stExpander').filter({ hasText: jobId });
  await result.locator('summary').click();
  const download = result.getByRole('button', { name: 'Download ZIP', exact: true });
  await download.waitFor();
  assert.match(await result.innerText(), /incomplete/i);
  assert.match(await result.innerText(), /Bundle available/);
  assert.equal(mediaRequests.length, 0, `Page rendering requested archive data: ${mediaRequests}`);
  const event = page.waitForEvent('download', { timeout: 60000 });
  await download.click();
  const archive = await event;
  const destination = join(output, archive.suggestedFilename());
  await archive.saveAs(destination);
  assert.equal(await archive.failure(), null);
  assert(statSync(destination).size > 0);
  assert(mediaRequests.length > 0, 'Download click must request the generated media');
  assert.deepEqual(errors, []);
  await page.screenshot({ path: join(output, 'download.png'), fullPage: true });
  writeFileSync(join(output, 'checks.json'), JSON.stringify({
    jobId, archive: destination, bytes: statSync(destination).size,
    checks: ['rendered completed warning result', 'no pre-click media request',
      'deferred download click succeeded'], errors,
  }, null, 2));
  console.log('installed-browser-download-ok');
} catch (error) {
  await page.screenshot({ path: join(output, 'failure.png'), fullPage: true });
  writeFileSync(join(output, 'failure.txt'), `${error.stack}\n${mediaRequests.join('\n')}\n${await page.locator('body').innerText()}`);
  throw error;
} finally {
  await browser.close();
}
