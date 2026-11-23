// #12: screenings list: search, status filter, URL state, pagination, empty and error states, 375 px.
import { expect, test, type Page } from '@playwright/test';
import { API, bearer, horizontalOverflow, resetDemo, signIn, token } from './helpers';

test.beforeEach(async ({ request }) => resetDemo(request));

const rowRefs = (page: Page) => page.locator('table tbody .row-link').allTextContents();

test('search and status filter match the API, and survive reload and back/forward', async ({ page, request }) => {
  await signIn(page);
  await page.goto('/screenings');
  await page.getByLabel('SEARCH PATIENT REF').fill('p-01');  // case-insensitive
  await expect(page).toHaveURL(/q=p-01/);
  await page.getByRole('radiogroup', { name: 'Status filter' }).getByRole('radio', { name: 'Pending' }).click();
  await expect(page).toHaveURL(/status=pending/);

  const api = await (await request.get(`${API}/screenings?q=P-01&status=pending&page=1&limit=20`,
    { headers: bearer(await token(request)) })).json();
  const expected = api.data.map((s: { patient_ref: string }) => s.patient_ref);
  expect(expected.length).toBeGreaterThan(0);
  await expect(page.locator('table tbody tr')).toHaveCount(expected.length);
  expect(await rowRefs(page)).toEqual(expected);

  await page.reload();
  await expect(page.getByLabel('SEARCH PATIENT REF')).toHaveValue('p-01');
  await expect(page.getByRole('radio', { name: 'Pending' })).toHaveAttribute('aria-checked', 'true');
  expect(await rowRefs(page)).toEqual(expected);

  await page.goBack();  // before the status filter
  await expect(page.getByRole('radio', { name: 'Pending' })).toHaveAttribute('aria-checked', 'false');
  await page.goForward();
  await expect(page.getByRole('radio', { name: 'Pending' })).toHaveAttribute('aria-checked', 'true');

  // Clearing the search restores the full list
  await page.getByLabel('SEARCH PATIENT REF').fill('');
  await page.getByRole('radio', { name: 'All' }).click();
  await expect(page.locator('table tbody tr')).toHaveCount(7);
});

test('pagination with more than 20 screenings', async ({ page, request }) => {
  const headers = bearer(await token(request));
  for (let i = 0; i < 16; i++) {  // 7 seeded + 16 = 23
    const r = await request.post(`${API}/screenings`, { headers, data: { patient_ref: `P-9${String(i).padStart(3, '0')}`, eye: 'left' } });
    expect(r.status()).toBe(201);
  }
  await signIn(page);
  await page.goto('/screenings');
  const pager = page.getByRole('navigation', { name: 'Pages' });
  await expect(page.getByText('SHOWING 1–20 OF 23')).toBeVisible();
  await expect(pager.getByText('PAGE 1 OF 2')).toBeVisible();
  await expect(pager.getByRole('button', { name: /Previous/ })).toBeDisabled();
  await pager.getByRole('button', { name: /Next/ }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.getByText('SHOWING 21–23 OF 23')).toBeVisible();
  await expect(page.locator('table tbody tr')).toHaveCount(3);
  await expect(pager.getByRole('button', { name: /Next/ })).toBeDisabled();
  await expect(pager.getByRole('button', { name: /Previous/ })).toBeEnabled();
  await page.reload();
  await expect(page.getByText('SHOWING 21–23 OF 23')).toBeVisible();
  await page.goBack();
  await expect(page.getByText('SHOWING 1–20 OF 23')).toBeVisible();

  // A page beyond the last one shows the filtered-empty state with a way back
  await page.goto('/screenings?page=9');
  await expect(page.getByText('No screenings match these filters')).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await expect(page.getByText('SHOWING 1–20 OF 23')).toBeVisible();
});

test('empty states and the error state', async ({ page, request }) => {
  // Filtered empty
  await signIn(page);
  await page.goto('/screenings?q=ZZZ-NONE');
  await expect(page.getByText('No screenings match these filters')).toBeVisible();

  // Error state with retry (the list request fails once)
  let fail = true;
  await page.route('**/api/v1/screenings?*', (route) => (fail ? route.fulfill({ status: 500, json: {
    success: false, error: { code: 'INTERNAL_ERROR', message: 'Something went wrong — check the backend terminal' } } }) : route.continue()));
  await page.goto('/screenings?q=P-0');
  await expect(page.getByRole('alert')).toContainText('Something went wrong', { timeout: 20_000 });
  fail = false;
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.locator('table tbody tr').first()).toBeVisible();
  await page.unroute('**/api/v1/screenings?*');

  // "No screenings yet": judge's only screening is deleted
  const judge = bearer(await token(request, 'judge@example.com'));
  expect((await request.delete(`${API}/screenings/8`, { headers: judge })).ok()).toBeTruthy();
  await page.getByRole('button', { name: 'Sign out' }).first().click();
  await signIn(page, 'judge@example.com');
  await page.goto('/screenings');
  await expect(page.getByText('No screenings yet')).toBeVisible();
});

test('table at 1280 px, cards at 375 px, reachable by keyboard', async ({ page }) => {
  await signIn(page);
  await page.goto('/screenings');
  await expect(page.locator('table thead')).toBeVisible();
  await page.setViewportSize({ width: 375, height: 800 });
  await expect(page.locator('table thead')).toBeHidden();
  expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);
  // Keyboard: Tab reaches the first row link and Enter opens it
  const first = page.locator('table tbody .row-link').first();
  for (let i = 0; i < 40 && !(await first.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press('Tab');
  await expect(first).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/screenings\/\d+$/);
});
