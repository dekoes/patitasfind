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

    // Login demo vacío
    await page.click('#auth-submit', { force: true });
    await page.waitForSelector('[data-s="home"].active', { timeout: 5000 });
    console.log('Home loaded');

    // Abrir Tinder desde el corazón del header
    await page.click('#home-discover');
    await page.waitForSelector('[data-s="discover"].active', { timeout: 5000 });
    console.log('Discover (Tinder) opened');

    // Esperar a que cargue la tarjeta
    await page.waitForSelector('#discover-card', { timeout: 10000 });
    await delay(800);

    // Obtener nombre del primer perro
    const firstDogName = await page.locator('#discover-name').textContent();
    console.log('First dog:', firstDogName);

    // Dar like
    await page.click('#like-btn');
    await delay(600);

    // Puede aparecer modal de match o pasar al siguiente perro
    const matchVisible = await page.locator('#match-modal').isVisible().catch(() => false);
    console.log('Match modal visible:', matchVisible);

    if (matchVisible) {
      // Abrir cuestionario
      await page.click('#match-questionnaire', { force: true });
      await page.waitForSelector('[data-s="questionnaire"].active', { timeout: 5000 });
      console.log('Questionnaire opened');

      // Llenar cuestionario
      await page.selectOption('#q-housing', 'casa_con_jardin');
      await page.selectOption('#q-experience', 'mucha');
      await page.selectOption('#q-children', 'no');
      await page.selectOption('#q-other-pets', 'no');
      await page.selectOption('#q-budget', '100-200');
      await page.selectOption('#q-outdoor', 'jardin');

      await page.click('#questionnaire-form button[type="submit"]', { force: true });
      await delay(1000);
      console.log('Questionnaire submitted');
    }

    // Ver detalle deslizando hacia arriba
    await page.evaluate(() => {
      const detail = document.getElementById('tinder-detail');
      if (detail) detail.style.transform = 'translateY(0)';
    });
    await delay(500);
    const detailDesc = await page.locator('#detail-description').textContent().catch(() => '');
    console.log('Detail description present:', detailDesc.length > 0);

    console.log('\n=== TINDER E2E TEST COMPLETED ===');
  } catch (e) {
    console.error('TEST FAILED:', e.message);
    await page.screenshot({ path: 'test-e2e-tinder-fail.png', fullPage: true });
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
