import { chromium } from 'playwright';

const BASE = 'https://transactions-busy-psychological-rent.trycloudflare.com/app/';

function delay(ms) {
  return new Promise(r => setTimeout(r, ms));
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });

  page.on('console', msg => {
    if (msg.type() === 'error') console.log(`[${msg.type()}]`, msg.text());
  });
  page.on('pageerror', err => console.log('[PAGE ERROR]', err.message));
  page.on('requestfailed', req => console.log('[REQUEST FAILED]', req.url(), req.failure().errorText));

  try {
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await page.waitForSelector('[data-s="auth"].active', { timeout: 5000 });

    // Scroll para ver botones Google/demo
    const googleVisible = await page.locator('#google-login').isVisible().catch(() => false);
    const demoVisible = await page.locator('#demo-login').isVisible().catch(() => false);
    console.log('Google button visible:', googleVisible);
    console.log('Demo button visible:', demoVisible);

    // Click en Entrar sin llenar nada
    await page.click('#auth-submit', { force: true });
    await page.waitForSelector('[data-s="home"].active', { timeout: 5000 });
    await delay(800);

    const location = await page.locator('#home-location').textContent().catch(() => '');
    console.log('Home loaded after empty login, location:', location);

    console.log('\n=== EMPTY LOGIN TEST COMPLETED ===');
  } catch (e) {
    console.error('TEST FAILED:', e.message);
    await page.screenshot({ path: 'test-empty-login-fail.png', fullPage: true });
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
