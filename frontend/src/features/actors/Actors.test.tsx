import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { client } from "../../api/client.gen";
import { useCurrentProject } from "../../lib/currentProject";
import { useToasts } from "../../lib/toast";
import { ActorPage } from "./ActorPage";
import { ActorsPage } from "./ActorsPage";
import { PeoplePanel } from "./PeoplePanel";

const actor = (id: string, name: string, named: boolean, tracks: number) => ({
  id,
  project_id: "p1",
  number: Number(id.slice(1)),
  name,
  named,
  tracks,
  faces: tracks * 5,
  clips: 2,
  seen_s: tracks * 2.5,
  crop_url: `/api/face-tracks/${id}/image`,
});
const track = (id: string, actor_id: string | null, state = "auto", start_s = 1.5, how = "similar faces") => ({
  id,
  media_id: "m1",
  filename: "picnic.mov",
  start_s,
  end_s: start_s + 2,
  face_count: 4,
  crop_url: `/api/face-tracks/${id}/image`,
  actor_id,
  actor_name: actor_id === "a2" ? "Asha" : actor_id ? "Actor 001" : null,
  state,
  assignment: { how, similarity_to_group: 0.71, method: "agglomerative", cluster_distance: 0.6 },
});
const OVERVIEW = {
  actors: [actor("a1", "Actor 001", false, 4), actor("a2", "Asha", true, 2), actor("a3", "Actor 003", false, 1)],
  ignored: 1,
  unknown: 0,
  scans: { done: 3, no_faces: 2 },
  message: null,
  run: { engine: "yunet-sface", method: "agglomerative", cluster_distance: 0.6, tracks: 8, corrections_not_found: 2 },
  clustered_at: "2026-10-10T10:00:00Z",
};
const DETAIL = {
  ...actor("a1", "Actor 001", false, 3),
  track_list: [track("t1", "a1"), track("t2", "a1", "pinned", 9, "placed by you"), track("t4", "a1", "pinned", 12, "kept with this person by your correction")],
};
const FACES = {
  media_id: "m1",
  status: "done",
  message: null,
  frames_sampled: 24,
  faces_detected: 30,
  faces_used: 21,
  max_in_frame: 3,
  details: { rejected: { low_score: 4, small: 3, turned: 2, blurry: 0 } },
  tracks: [track("t1", "a1"), track("t3", "a2", "pinned", 6), track("t9", null, "ignored"), track("t8", null, "auto")],
};

interface Call {
  method: string;
  path: string;
  body: unknown;
}

/** Answers by URL; records every request that changes something. */
function backend(overrides: Record<string, unknown> = {}) {
  const calls: Call[] = [];
  const fetcher = vi.fn(async (input: Request | string | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(new URL(String(input), "http://localhost"), init);
    const path = new URL(req.url).pathname;
    if (req.method !== "GET") calls.push({ method: req.method, path, body: await req.json().catch(() => null) });
    for (const [end, answer] of Object.entries(overrides)) {
      if (path.endsWith(end)) return answer instanceof Response ? answer.clone() : Response.json(answer);
    }
    if (path.endsWith("/split")) return Response.json({ ...DETAIL, id: "a9", name: "Actor 009" });
    if (path.endsWith("/merge") || path.startsWith("/api/actors/")) return Response.json(req.method === "PATCH" ? { ...DETAIL, name: "Ravi" } : DETAIL);
    if (path.endsWith("/face-tracks")) return Response.json([track("t9", null, "ignored")]);
    if (path.endsWith("/faces")) return Response.json(FACES);
    return Response.json(OVERVIEW);
  });
  vi.stubGlobal("fetch", fetcher);
  return calls;
}

beforeEach(() => {
  client.setConfig({ baseUrl: "http://localhost" });
  useCurrentProject.setState({ id: "p1" });
  useToasts.setState({ toasts: [] });
});
afterEach(() => {
  vi.unstubAllGlobals();
  useCurrentProject.setState({ id: null });
});

const toasts = () => useToasts.getState().toasts.map((t) => t.message);

function wrap(ui: ReactNode, path = "/actors") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/actors" element={ui} />
          <Route path="/actors/:actorId" element={<ActorPage />} />
          <Route path="*" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("lists people most seen first, says how they were grouped and that groups can be wrong", async () => {
  backend();
  wrap(<ActorsPage />);
  const people = within(await screen.findByRole("list", { name: "People" }));
  expect(people.getAllByRole("listitem").map((li) => within(li).getByRole("link").textContent)).toEqual(["Actor 001", "Asha", "Actor 003"]);
  expect(people.getByText("4 appearances in 2 clips · 0:10")).toBeInTheDocument();
  expect(people.getByRole("link", { name: /Asha/ })).toHaveAttribute("href", "/actors/a2");
  expect(screen.getByText(/Groups can be wrong/)).toHaveTextContent("nothing is matched to real identities");
  const status = screen.getByText(/3 people from 8 appearances/);
  expect(status).toHaveTextContent("3 clips with usable faces out of 5 searched");
  expect(status).toHaveTextContent("Grouped with yunet-sface, agglomerative, distance 0.6");
  expect(status).toHaveTextContent("2 corrections could not be matched to a face any more");
});

