import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { client } from "../../api/client.gen";
import { useCurrentProject } from "../../lib/currentProject";
import { SearchPage } from "./SearchPage";

const hit = (rank: number, score: number, extra = {}) => ({ rank, score, contribution: 1 / (60 + rank), time_s: 1.2, text: null, parts: null, matched: [], ...extra });
const DEFAULTS = { relevance: 1, quality: 0.2, selection: 0.3, person: 0.1, scene: 0.1, duplicate: 0.3 };
const RESULT = {
  shot_id: "s1",
  media_id: "m1",
  filename: "walk.mov",
  shot_index: 0,
  start_s: 0,
  end_s: 4,
  jump_s: 1.2,
  keyframe_url: "/api/keyframes/k1/image",
  scene_name: "Scene 1",
  quality_score: 0.9,
  score: 0.0325,
  relevant: null,
  final: 1.12,
  breakdown: {
    relevance: { value: 1, weight: 1, contribution: 1 },
    quality: { value: 0.9, weight: 0.2, contribution: 0.18 },
    selection: { value: 0, weight: 0.3, contribution: 0 },
    person: { value: 0, weight: 0.1, contribution: 0 },
    scene: { value: 0, weight: 0.1, contribution: 0 },
    duplicate: { value: 0.2, weight: 0.3, contribution: -0.06 },
  },
  duplicate_of: "s0",
  notes: [],
  mark: null,
  stars: 0,
  why: {
    keyword: hit(1, -2.5, { text: "into the forest", parts: [{ text: "into the ", match: false }, { text: "forest", match: true }] }),
    labels: hit(2, 1, { matched: ["tag: Forest"] }),
    visual: hit(3, 0.27),
  },
};
const OUT = { query: "forest", like_shot_id: null, results: [RESULT], lists: { keyword: 1, labels: 4, text: 0, visual: 4 }, unavailable: {}, rrf_k: 60, weights: {}, ranking_weights: DEFAULTS, ranking_defaults: DEFAULTS };

const NO_FILTERS = { has_dialogue: false, selects_only: false, include_rejected: false };

interface Call {
  method: string;
  path: string;
  body: unknown;
}

function backend(out: unknown = OUT) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string | URL, init?: RequestInit) => {
      const req = input instanceof Request ? input : new Request(new URL(String(input), "http://localhost"), init);
      const url = new URL(req.url);
      const body = req.method === "GET" ? null : req.headers.get("content-type")?.includes("json") ? await req.json() : "binary";
      calls.push({ method: req.method, path: url.pathname + url.search, body });
      if (url.pathname.endsWith("/mark")) return Response.json({ shot_id: "s1", ...(body as object), stars: (body as { stars?: number }).stars ?? 0 });
      if (url.pathname.endsWith("/judgments")) return Response.json({ query: "forest", shot_id: "s1", relevant: true, judged: 1 });
      if (url.pathname.includes("/search")) return Response.json(out);
      if (url.pathname.endsWith("/actors")) return Response.json({ actors: [{ id: "a1", name: "Asha" }] });
      if (url.pathname.endsWith("/scenes")) return Response.json({ scenes: [{ id: "c1", name: "Scene 1" }] });
      return Response.json([{ id: "m1", filename: "walk.mov" }]);
    }),
  );
  return calls;
}

beforeEach(() => {
  client.setConfig({ baseUrl: "http://localhost" });
  useCurrentProject.setState({ id: "p1" });
});
afterEach(() => {
  vi.unstubAllGlobals();
  useCurrentProject.setState({ id: null });
});

function wrap(path = "/search") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const searches = (calls: Call[]) => calls.filter((c) => c.path.endsWith("/search"));

