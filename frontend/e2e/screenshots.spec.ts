// README screenshots (docs/images/). Not part of the normal run: `npm run e2e:screenshots`.
import { expect, test, type Page } from '@playwright/test';
import { resolve } from 'node:path';
import { API, bearer, resetDemo, signIn, token } from './helpers';

const OUT = resolve(import.meta.dirname, '..', '..', 'docs', 'images');  // used by the README
const EXTRA = resolve(import.meta.dirname, '..', 'test-results', 'screenshots');  // for PRs, git-ignored

/** Wait for the page fade-in to finish, so screenshots are not washed out. */
const settled = (page: Page) => page.waitForFunction(() => document.getAnimations()
  .every((a) => a.playState !== 'running' || a.effect?.getComputedTiming().iterations === Infinity));

test.skip(!process.env.SCREENSHOTS, 'set SCREENSHOTS=1 (npm run e2e:screenshots)');

test('dashboard and result page', async ({ page, request }) => {
  test.setTimeout(150_000);
  await resetDemo(request);
  await request.post(`${API}/screenings/7/analyze`, { headers: bearer(await token(request)), timeout: 120_000 });
  await page.setViewportSize({ width: 1280, height: 900 });
  await signIn(page);
  await settled(page);
  await page.screenshot({ path: `${OUT}/dashboard.png`, fullPage: true });

  await page.goto('/screenings/3/scan');
  await expect(page.getByRole('link', { name: /Open reviewer’s notes/ })).toBeVisible({ timeout: 60_000 });
  await page.waitForFunction(() => ['.read-col', '.verdict'].every((s) =>
    getComputedStyle(document.querySelector(s)!).opacity === '1'), undefined, { timeout: 30_000 });
  await page.screenshot({ path: `${OUT}/result.png`, fullPage: true });

  await page.goto('/screenings/3');
  await expect(page.getByRole('meter')).toHaveCount(4);
  await settled(page);
  await page.screenshot({ path: `${EXTRA}/detail.png`, fullPage: true });

  await page.setViewportSize({ width: 375, height: 812 });
  await page.reload();
  await expect(page.getByRole('meter')).toHaveCount(4);
  await settled(page);
  await page.screenshot({ path: `${EXTRA}/detail-375.png`, fullPage: true });
});
