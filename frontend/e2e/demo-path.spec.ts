// #16: the whole demo path, as a technician would click it.
// Live model (npm run e2e): P-0180 gets a live "Possible: Cataract".
// USE_MOCKS (npm run e2e:mocks): P-0180 gets "Model offline" (nothing made up); seeded P-0175 shows its stored result.
import { expect, test } from '@playwright/test';
import { API, MOCKS, bearer, resetDemo, seedImage, signIn, token } from './helpers';

test.beforeAll(async ({ request }) => resetDemo(request));

test('sign in → ledger → new screening → analyze → normal result → review → model card', async ({ page, request }) => {
  test.setTimeout(180_000);
  await signIn(page);

  // Ledger numbers come from the API
  const stats = await (await request.get(`${API}/screenings/stats`, { headers: bearer(await token(request)) })).json();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(`Today’s camp — ${stats.data.total} eyes screened`);

  // New screening P-0180 with the seeded cataract photo
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'New screening' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'New screening' })).toBeVisible();
  await page.getByLabel('A fundus photo from an eye clinic').check();
  await page.getByRole('radio', { name: 'Right eye (OD)' }).check();
  await page.locator('#photo-file').setInputFiles(seedImage('cataract_354_right.jpg'));
  await expect(page.getByText('PHOTO PLACED')).toBeVisible();
  await page.getByRole('button', { name: /Check my eye/ }).click();
  await page.waitForURL(/\/screenings\/\d+\/scan$/);
  const newId = Number(page.url().match(/screenings\/(\d+)\/scan/)![1]);

  let cataractId = newId;
  if (MOCKS) {
    await expect(page.getByRole('alert')).toContainText('Model offline: no result for this image');
    await expect(page.getByText('Possible: Cataract.')).toHaveCount(0);
    cataractId = 7; // seeded P-0175, same photo, stored result
    await page.goto(`/screenings/${cataractId}/scan`);
    await expect(page.getByText('DEMO RESULT · PRECOMPUTED, NOT LIVE')).toBeVisible();
  } else {
    await expect(page.getByText(/LIVE MODEL OUTPUT · \d+ MS/)).toBeVisible({ timeout: 90_000 });
  }
  await expect(page.getByRole('link', { name: /See your result and ask questions/ })).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('.verdict .words')).toHaveText('Possible: Cataract.');

  // A normal photo: the four-disease "not detected" line, never "healthy"
  await page.goto(MOCKS ? '/screenings/5' : '/screenings/5/scan');
  if (!MOCKS) await expect(page.getByRole('link', { name: /See your result and ask questions/ })).toBeVisible({ timeout: 90_000 });
  await expect(page.locator('.verdict .words')).toHaveText('Not detected.');
  await expect(page.getByText('Screens these four diseases only; other eye conditions are not checked.')).toBeVisible();

  // Review the cataract result
  await page.goto(`/screenings/${cataractId}`);
  await page.getByRole('radio', { name: 'Agree', exact: true }).click();
  await page.getByLabel('NOTE (OPTIONAL)').fill('Lens opacity visible.');
  await page.getByRole('button', { name: 'Save read' }).click();
  await expect(page.getByText(/^SAVED \d\d:\d\d/)).toBeVisible();
  await expect(page.locator('.crumb .status')).toContainText('✓ REVIEWED');

  // Model card
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Model' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Certificate of calibration' })).toBeVisible();
  const card = (await (await request.get(`${API}/model`, { headers: bearer(await token(request)) })).json()).data;
  await expect(page.locator('.limits li')).toHaveCount(card.limitations.length);
  await expect(page.getByRole('heading', { level: 2 })).toHaveText(['Myopia', 'Cataract', 'Glaucoma', 'Diabetic retinopathy']);
  await expect(page.getByText(MOCKS ? 'OFFLINE · STORED RESULTS ONLY' : /^LIVE · /)).toBeVisible();
});