it("searches, shows why each shot is there, and links to the moment", async () => {
  const calls = backend();
  wrap();
  await userEvent.type(screen.getByLabelText("Search shots"), "forest");
  await userEvent.click(screen.getByRole("button", { name: "Search" }));
  const card = within((await screen.findByRole("list", { name: "Search results" })).querySelector("li")!);
  expect(searches(calls)[0]).toMatchObject({ method: "POST", path: "/api/projects/p1/search", body: { q: "forest", filters: NO_FILTERS } });
  expect(card.getByRole("link")).toHaveAttribute("href", "/library/m1?t=1.2");
  expect(card.getByText("forest").tagName).toBe("MARK");
  const why = within(card.getByRole("list", { name: "Why this result" }));
  expect(why.getByText("Spoken words #1 (BM25 -2.50)")).toBeInTheDocument();
  expect(why.getByText("Labels #2: tag: Forest")).toBeInTheDocument();
  expect(why.getByText("Picture #3 (similarity 0.27)")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Found per list: Spoken words 1 · Labels 4 · Meaning of speech 0 · Picture 4");
  expect(screen.getByText(/Reciprocal Rank Fusion/)).toHaveTextContent("k = 60");
});

it("filters, finds more like a shot, and records judgments", async () => {
  const calls = backend();
  wrap("/search?q=forest");
  await screen.findByRole("list", { name: "Search results" });
  await userEvent.click(screen.getByLabelText("With speech"));
  await waitFor(() => expect(searches(calls).at(-1)?.body).toEqual({ q: "forest", filters: { ...NO_FILTERS, has_dialogue: true } }));
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Person" }), "a1");
  await waitFor(() => expect(searches(calls).at(-1)?.body).toEqual({ q: "forest", filters: { ...NO_FILTERS, has_dialogue: true, actor_id: "a1" } }));

  await userEvent.click(screen.getByRole("button", { name: "Good result: walk.mov shot 1" }));
  await waitFor(() => expect(calls.find((c) => c.path.endsWith("/judgments"))?.body).toEqual({ query: "forest", shot_id: "s1", relevant: true }));
  expect(await screen.findByRole("button", { name: "Good result: walk.mov shot 1", pressed: true })).toBeInTheDocument();
  expect(searches(calls)).toHaveLength(3); // the mark is patched in, not searched again

  await userEvent.click(screen.getByRole("button", { name: "More like this" }));
  await waitFor(() => expect(searches(calls).at(-1)?.body).toMatchObject({ like_shot_id: "s1" }));
});

it("searches by a picture and shows lists that could not run", async () => {
  const calls = backend({ ...OUT, query: null, lists: { visual: 4 }, unavailable: { text: "The text model 'minilm-l6' is not downloaded." } });
  wrap();
  const file = new File([new Uint8Array([137, 80, 78, 71])], "frame.png", { type: "image/png" });
  await userEvent.upload(screen.getByLabelText("Search by picture"), file);
  expect(await screen.findByRole("alert")).toHaveTextContent("Meaning of speech: The text model 'minilm-l6' is not downloaded.");
  expect(calls.find((c) => c.path.startsWith("/api/projects/p1/search/image"))).toMatchObject({ method: "POST", body: "binary" });
  expect(screen.queryByRole("button", { name: /Good result/ })).not.toBeInTheDocument();
});

it("asks for a project first", () => {
  useCurrentProject.setState({ id: null });
  wrap();
  expect(screen.getByText("No project selected")).toBeInTheDocument();
});

it("explains the score, marks shots, and re-ranks with other weights", async () => {
  const calls = backend();
  wrap("/search?q=forest");
  await screen.findByRole("list", { name: "Search results" });
  const table = within(screen.getByRole("table", { name: "Score breakdown" }));
  expect(table.getByRole("row", { name: /Relevance 1.00 × 1.0 \+1.00/ })).toBeInTheDocument();
  expect(table.getByRole("row", { name: /Duplicate \(minus\) 0.20 × 0.3 −0.06/ })).toBeInTheDocument();
  expect(table.getByRole("row", { name: /Score 1.12/ })).toBeInTheDocument();
  expect(screen.getByText(/Looks like another shot, placed higher/)).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Select walk.mov shot 1" }));
  await waitFor(() => expect(calls.find((c) => c.path === "/api/shots/s1/mark")?.body).toEqual({ mark: "select" }));
  expect(await screen.findByRole("button", { name: "Select walk.mov shot 1", pressed: true })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "4 stars for walk.mov shot 1" }));
  await waitFor(() => expect(calls.filter((c) => c.path === "/api/shots/s1/mark").at(-1)?.body).toEqual({ stars: 4 }));
  await userEvent.click(screen.getByRole("button", { name: "Reject walk.mov shot 1" }));
  expect(await screen.findByText(/Rejected: left out of search unless/)).toBeInTheDocument();

  await userEvent.click(screen.getByText("Ranking weights"));
  const slider = screen.getByLabelText("Weight of Technical quality");
  fireEvent.change(slider, { target: { value: "1.5" } });
  await waitFor(() =>
    expect(searches(calls).at(-1)?.body).toMatchObject({ q: "forest", weights: { relevance: 1, quality: 1.5, duplicate: 0.3 } }),
  );
  const sent = searches(calls).length;
  await userEvent.click(screen.getByRole("button", { name: "Back to the defaults" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Back to the defaults" })).not.toBeInTheDocument());
  expect(searches(calls)).toHaveLength(sent); // the cached search with the defaults is shown again
});

it("offers selects-only and show-rejected filters", async () => {
  const calls = backend();
  wrap("/search?q=forest");
  await screen.findByRole("list", { name: "Search results" });
  await userEvent.click(screen.getByLabelText("Selects only"));
  await waitFor(() => expect(searches(calls).at(-1)?.body).toEqual({ q: "forest", filters: { ...NO_FILTERS, selects_only: true } }));
  await userEvent.click(screen.getByLabelText("Show rejected"));
  await waitFor(() => expect(searches(calls).at(-1)?.body).toMatchObject({ filters: { selects_only: true, include_rejected: true } }));
});
