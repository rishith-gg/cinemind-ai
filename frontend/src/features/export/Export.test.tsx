import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { client } from "../../api/client.gen";
import { Toaster } from "../../components/Toaster";
import { useCurrentProject } from "../../lib/currentProject";
import { useToasts } from "../../lib/toast";
import { ExportPage } from "./ExportPage";

const timeline = {
  id: "t1abcdef",
  project_id: "p1",
  name: "All shots",
  kind: "all_shots",
  fps_num: 60000,
  fps_den: 1001,
  width: 3840,
  height: 2160,
  params: { excluded: [] },
  created_at: "2026-10-09T00:00:00Z",
  item_count: 5,
  duration_frames: 4316,
  duration_s: 72,
  warnings: ["1 clip(s) do not match the timeline rate of 59.94 fps (slow.mov)."],
  export_dir: "/data/projects/p1/exports",
  formats: ["fcp7xml", "edl", "otio"],
};

beforeEach(() => {
  client.setConfig({ baseUrl: "http://localhost" });
  useCurrentProject.setState({ id: "p1" });
});
afterEach(() => {
  vi.unstubAllGlobals();
  useCurrentProject.setState({ id: null });
  useToasts.setState({ toasts: [] });
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ExportPage />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("lists timelines with warnings and a download link per format", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json([timeline])));
  renderPage();
  const card = within(await screen.findByRole("listitem", { name: "All shots" }));
  expect(card.getByText(/5 cuts · 1:12 · 59.94 fps · 3840×2160/)).toBeInTheDocument();
  expect(card.getByRole("note")).toHaveTextContent("do not match the timeline rate");
  for (const name of ["Download FCP7 XML (DaVinci Resolve)", "Download EDL", "Download OTIO"])
    expect(card.getByRole("button", { name })).toBeInTheDocument();
  expect(card.getByText("/data/projects/p1/exports")).toBeInTheDocument();
});

it("downloads an export as a file, and shows why when the backend refuses", async () => {
  const refusal = "An EDL cannot describe timelines above 60 fps. Use FCP7 XML or OTIO for this one.";
  const fetchMock = vi.fn(async (input: Request) => {
    const path = new URL(input.url).pathname;
    if (path.endsWith("/export/fcp7xml"))
      return new Response("<xmeml/>", { headers: { "content-disposition": "attachment; filename*=utf-8''All%20shots_t1abcdef.xml" } });
    if (path.endsWith("/export/edl")) return Response.json({ code: "invalid_input", message: refusal }, { status: 422 });
    return Response.json([timeline]);
  });
  vi.stubGlobal("fetch", fetchMock);
  const saved: string[] = [];
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined }));
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    saved.push(this.download);
  });
  renderPage();
  await userEvent.click(await screen.findByRole("button", { name: "Download FCP7 XML (DaVinci Resolve)" }));
  await waitFor(() => expect(saved).toEqual(["All shots_t1abcdef.xml"]));
  await userEvent.click(screen.getByRole("button", { name: "Download EDL" }));
  expect(await screen.findByText(refusal)).toBeInTheDocument();
  expect(saved).toHaveLength(1);
  click.mockRestore();
});

it("builds a timeline with the chosen rate and option", async () => {
  const fetchMock = vi.fn(async (input: Request) =>
    input.method === "POST" ? Response.json({ ...timeline, items: [] }, { status: 201 }) : Response.json([]),
  );
  vi.stubGlobal("fetch", fetchMock);
  renderPage();
  expect(await screen.findByText("No timelines yet")).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("Frame rate"), "29.97 fps");
  await userEvent.click(screen.getByLabelText("Leave out clips at other frame rates"));
  await userEvent.click(screen.getByRole("button", { name: "Build timeline" }));
  await waitFor(() => expect(fetchMock.mock.calls.some(([r]) => r.method === "POST")).toBe(true));
  const post = fetchMock.mock.calls.map(([r]) => r).find((r) => r.method === "POST");
  expect(new URL(post!.url).pathname).toBe("/api/projects/p1/timelines");
  expect(await post!.json()).toEqual({ name: "All shots", fps: [30000, 1001], mixed_rates: "exclude" });
  expect(await screen.findByText("Timeline “All shots” built with 5 cuts.")).toBeInTheDocument();
});

it("shows the backend's reason when nothing can be built", async () => {
  const message = "There are no shots yet. Import footage and wait for processing to finish.";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) =>
      input.method === "POST" ? Response.json({ code: "invalid_input", message }, { status: 422 }) : Response.json([]),
    ),
  );
  renderPage();
  await userEvent.click(await screen.findByRole("button", { name: "Build timeline" }));
  expect(await screen.findByText(message)).toBeInTheDocument();
});
