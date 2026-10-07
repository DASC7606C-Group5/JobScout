import { defineConfig } from '@playwright/test'

const replay = process.env.JOBSCOUT_REPLAY_E2E === '1'
const account = process.env.JOBSCOUT_ACCOUNT_E2E === '1'
const port = account ? 3028 : replay ? 3019 : 3018
const baseURL = `http://127.0.0.1:${port}`

export default defineConfig({
  testDir: './tests/browser',
  testMatch: account ? '**/account.spec.ts' : replay ? '**/replay.spec.ts' : '**/workflow.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL,
    browserName: 'chromium',
    channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge',
    headless: true,
    trace: 'off',
  },
  reporter: 'list',
  webServer: {
    command: `node node_modules\\vite\\bin\\vite.js --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: !replay && !account && !process.env.CI,
    env: account
      ? { API_PROXY_TARGET: process.env.JOBSCOUT_ACCOUNT_API_URL || 'http://127.0.0.1:8028' }
      : replay
        ? { API_PROXY_TARGET: process.env.JOBSCOUT_REPLAY_API_URL || 'http://127.0.0.1:8018' }
        : {},
  },
})
