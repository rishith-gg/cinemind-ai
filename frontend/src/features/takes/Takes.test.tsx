import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { TakeGroupsOut, TakeMemberOut } from "../../api";
import { client } from "../../api/client.gen";
import { Toaster } from "../../components/Toaster";
import { useCurrentProject } from "../../lib/currentProject";
import { useToasts } from "../../lib/toast";
import { TakesPage } from "./TakesPage";

const settings = { text_min: 0.6, picture_min_with_text: 0.5, picture_min: 0.9, max_apart: 3 };

function member(shot_id: string, rank: number, extra: Partial<TakeMemberOut> = {}): TakeMemberOut {
  return {
    shot_id,
    media_id: `m-${shot_id}`,
    filename: `IMG_${shot_id}.MOV`,
    index: 0,
    start_s: 0,
    end_s: 8,
    keyframe_id: null,
    mark: null,
    stars: 0,
    rank,
    best: rank === 1,
    score: rank === 1 ? 0.91 : 0.62,
    signals: { focus: 0.9, exposure: 0.8, audio: null, complete: 1, clean: rank === 1 ? 1 : 0.75 },
    notes: rank === 1 ? [] : ["1 filler word(s)"],
    text: "we have to follow our passions",
    ...extra,
  };
}

const data: TakeGroupsOut = {
  groups: [
    {
      id: "g1",
      index: 0,
      kind: "speech",
      best_shot_id: "a",
      best_by: "auto",
      members: [member("a", 1), member("b", 2)],
      pairs: [{ a: "a", b: "b", rule: "speech", text: 0.96, picture: 0.88, adjacent: 1, score: 0.93, why: "same words (0.96)" }],
    },
  ],
  kept_apart: [{ shot_id: "c", media_id: "m-c", filename: "IMG_c.MOV", index: 1, start_s: 2, end_s: 4, keyframe_id: null }],
  grouped_at: "2026-10-16T00:00:00Z",
  details: { groups: 1, shots_in_groups: 2, shots_with_speech: 2 },
  settings,
  shots: 5,
  message: null,
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
        <TakesPage />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function stub(answer: (path: string, method: string, body: unknown) => TakeGroupsOut = () => data) {
  const calls: { method: string; path: string; body?: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      const path = new URL(input.url).pathname;
      const body = input.method === "GET" || input.method === "POST" ? undefined : await input.json();
      calls.push({ method: input.method, path, body });
      return Response.json(answer(path, input.method, body));
    }),
  );
  return calls;
}

it("shows each group with its best take, the signals, the notes and why they are grouped", async () => {
  stub();
  renderPage();
  const group = within(await screen.findByRole("article", { name: "Take group 1" }));
  expect(group.getByText(/2 takes · same words · Best take suggested from its signals/)).toBeInTheDocument();
  expect(group.getByText("Best take")).toBeInTheDocument();
  expect(group.getByText("0.91")).toBeInTheDocument();
  expect(group.getByRole("list", { name: "Notes on IMG_b.MOV, shot 1" })).toHaveTextContent("1 filler word(s)");
  expect(group.getAllByText("—")).toHaveLength(2); // audio not measured on either take
  expect(group.getByText(/IMG_a.MOV · 1 ↔ IMG_b.MOV · 1: same words \(0.96\) · words 0.96 · picture 0.88/)).toBeInTheDocument();
  expect(screen.getByText(/1 groups holding 2 of 5 shots \(2 with speech\)/)).toBeInTheDocument();
});

it("sends the editor's best take and 'not a take', and undoes a shot taken out", async () => {
  const calls = stub();
  renderPage();
  await userEvent.click(await screen.findByRole("button", { name: "Make IMG_b.MOV, shot 1 the best take" }));
  await waitFor(() => expect(calls.at(-1)).toEqual({ method: "PUT", path: "/api/projects/p1/takes/best", body: { shot_id: "b", best: true } }));
  await userEvent.click(screen.getByRole("button", { name: "IMG_a.MOV, shot 1 is not a take of these" }));
  await waitFor(() => expect(calls.at(-1)).toEqual({ method: "PUT", path: "/api/projects/p1/takes/apart", body: { shot_id: "a", apart: true } }));
  await userEvent.click(screen.getByRole("button", { name: "Undo" }));
  await waitFor(() => expect(calls.at(-1)).toEqual({ method: "PUT", path: "/api/projects/p1/takes/apart", body: { shot_id: "c", apart: false } }));
  await userEvent.click(screen.getByRole("button", { name: "Look for takes again" }));
  await waitFor(() => expect(calls.at(-1)).toMatchObject({ method: "POST", path: "/api/projects/p1/takes/regroup" }));
  expect(await screen.findByText(/Looked for takes: 1 group/)).toBeInTheDocument();
});

it("a best take chosen by the editor can go back to the signals; a rejected take cannot be made best", async () => {
  const chosen = { ...data.groups[0]!, best_by: "you" as const, members: [member("a", 1), member("b", 2, { mark: "reject" })] };
  const calls = stub(() => ({ ...data, groups: [chosen] }));
  renderPage();
  expect(await screen.findByText(/Best take chosen by you/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Make IMG_b.MOV, shot 1 the best take" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Let the signals choose" }));
  await waitFor(() => expect(calls.at(-1)?.body).toEqual({ shot_id: "a", best: false }));
});

it("says when takes were never looked for, and when none were found", async () => {
  stub(() => ({ ...data, groups: [], kept_apart: [], grouped_at: null, details: {}, message: "Takes have not been looked for in this project yet. Press Find takes." }));
  renderPage();
  expect(await screen.findByRole("alert")).toHaveTextContent("Press Find takes.");
  expect(screen.getByRole("button", { name: "Find takes" })).toBeInTheDocument();
});

it("explains an empty result", async () => {
  stub(() => ({ ...data, groups: [], kept_apart: [] }));
  renderPage();
  expect(await screen.findByText("No repeated takes found")).toBeInTheDocument();
});
