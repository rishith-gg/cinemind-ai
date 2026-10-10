import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { client } from "../../api/client.gen";
import { useCurrentProject } from "../../lib/currentProject";
import { languageName } from "./labels";
import { TranscriptPanel } from "./TranscriptPanel";
import { TranscriptsPage } from "./TranscriptsPage";

const word = (w: string, start_s: number, probability = 0.9) => ({ word: w, start_s, end_s: start_s + 0.4, probability });
const segment = (id: number, start_s: number, words: ReturnType<typeof word>[], uncertain = false) => ({
  id,
  index: id - 1,
  start_s,
  end_s: words.at(-1)?.end_s ?? start_s,
  text: words.map((w) => w.word).join(" "),
  confidence: 0.8,
  avg_logprob: uncertain ? -1.4 : -0.3,
  no_speech_prob: 0.1,
  compression_ratio: 1.2,
  uncertain,
  words,
});
const TRANSCRIPT = {
  media_id: "m1",
  status: "done",
  message: null,
  language: "en",
  language_probability: 0.93,
  language_uncertain: false,
  model: "small",
  model_revision: "536b",
  speech_s: 6,
  details: {},
  thresholds: { uncertain_logprob_below: -1, uncertain_compression_above: 2.4, uncertain_language_below: 0.5 },
  segments: [
    segment(1, 0.2, [word("Hello", 0.2), word("there,", 0.7), word("camera", 1.2), word("rolling.", 1.7)]),
    segment(2, 4, [word("Walking", 4, 0.3), word("towards", 4.5), word("the", 5), word("forest", 5.5)], true),
  ],
};
const SUMMARY = [
  { media_id: "m1", filename: "interview.mov", duration_s: 12, status: "done", message: null, language: "en", speech_s: 6, segments: 2, words: 8 },
  { media_id: "m2", filename: "waves.mov", duration_s: 30, status: "no_speech", message: "No speech was found in this clip.", language: null, speech_s: 0, segments: 0, words: 0 },
];
const HITS = {
  query: "forest",
  terms: ["forest"],
  hits: [
    {
      segment_id: 2,
      media_id: "m1",
      filename: "interview.mov",
      start_s: 4,
      end_s: 5.9,
      jump_s: 5.5,
      parts: [
        { text: "Walking towards the ", match: false },
        { text: "forest", match: true },
      ],
      uncertain: true,
      rank: -1.2,
    },
  ],
};

beforeEach(() => client.setConfig({ baseUrl: "http://localhost" }));
afterEach(() => {
  vi.unstubAllGlobals();
  useCurrentProject.setState({ id: null });
});

function wrap(ui: ReactNode, path = "/transcripts") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Answers by URL: the search endpoint, else the per-project overview. */
function backend(search: unknown = HITS) {
  const calls: string[] = [];
  const fetcher = vi.fn(async (input: Request | string | URL) => {
    const url = new URL(input instanceof Request ? input.url : String(input), "http://localhost");
    calls.push(url.pathname + url.search);
    return Response.json(url.pathname.endsWith("/search") ? search : SUMMARY);
  });
  vi.stubGlobal("fetch", fetcher);
  return calls;
}

it("follows playback: highlights the spoken word, and a click on a word or a time seeks there", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(TRANSCRIPT)));
  const onSeek = vi.fn();
  wrap(<TranscriptPanel mediaId="m1" time={1.3} onSeek={onSeek} />);
  const panel = within(await screen.findByRole("region", { name: "Transcript" }));
  expect(panel.getByText(/English \(93% sure\) · Whisper small · 2 segments/)).toBeInTheDocument();
  const [first, second] = panel.getAllByRole("listitem");
  expect(first).toHaveAttribute("aria-current", "true");
  expect(second).not.toHaveAttribute("aria-current");
  expect(panel.getByRole("button", { name: "camera" })).toHaveClass("bg-blue-600");
  expect(panel.getByRole("button", { name: "Hello" })).not.toHaveClass("bg-blue-600");

  await userEvent.click(panel.getByRole("button", { name: "forest" }));
  expect(onSeek).toHaveBeenLastCalledWith(5.5);
  await userEvent.click(panel.getByRole("button", { name: "Jump to 0:04.00" }));
  expect(onSeek).toHaveBeenLastCalledWith(4);
});

