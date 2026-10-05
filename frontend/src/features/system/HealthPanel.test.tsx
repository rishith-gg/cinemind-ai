import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { client } from "../../api/client.gen";
import { HealthPanel } from "./HealthPanel";

const sample = {
  status: "ok",
  version: "0.1.0",
  report: {
    app_version: "0.1.0",
    ok: true,
    selected_tier: "lite",
    checks: [{ name: "ffmpeg", status: "ok", required: true, version: "9.0.2" }],
    hardware: { os: "T", arch: "x", cpu_name: "Test CPU", cpu_cores: 8, ram_gb: 8, free_disk_gb: 100, gpu: { kind: "none" } },
    recommended: { tier: "lite", reason: "small machine" },
  },
};

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <HealthPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => client.setConfig({ baseUrl: "http://localhost" }));
afterEach(() => vi.unstubAllGlobals());

it("shows backend health returned through the generated client", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(sample)));
  renderPanel();
  expect(await screen.findByTestId("backend-status")).toHaveTextContent("ok");
  expect(screen.getByText(/ffmpeg/)).toBeInTheDocument();
});

it("shows a friendly error when the backend is down", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
  renderPanel();
  expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the CineMind backend");
});
