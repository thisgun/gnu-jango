import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  use: {
    baseURL:
      process.env.PLAYWRIGHT_BASE_URL ||
      process.env.LOCAL_APP_URL ||
      'http://localhost:3000',
    screenshot: 'only-on-failure',
  },
  reporter: [['list']],
});
