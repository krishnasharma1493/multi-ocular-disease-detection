// #14 and #15: the result shows exactly the API's numbers, in text as well as colour; reviews; model card.
import { expect, test } from '@playwright/test';
import { API, MOCKS, bearer, horizontalOverflow, resetDemo, seedImage, signIn, token } from './helpers';

type Finding = { code: string; disease: string; probability: number; threshold: number; positive: boolean };
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
const sentence = (n: string) => n.split(' ').map((w, i) => (i ? w.toLowerCase() : w)).join(' ');

test.beforeAll(async ({ request }) => resetDemo(request));

for (const [id, label] of [[7, 'cataract (positive)'], [6, 'myopia just under its threshold']] as const) {
  test(`readings equal the API for screening ${id}, ${label}`, async ({ page, request }) => {
    test.setTimeout(150_000);
    const headers = bearer(await token(request));
    const r = await request.post(`${API}/screenings/${id}/analyze`, { headers, timeout: 120_000 });
    expect(r.ok(), await r.text()).toBeTruthy();
    const result = (await r.json()).data as { findings: Finding[]; demo: boolean };

    await signIn(page);
    await page.goto(`/screenings/${id}`);
    const meters = page.getByRole('meter');
    await expect(meters).toHaveCount(4);
    for (const f of result.findings) {
      const row = page.locator('.readings-col .reading', { hasText: sentence(f.disease) });
      await expect(row.locator('.prob')).toHaveText(pct(f.probability));
      await expect(row).toContainText(`threshold ${pct(f.threshold)}`);
      await expect(row.locator('.res')).toHaveText(f.positive ? '▲ POSITIVE' : '○ NOT DETECTED');  // said in text, not only colour
      const meter = page.getByRole('meter', { name: `${f.disease} probability ${pct(f.probability)}, threshold ${pct(f.threshold)}` });
      await expect(meter).toHaveJSProperty('value', f.probability);
    }
    await expect(page.locator('.readings-col .live')).toContainText(result.demo ? 'DEMO RESULT' : 'live');
    if (id === 6) {
      const myopia = result.findings.find((f) => f.code === 'M')!;
      expect(myopia.positive).toBe(false);
      expect(myopia.probability).toBeLessThan(myopia.threshold);
      await expect(page.locator('.verdict .words')).toHaveText('Not detected.');
    }
    await page.setViewportSize({ width: 375, height: 800 });
    expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);
  });
}

test('model offline: a new photo gets the amber notice, never a made-up result', async ({ page }) => {
  test.skip(!MOCKS, 'only with USE_MOCKS=true (npm run e2e:mocks)');
  await signIn(page);
  await page.goto('/screenings/new');
  await page.getByLabel('A fundus photo from an eye clinic').check();
  await page.getByRole('radio', { name: 'Left eye (OS)' }).check();
  await page.locator('#photo-file').setInputFiles(seedImage('dr_5_right.jpg'));
  await page.getByRole('button', { name: /Check my eye/ }).click();
  const notice = page.locator('.notice-amber[role=alert]');
  await expect(notice).toContainText('◐ MODEL OFFLINE');
  await expect(notice).toContainText('Model offline: no result for this image. Nothing has been made up');
  await notice.getByRole('link', { name: 'Open screening' }).click();
  await expect(page.locator('.verdict .words')).toHaveText('Awaiting analysis.');
  await expect(page.getByRole('meter')).toHaveCount(0);
});

test('seeded reviews show, and the review form works by keyboard', async ({ page }) => {
  test.skip(true, 'the clinician review box is hidden for patients (#24); remove this skip if it returns');
  await signIn(page);
  await page.goto('/screenings/2');
  await expect(page.getByRole('list', { name: 'Earlier reads, newest first' })).toContainText('Agree');
  await page.goto('/screenings/6');
  await expect(page.getByRole('list', { name: 'Earlier reads, newest first' })).toContainText('Disagree');
  await expect(page.locator('.crumb .status')).toContainText('REVIEWER: DISAGREE');

  // Keyboard only: arrow keys move through the read options, the form saves
  const group = page.getByRole('radiogroup', { name: 'Do you agree with the model’s verdict?' });
  await group.getByRole('radio', { checked: true }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(group.getByRole('radio', { name: 'Unsure' })).toBeFocused();
  await expect(group.getByRole('radio', { name: 'Unsure' })).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('NOTE (OPTIONAL)')).toBeFocused();
  await page.keyboard.type('Second look.');
  await page.getByRole('button', { name: 'Save read' }).click();
  await expect(page.getByRole('list', { name: 'Earlier reads, newest first' }).locator('li').first()).toContainText('Unsure');
});
