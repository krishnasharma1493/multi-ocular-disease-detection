// #13: create with a photo, client and server upload errors, edit, replace photo (with the warning) and delete.
import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { API, bearer, resetDemo, seedImage, signIn, token } from './helpers';

test.beforeEach(async ({ request }) => resetDemo(request));

test('create P-0180 with a photo, then it is in the list', async ({ page, request }) => {
  await signIn(page);
  await page.goto('/screenings/new');
  await expect(page.getByRole('button', { name: /Check my eye/ })).toBeDisabled();
  await expect(page.getByText('NEEDS A PHOTO, WHERE THE PHOTO IS FROM AND AN EYE')).toBeVisible();
  await page.getByLabel('A fundus photo from an eye clinic').check();
  await page.getByRole('radio', { name: 'Right eye (OD)' }).check();
  await page.locator('#photo-file').setInputFiles(seedImage('cataract_354_right.jpg'));
  await page.getByRole('button', { name: /Check my eye/ }).dblclick();  // a double click still makes one screening
  await page.waitForURL(/\/screenings\/\d+\/scan$/);
  const list = await (await request.get(`${API}/screenings?q=Me`, { headers: bearer(await token(request)) })).json();
  expect(list.pagination.total).toBe(1);
  expect(list.data[0].has_image).toBe(true);
  expect(list.data[0].image.name).toBe('cataract_354_right.jpg');
});

test('client blocks a GIF and a file over 10 MB; the server rejects a broken JPEG', async ({ page }) => {
  await signIn(page);
  await page.goto('/screenings/new');
  const input = page.locator('#photo-file');
  await input.setInputFiles({ name: 'eye.gif', mimeType: 'image/gif', buffer: Buffer.from('GIF89a') });
  await expect(page.getByRole('alert')).toContainText('This file is GIF, not JPG or PNG.');
  await input.setInputFiles({ name: 'huge.jpg', mimeType: 'image/jpeg', buffer: Buffer.alloc(10.5 * 1024 * 1024, 0xff) });
  await expect(page.getByRole('alert')).toContainText('The limit is 10 MB.');
  await expect(page.getByRole('button', { name: /Check my eye/ })).toBeDisabled();

  // Passes the client check (JPEG type, small) but is not a real image: the server's 415 is shown
  await page.getByLabel('A fundus photo from an eye clinic').check();
  await page.getByRole('radio', { name: 'Left eye (OS)' }).check();
  await input.setInputFiles({ name: 'broken.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('not really a jpeg') });
  await page.getByRole('button', { name: /Check my eye/ }).click();
  await expect(page.getByRole('alert')).toContainText('ERR · FILE TYPE');
  await expect(page.getByRole('alert')).toContainText('broken.jpg');
  await expect(page).toHaveURL(/\/screenings\/new$/);  // the user stays on the form with the error
});

test('edit, replace photo (with warning) and delete', async ({ page, request }) => {
  test.setTimeout(150_000);
  const headers = bearer(await token(request));
  // Seeded P-0175 (#7) gets a result first: live model, or its stored result under USE_MOCKS
  const analyzed = await request.post(`${API}/screenings/7/analyze`, { headers, timeout: 120_000 });
  expect(analyzed.ok(), await analyzed.text()).toBeTruthy();

  await signIn(page);
  await page.goto('/screenings/7');
  await page.getByRole('button', { name: 'Edit' }).click();
  const dialog = page.getByRole('dialog', { name: 'EDIT THIS SCREENING' });
  await dialog.getByRole('radio', { name: 'Left (OS)' }).check();
  await dialog.getByLabel('ANYTHING YOU WANT TO REMEMBER (OPTIONAL)').fill('Edited in the end-to-end test.');
  await dialog.getByRole('button', { name: 'Save changes' }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Left eye');
  await expect(page.locator('.fact', { hasText: 'NOTES' })).toContainText('Edited in the end-to-end test.');
  await page.goto('/screenings?q=left');
  await expect(page.locator('table tbody .row-link')).toHaveText(['Screening #7']);

  // Replacing the photo of an analyzed screening asks first; Cancel keeps the result
  await page.goto('/screenings/7');
  await expect(page.locator('.verdict .words')).toHaveText('Possible: Cataract.');
  const photo = { name: 'normal_115_right.jpg', mimeType: 'image/jpeg', buffer: readFileSync(seedImage('normal_115_right.jpg')) };
  page.once('dialog', (d) => { expect(d.message()).toContain('clears the current result'); void d.dismiss(); });
  await page.locator('.crumb-actions input[type=file]').setInputFiles(photo);
  await expect(page.locator('.verdict .words')).toHaveText('Possible: Cataract.');
  page.once('dialog', (d) => void d.accept());
  await page.locator('.crumb-actions input[type=file]').setInputFiles(photo);
  await expect(page.locator('.verdict .words')).toHaveText('Awaiting analysis.');
  await expect(page.locator('.fact', { hasText: 'IMAGE' })).toBeVisible();

  // Delete asks with the patient ref, then the list and stats no longer count it
  const before = (await (await request.get(`${API}/screenings/stats`, { headers })).json()).data.total;
  page.once('dialog', (d) => { expect(d.message()).toContain('Delete this screening'); void d.accept(); });
  await page.getByRole('button', { name: 'Delete' }).click();
  await page.waitForURL(/\/screenings$/);
  await expect(page.locator('table tbody tr').first()).toBeVisible();
  await expect(page.locator('table tbody .row-link', { hasText: 'Screening #7' })).toHaveCount(0);
  const after = (await (await request.get(`${API}/screenings/stats`, { headers })).json()).data.total;
  expect(after).toBe(before - 1);
});
