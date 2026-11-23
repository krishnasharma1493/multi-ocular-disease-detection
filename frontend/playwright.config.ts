/**
 * End-to-end tests (e2e/). Playwright builds the app and starts its OWN backend on a throwaway database,
 * so backend/app.db and backend/uploads/ are never touched. Every test file resets the demo data first.
 *
 *   npm run e2e              live model (outputs/best_efficientnet_b0.pth), port 7870
 *   npm run e2e:mocks        USE_MOCKS=true + DEMO_FIXTURES=true (stored "cached" results), port 7871
 *
 * Python: E2E_PYTHON, else the repo venv (../.venv/bin/python), else python3 on PATH.
 */
import { existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const mocks = process.env.E2E_MOCKS === 'true';
const port = mocks ? 7871 : 7870;
const venv = resolve(import.meta.dirname, '..', '.venv', 'bin', 'python');
const python = process.env.E2E_PYTHON ?? (existsSync(venv) ? venv : 'python3');
// Not deleted here: Playwright loads this file in every worker too, while the server is using the database.
// Each test file resets the demo data through the API instead.
const data = join(tmpdir(), `retinascreen-e2e-${mocks ? 'mocks' : 'live'}`);
mkdirSync(data, { recursive: true });

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1, // one shared backend and database: tests run one after another
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
    viewport: { width: 1280, height: 900 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } } }],
  webServer: {
    command: `npm run build && cd ../backend && "${python}" -m uvicorn app.main:app --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/health`,
    reuseExistingServer: false,
    timeout: 180_000,
    stdout: 'ignore',
    stderr: 'pipe',
    env: {
      APP_ENV: 'test',
      DATABASE_URL: `sqlite:///${join(data, 'e2e.db')}`,
      UPLOAD_DIR: join(data, 'uploads'),
      USE_MOCKS: String(mocks),
      DEMO_FIXTURES: String(mocks),
      SEED_ON_STARTUP: 'true',
      AUTH_DISABLED: 'false',
      DEMO_PASSWORD: process.env.E2E_PASSWORD ?? 'camp-S3HqmECzyZSY',
      JWT_SECRET: 'e2e-'.padEnd(64, 'x'),
      MODEL_DEVICE: process.env.MODEL_DEVICE ?? 'cpu',
    },
  },
});
