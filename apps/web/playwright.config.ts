import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e/hiruzen',
  testMatch: '**/*.e2e.ts',
  timeout: 30000,
  use: {
    baseURL: 'http://127.0.0.1:3101',
    browserName: 'chromium',
    channel: 'chrome',
    headless: true,
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 3101 --strictPort',
    url: 'http://127.0.0.1:3101',
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
});
