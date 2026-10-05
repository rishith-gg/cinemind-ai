import { defineConfig } from "@playwright/test";

const PORT = 8765;

export default defineConfig({
  testDir: "./e2e",
  use: { channel: "chromium", baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  // The real app: built UI + API + worker, on a throwaway data dir (data/e2e, gitignored; wiped by `T e2e`).
  webServer: {
    command: "uv run cinemind serve",
    cwd: "..",
    url: `http://127.0.0.1:${PORT}/api/system/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: { CINEMIND_PORT: String(PORT), CINEMIND_DATA_DIR: "data/e2e" },
  },
});
