import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { ScriptOut } from "../../api";
import { client } from "../../api/client.gen";
import { Toaster } from "../../components/Toaster";
import { useCurrentProject } from "../../lib/currentProject";
import { useToasts } from "../../lib/toast";
import { ScriptPage } from "./ScriptPage";

const take = { id: "k1", media_id: "m1", filename: "IMG_1.MOV", rank: 1, start_s: 0.2, end_s: 1.8, text: "walking into the forest now", lexical: 0.95, semantic: 0.9, score: 0.9 };
const doc: ScriptOut = {
  id: "d1",
  project_id: "p1",
  name: "Forest",
  format: "fountain",
  created_at: "2026-10-16T00:00:00Z",
  alignment: { semantic: true, text_model: "minilm-l6", segments: 12, lexical_weight: 0, semantic_weight: 1, limit: 0.3, dialogue_lines: 2, found: 1 },
  min_score: 0.3,
  dialogue_lines: 2,
  with_take: 1,
  lines: [
    { id: "s", index: 0, kind: "scene", character: null, scene: "INT. FOREST", text: "INT. FOREST", choice: "auto", chosen_take_id: null, why: "", takes: [] },
    { id: "l1", index: 1, kind: "dialogue", character: "ANNA", scene: "INT. FOREST", text: "Walking into the forest now.", choice: "auto", chosen_take_id: "k1", why: "best match", takes: [take, { ...take, id: "k2", rank: 2, start_s: 30, score: 0.6 }] },
    { id: "l2", index: 2, kind: "dialogue", character: "BEN", scene: "INT. FOREST", text: "A storm is coming.", choice: "auto", chosen_take_id: null, why: "not found in any transcript", takes: [] },
  ],
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
      <MemoryRouter initialEntries={["/script"]}>
        <Routes>
          <Route path="/script" element={<ScriptPage />} />
          <Route path="/timeline/:id" element={<p>timeline page</p>} />
        </Routes>
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("asks for a script when there is none and sends the pasted text", async () => {
  let sent: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      if (input.method === "POST") {
        sent = await input.json();
        return Response.json(doc, { status: 201 });
      }
      return Response.json({ code: "not_found", message: "This project has no script yet." }, { status: 404 });
    }),
  );
  renderPage();
  await userEvent.type(await screen.findByLabelText("Screenplay"), "ANNA{enter}Walking into the forest now.");
  await userEvent.click(screen.getByRole("button", { name: "Find the lines in the footage" }));
  expect(await screen.findByRole("status")).toHaveTextContent("1 of 2 dialogue lines have a take");
  expect(sent).toEqual({ name: "Script", text: "ANNA\nWalking into the forest now." });
});

it("shows each line's take and why, lets the editor choose another, and builds the assembly", async () => {
  const calls: { method: string; path: string; body?: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      const path = new URL(input.url).pathname;
      calls.push({ method: input.method, path, body: input.method === "GET" ? undefined : await input.json() });
      if (path.endsWith("/assembly")) return Response.json({ id: "t9" }, { status: 201 });
      return Response.json(doc);
    }),
  );
  renderPage();
  const lines = await screen.findByRole("list", { name: "Script lines" });
  const first = within(within(lines).getByRole("listitem", { name: "Line 1" }));
  expect(first.getByText(/heard “walking into the forest now” · match 0.90 \(words 0.95, meaning 0.90\) · best match/)).toBeInTheDocument();
  expect(within(lines).getByRole("listitem", { name: "Line 2" })).toHaveTextContent("No take used: not found in any transcript.");
  expect(screen.getByRole("status", { name: "Script summary" })).toHaveTextContent("scored by meaning (minilm-l6); the words set each take's in and out");

  await userEvent.selectOptions(first.getByLabelText("Take for line 1"), "k2");
  await waitFor(() => expect(calls.at(-1)).toEqual({ method: "PUT", path: "/api/script-lines/l1/take", body: { take_id: "k2" } }));
  await userEvent.selectOptions(first.getByLabelText("Take for line 1"), "not_filmed");
  await waitFor(() => expect(calls.at(-1)?.body).toEqual({ not_filmed: true }));

  await userEvent.click(screen.getByRole("button", { name: "Build script assembly" }));
  expect(await screen.findByText("timeline page")).toBeInTheDocument();
});