it("marks what the model was unsure about and says the text is machine-made", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...TRANSCRIPT, language_probability: 0.31, language_uncertain: true })));
  wrap(<TranscriptPanel mediaId="m1" time={0} onSeek={vi.fn()} />);
  const panel = within(await screen.findByRole("region", { name: "Transcript" }));
  const [first, second] = panel.getAllByRole("listitem") as [HTMLElement, HTMLElement];
  expect(within(second).getByText("uncertain")).toBeInTheDocument();
  expect(within(first).queryByText("uncertain")).not.toBeInTheDocument();
  expect(panel.getByRole("note")).toHaveTextContent("The language was a guess (31% sure)");
  expect(panel.getByText(/Machine transcript; it can be wrong/)).toHaveTextContent("1 of 2 segments are marked uncertain");

  await userEvent.type(panel.getByLabelText("Find in this transcript"), "FOREST");
  expect(panel.getAllByRole("listitem")).toHaveLength(1);
  await userEvent.type(panel.getByLabelText("Find in this transcript"), "x");
  expect(panel.getByText(/Nothing in this transcript contains “FORESTx”/)).toBeInTheDocument();
});

it.each([
  ["model_missing", "The speech model 'small' (487 MB) is not downloaded. Run `uv run cinemind models pull` once (needs internet), then press Reprocess."],
  ["no_speech", "No speech was found in this clip."],
  ["no_audio", "This clip has no audio track."],
  ["pending", "Not transcribed yet. Processing may still be running; otherwise press Reprocess."],
])("says why there is no text (%s)", async (status, message) => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...TRANSCRIPT, status, message, language: null, segments: [] })));
  wrap(<TranscriptPanel mediaId="m1" time={0} onSeek={vi.fn()} />);
  expect(await screen.findByRole("note")).toHaveTextContent(message);
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
});

it("searches the project's transcripts and links each hit to the moment the word is spoken", async () => {
  useCurrentProject.setState({ id: "p1" });
  const calls = backend();
  wrap(<TranscriptsPage />);
  const table = within(await screen.findByRole("table"));
  expect(table.getByRole("row", { name: /interview\.mov Transcribed English 0:06 of 0:12 8/ })).toBeInTheDocument();
  expect(table.getByRole("row", { name: /waves\.mov No speech found – – –/ })).toBeInTheDocument();
  expect(screen.queryByRole("list", { name: "Search results" })).not.toBeInTheDocument();

  await userEvent.type(screen.getByLabelText("Search transcripts"), " forest ");
  await userEvent.click(screen.getByRole("button", { name: "Search" }));
  const results = within(await screen.findByRole("list", { name: "Search results" }));
  expect(calls).toContain("/api/projects/p1/transcripts/search?q=forest");
  const hit = results.getByRole("link");
  expect(hit).toHaveAttribute("href", "/library/m1?t=5.5");
  expect(hit).toHaveTextContent("0:05.50 interview.mov");
  expect(within(hit).getByText("forest").tagName).toBe("MARK");
  expect(within(hit).getByText("uncertain")).toBeInTheDocument();
});

it("says when nothing matches, and what to do when the speech model is missing", async () => {
  useCurrentProject.setState({ id: "p1" });
  backend({ query: "zebra crossing", terms: ["zebra", "crossing"], hits: [] });
  wrap(<TranscriptsPage />, "/transcripts?q=zebra%20crossing");
  expect(await screen.findByText(/No transcript contains all of “zebra crossing”/)).toBeInTheDocument();
  expect(screen.getByLabelText("Search transcripts")).toHaveValue("zebra crossing");

  const hint = "The speech model 'small' (487 MB) is not downloaded. Run `uv run cinemind models pull` once (needs internet), then press Reprocess.";
  vi.stubGlobal("fetch", vi.fn(async () => Response.json([{ ...SUMMARY[1], status: "model_missing", message: hint }])));
  wrap(<TranscriptsPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("cinemind models pull");
  expect(screen.getAllByText("Speech model not downloaded").length).toBeGreaterThan(0);
});

it("asks for a project first, and names languages", () => {
  wrap(<TranscriptsPage />);
  expect(screen.getByText("No project selected")).toBeInTheDocument();
  expect(languageName("kn")).toBe("Kannada");
  expect(languageName(null)).toBe("unknown");
  expect(languageName("not a code")).toBe("not a code");
});
