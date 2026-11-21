import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: 'tests/browser',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8000 },
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:3961',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } },
    },
  ],
  webServer: [
    {
      command:
        'node node_modules/next/dist/bin/next start starters/web --hostname 127.0.0.1 --port 3960',
      url: 'http://127.0.0.1:3960/api/health',
      reuseExistingServer: false,
    },
    {
      command:
        'node node_modules/next/dist/bin/next start examples/showcase --hostname 127.0.0.1 --port 3961',
      url: 'http://127.0.0.1:3961',
      env: { RUN_LIVE_AI: 'false' },
      reuseExistingServer: false,
    },
    {
      command: 'node --import tsx modules/realtime/examples/server.ts',
      port: 3787,
      env: { REALTIME_PORT: '3787' },
      reuseExistingServer: false,
    },
  ],
});
