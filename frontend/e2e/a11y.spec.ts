// #16: accessibility and responsive pass on every page, at 375, 768 and 1280 px.
// - axe-core (WCAG 2.0/2.1 A and AA rules): no serious or critical violation.
// - No horizontal page scroll.
// - Keyboard: every element Tab reaches has a visible focus indicator, and Tab never gets stuck (no trap).
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { API, bearer, horizontalOverflow, resetDemo, signIn, token } from './helpers';

const WIDTHS = [1280, 768, 375];
const PAGES = [
  ['/', 'Ledger'],
  ['/screenings', 'Screenings list'],
  ['/screenings/new', 'New screening'],
  ['/screenings/7', 'Screening detail (with a result)'],
  ['/screenings/8', 'Not found (another user’s screening)'],
  ['/screenings/7/scan', 'Scan and result reveal'],
  ['/model', 'Model card'],
  ['/no-such-page', 'Page not found'],
] as const;

/** Wait until page-entry animations (the 220 ms fade-in) have finished; endless pulses are ignored. */
async function settled(page: Page) {
  await page.waitForFunction(() => document.getAnimations()
    .every((a) => a.playState !== 'running' || a.effect?.getComputedTiming().iterations === Infinity));
}

async function axe(page: Page) {
  await settled(page);
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  return r.violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.impact} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`);
}

/** Tab through the page: returns elements without a visible focus style, and whether focus got stuck. */
async function tabWalk(page: Page, presses = 60) {
  await page.locator('body').click({ position: { x: 1, y: 1 } });
  const seen: string[] = [];
  const unstyled = new Set<string>();
  for (let i = 0; i < presses; i++) {
    await page.keyboard.press('Tab');
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const cs = getComputedStyle(el);
      const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
      const name = `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}[${(el.getAttribute('aria-label') ?? el.textContent ?? '').trim().slice(0, 30)}]`;
      return { name, ring };
    });
    if (!info) continue;
    seen.push(info.name);
    if (!info.ring) unstyled.add(info.name);
  }
  const tail = seen.slice(-10);
  const stuck = tail.length === 10 && new Set(tail).size === 1;
  return { unstyled: [...unstyled], stuck, reached: new Set(seen).size };
}

test.beforeAll(async ({ request }) => {
  test.setTimeout(150_000);
  await resetDemo(request);
  // Screening 7 gets a result (live model, or its stored result with USE_MOCKS)
  const r = await request.post(`${API}/screenings/7/analyze`, { headers: bearer(await token(request)), timeout: 120_000 });
  expect(r.ok(), await r.text()).toBeTruthy();
});

test('sign-in page', async ({ page }) => {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/login');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    expect(await axe(page), `axe at ${width}px`).toEqual([]);
    expect(await horizontalOverflow(page), `horizontal scroll at ${width}px`).toBeLessThanOrEqual(0);
  }
  const walk = await tabWalk(page, 12);
  expect(walk.unstyled).toEqual([]);
  expect(walk.stuck).toBe(false);
});

for (const [path, name] of PAGES) {
  test(`${name} (${path})`, async ({ page }) => {
    test.setTimeout(150_000);
    await signIn(page);
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(path);
      await expect(page.locator('main#main')).toBeVisible();
      await expect(page.locator('[aria-busy=true]')).toHaveCount(0, { timeout: 20_000 });
      if (path.endsWith('/scan')) {
        // The reveal is drawn frame by frame (inline opacity): wait until readings and verdict are fully shown
        await expect(page.getByRole('link', { name: /Open reviewer’s notes/ })).toBeVisible({ timeout: 60_000 });
        await page.waitForFunction(() => ['.read-col', '.verdict'].every((s) =>
          getComputedStyle(document.querySelector(s)!).opacity === '1'), undefined, { timeout: 30_000 });
      }
      expect(await axe(page), `axe at ${width}px`).toEqual([]);
      expect(await horizontalOverflow(page), `horizontal scroll at ${width}px`).toBeLessThanOrEqual(0);
      const walk = await tabWalk(page);
      expect(walk.unstyled, `focus indicator at ${width}px`).toEqual([]);
      expect(walk.stuck, `keyboard trap at ${width}px`).toBe(false);
      expect(walk.reached).toBeGreaterThan(1);
    }
  });
}
