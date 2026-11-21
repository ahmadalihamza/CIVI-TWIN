const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const [mode, base] = process.argv.slice(2);
assert(['local', 'pages'].includes(mode) && base, 'Usage: node browser.cjs local|pages URL');

async function local(page) {
  await page.addInitScript(() => {
    localStorage.setItem('civitwin.toured', '1');
    localStorage.setItem('civitwin.dataset', 'demo-bajaur-v1');
  });
  await page.goto(new URL('#plan', base).href);
  await page.locator('#reviewBtn').click();
  await page.locator('#confirmBtn').click();
  await page.waitForURL('**/#results');
  await page.getByRole('heading', { name: 'Independent audit' }).waitFor();
  assert.match(await page.locator('#resultsBox').innerText(), /Passed 12\/12/);

  await page.locator('[data-view=report]').click();
  const link = page.locator('#reportBox a[download]').last();
  const download = await page.request.get(new URL(await link.getAttribute('href'), base).href);
  assert(download.ok());
  assert.match(download.headers()['content-type'], /^text\/csv/);
  await page.reload();
  await page.getByRole('heading', { name: 'CIVITWIN AI planning report' }).waitFor();
}

async function pages(page) {
  const apiRequests = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.includes('/api/')) apiRequests.push(request.url());
  });
  await page.goto(base);
  await page.getByText('Published read-only demo.', { exact: false }).waitFor();
  assert.equal(await page.locator('[data-view=plan]').isVisible(), false);
  await page.getByRole('button', { name: 'Map: baseline' }).click();

  await page.locator('[data-view=results]').click();
  await page.getByRole('heading', { name: 'Independent audit' }).waitFor();
  assert.match(await page.locator('#resultsBox').innerText(), /Passed 12\/12/);
  await page.getByRole('button', { name: '2D', exact: true }).click();
  await page.locator('[data-lang=ur]').click();
  await page.locator('#explBox [lang=ur]').waitFor();
  await page.getByRole('img', { name: /Coverage versus weekly budget/ }).waitFor();

  await page.locator('[data-view=stress]').click();
  assert.match(await page.locator('#stressStatus').innerText(), /20 cases/);
  assert.equal(await page.locator('#stressBtn').isVisible(), false);

  await page.locator('[data-view=report]').click();
  const exports = await page.locator('#reportBox .dl-row a').evaluateAll(
    (links) => links.map((link) => link.href),
  );
  assert.equal(exports.length, 9);
  for (const url of exports) {
    const response = await page.request.get(url);
    assert(response.ok(), `Export failed at ${url}`);
    if (url.endsWith('.json')) {
      const report = await response.json();
      assert.equal(report.dataset_manifest.is_synthetic, true);
      assert.equal(report.run.audit.passed, true);
    }
  }
  await page.setViewportSize({ width: 375, height: 812 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  assert.deepEqual(apiRequests, []);
}

async function main() {
  const browser = await chromium.launch({ channel: process.env.CIVITWIN_BROWSER_CHANNEL });
  try {
    const page = await browser.newPage({ reducedMotion: 'reduce' });
    const pageErrors = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    await (mode === 'local' ? local : pages)(page);
    assert.deepEqual(pageErrors, []);
    console.log(`Browser check passed for ${mode} at ${base}`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
