import { expect, type APIRequestContext, type Page } from '@playwright/test';
import { resolve } from 'node:path';

export const PASSWORD = process.env.E2E_PASSWORD ?? 'camp-S3HqmECzyZSY';
export const MOCKS = process.env.E2E_MOCKS === 'true';
export const SEED_IMAGES = resolve(import.meta.dirname, '..', '..', 'backend', 'seed_data', 'images');
export const seedImage = (name: string) => resolve(SEED_IMAGES, name);
export const API = '/api/v1';

export async function token(request: APIRequestContext, email = 'demo@example.com') {
  const r = await request.post(`${API}/auth/login`, { data: { email, password: PASSWORD } });
  expect(r.ok(), await r.text()).toBeTruthy();
  return (await r.json()).data.access_token as string;
}

export const bearer = (t: string) => ({ Authorization: `Bearer ${t}` });

/** Drop and reseed the demo data (admin endpoint), so every file starts from the same eight screenings. */
export async function resetDemo(request: APIRequestContext) {
  const r = await request.post(`${API}/demo/reset`, { headers: bearer(await token(request)) });
  expect(r.ok(), await r.text()).toBeTruthy();
}

/** Sign in through the real form. */
export async function signIn(page: Page, email = 'demo@example.com') {
  await page.goto('/login');
  await page.getByLabel('EMAIL').fill(email);
  await page.getByLabel('PASSWORD').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: /Your eye screenings/ })).toBeVisible();
}

/** Horizontal page scroll (the page wider than the viewport). */
export async function horizontalOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}
