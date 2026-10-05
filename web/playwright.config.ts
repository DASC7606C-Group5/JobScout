import { defineConfig } from '@playwright/test'

const replay = process.env.JOBSCOUT_REPLAY_E2E === '1'
const baseURL = replay ? 'http://127.0.0.1:3019' : 'http://127.0.0.1:3018'
const port = replay ? 3019 : 3018

export default defineConfig({
  testDir: './tests/browser',
  testMatch: replay ? '**/replay.spec.ts' : '**/workflow.spec.ts',
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
    reuseExistingServer: !replay && !process.env.CI,
    env: replay
      ? { API_PROXY_TARGET: process.env.JOBSCOUT_REPLAY_API_URL || 'http://127.0.0.1:8018' }
      : {},
  },
})