it("merges the selected people into the one the user named", async () => {
  const calls = backend();
  wrap(<ActorsPage />);
  await userEvent.click(await screen.findByLabelText("Select Actor 001"));
  expect(screen.queryByRole("region", { name: "Merge" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Select Asha"));
  const bar = within(screen.getByRole("region", { name: "Merge" }));
  await userEvent.click(bar.getByRole("button", { name: "Merge into Asha" }));
  await waitFor(() => expect(calls).toEqual([{ method: "POST", path: "/api/actors/a2/merge", body: { actor_ids: ["a1"] } }]));
  await waitFor(() => expect(screen.queryByRole("region", { name: "Merge" })).not.toBeInTheDocument());
});

it("groups again on request and puts set-aside faces back", async () => {
  const calls = backend();
  wrap(<ActorsPage />);
  await userEvent.click(await screen.findByRole("button", { name: "Group again" }));
  const aside = within(await screen.findByRole("region", { name: "Set aside" }));
  expect(aside.getByText("Not a face")).toBeInTheDocument();
  await userEvent.click(aside.getByRole("button", { name: "Put back the face from picnic.mov" }));
  await waitFor(() =>
    expect(calls).toEqual([
      { method: "POST", path: "/api/projects/p1/actors/regroup", body: null },
      { method: "POST", path: "/api/projects/p1/face-tracks/place", body: { track_ids: ["t9"], state: "auto" } },
    ]),
  );
});

it.each([
  [{ ...OVERVIEW, actors: [], message: "The face models are not downloaded. Run `uv run cinemind models pull` once (needs internet), then press Reprocess.", run: null }, "alert", "uv run cinemind models pull"],
  [{ ...OVERVIEW, actors: [], scans: { no_faces: 4 } }, "status", "0 people"],
])("explains an empty page", async (overview, role, text) => {
  backend({ "/actors": overview, "/face-tracks": [] });
  wrap(<ActorsPage />);
  await waitFor(() => expect(screen.getAllByRole(role).some((el) => el.textContent?.includes(text))).toBe(true));
  expect(screen.queryByRole("list", { name: "People" })).not.toBeInTheDocument();
  if (role === "status") expect(screen.getByText(/faces must be large, sharp and roughly frontal/)).toBeInTheDocument();
});

it("asks for a project first", () => {
  useCurrentProject.setState({ id: null });
  wrap(<ActorsPage />);
  expect(screen.getByText("No project selected")).toBeInTheDocument();
});

it("renames a person and shows where each appearance comes from", async () => {
  const calls = backend();
  wrap(<ActorsPage />, "/actors/a1");
  expect(await screen.findByRole("heading", { name: "Actor 001" })).toBeInTheDocument();
  const items = within(screen.getByRole("list", { name: "Appearances" })).getAllByRole("listitem");
  expect(items).toHaveLength(3);
  expect(items[0]).toHaveAttribute("title", "similar faces · similarity to the group 0.71 · agglomerative, distance 0.6");
  expect(within(items[0]!).getByRole("link", { name: "picnic.mov" })).toHaveAttribute("href", "/library/m1?t=1.5");
  expect(within(items[1]!).getByText("placed by you")).toBeInTheDocument();
  expect(within(items[2]!).getByText("kept by your correction")).toBeInTheDocument();
  const save = screen.getByRole("button", { name: "Save name" });
  expect(save).toBeDisabled();
  await userEvent.clear(screen.getByLabelText("Name"));
  await userEvent.type(screen.getByLabelText("Name"), "Ravi");
  await userEvent.click(save);
  await waitFor(() => expect(calls).toEqual([{ method: "PATCH", path: "/api/actors/a1", body: { name: "Ravi" } }]));
  await waitFor(() => expect(toasts()).toEqual(["Named Ravi."]));
});

it("splits, moves and sets aside the selected appearances", async () => {
  const calls = backend();
  wrap(<ActorsPage />, "/actors/a1");
  const tools = within(await screen.findByRole("region", { name: "Corrections" }));
  const split = tools.getByRole("button", { name: "Split into a new person" });
  expect(split).toBeDisabled();
  await userEvent.click(screen.getByLabelText("Select the appearance in picnic.mov at 0:01.50"));
  await userEvent.click(split);
  await waitFor(() => expect(calls.at(-1)).toEqual({ method: "POST", path: "/api/actors/a1/split", body: { track_ids: ["t1"] } }));
  await waitFor(() => expect(toasts()).toEqual(["Moved to a new person: Actor 009."]));

  await userEvent.click(screen.getByLabelText("Select the appearance in picnic.mov at 0:09.00"));
  expect(tools.getByRole("button", { name: "Move" })).toBeDisabled();
  await userEvent.selectOptions(tools.getByLabelText("Move to"), "Asha");
  await userEvent.click(tools.getByRole("button", { name: "Move" }));
  await waitFor(() =>
    expect(calls.at(-1)).toEqual({ method: "POST", path: "/api/projects/p1/face-tracks/place", body: { track_ids: ["t2"], state: "actor", actor_id: "a2" } }),
  );

  // Everything selected: splitting would leave nobody, the other corrections still work.
  await userEvent.click(tools.getByRole("button", { name: "Select all" }));
  expect(split).toBeDisabled();
  await userEvent.click(tools.getByRole("button", { name: "Not a face" }));
  await waitFor(() => expect(calls.at(-1)?.body).toEqual({ track_ids: ["t1", "t2", "t4"], state: "ignored" }));
  expect(await screen.findByRole("list", { name: "People" })).toBeInTheDocument(); // back on the list
});

it("says so when the person no longer exists", async () => {
  backend({ "/api/actors/gone": Response.json({ code: "not_found", message: "That person no longer exists. Reload the page." }, { status: 404 }) });
  wrap(<ActorsPage />, "/actors/gone");
  expect(await screen.findByRole("alert")).toHaveTextContent("That person no longer exists.");
  expect(screen.getByRole("link", { name: "Back to actors" })).toHaveAttribute("href", "/actors");
});

it("clip page: shows who is in the clip, what was left out, and jumps to an appearance", async () => {
  backend();
  const onSeek = vi.fn();
  wrap(<PeoplePanel mediaId="m1" onSeek={onSeek} />, "/clip");
  const panel = within(await screen.findByRole("region", { name: "People" }));
  expect(panel.getByText(/21 faces used from 24 sampled frames, up to 3 in one frame/)).toHaveTextContent(
    "9 left out as too small, turned, blurred or uncertain; 1 appearance set aside by you; 1 appearance not grouped yet (grouping runs when processing is done). Groups are suggestions.",
  );
  expect(panel.getAllByRole("listitem")).toHaveLength(2);
  expect(panel.getByRole("link", { name: "Asha" })).toHaveAttribute("href", "/actors/a2");
  await userEvent.click(panel.getByRole("button", { name: "Jump to Asha at 0:06.00" }));
  expect(onSeek).toHaveBeenCalledWith(6);
});

it.each([
  ["model_missing", "alert", "The face models are not downloaded. Run `uv run cinemind models pull` once (needs internet), then press Reprocess."],
  ["no_faces", "status", "No usable face was found in this clip."],
  ["pending", "status", "Not searched for faces yet. Processing may still be running; otherwise press Reprocess."],
])("clip page: says why there are no people (%s)", async (status, role, message) => {
  backend({ "/faces": { ...FACES, status, message, tracks: [], faces_used: 0 } });
  wrap(<PeoplePanel mediaId="m1" onSeek={vi.fn()} />, "/clip");
  expect(await screen.findByRole(role)).toHaveTextContent(message);
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
});

it("uses the person's own project and drops a selection that a refresh removed", async () => {
  useCurrentProject.setState({ id: "another" });
  const calls = backend();
  const view = wrap(<ActorsPage />, "/actors/a1");
  const tools = within(await screen.findByRole("region", { name: "Corrections" }));
  await userEvent.click(screen.getByLabelText("Select the appearance in picnic.mov at 0:09.00"));
  expect(tools.getByText("1 selected:")).toBeInTheDocument();
  await userEvent.click(tools.getByRole("button", { name: "Unknown person" }));
  await waitFor(() => expect(calls.at(-1)?.path).toBe("/api/projects/p1/face-tracks/place"));
  expect(calls.every((c) => !c.path.includes("another"))).toBe(true);
  view.unmount();

  // The same page when the selected appearance is gone after a refresh.
  backend({ "/api/actors/a1": { ...DETAIL, track_list: [track("t1", "a1")] } });
  wrap(<ActorsPage />, "/actors/a1");
  const again = within(await screen.findByRole("region", { name: "Corrections" }));
  expect(again.getByRole("button", { name: "Not a face" })).toBeDisabled();
});

it("does not show a distance for a method that has none", async () => {
  backend({ "/actors": { ...OVERVIEW, run: { engine: "yunet-sface", method: "hdbscan", tracks: 8 } }, "/face-tracks": [] });
  wrap(<ActorsPage />);
  const status = await screen.findByText(/3 people from 8 appearances/);
  expect(status).toHaveTextContent("Grouped with yunet-sface, hdbscan.");
  expect(status).not.toHaveTextContent("distance");
});

