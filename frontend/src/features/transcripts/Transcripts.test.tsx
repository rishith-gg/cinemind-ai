import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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

const SPEECH = { languages: ["en", "kn"], detect_only: ["kn"], available: ["en", "hi", "kn", "ta"], queued: 0 };

/** Answers by URL: the search endpoint, the spoken languages, one clip's transcript, else the
 * per-project overview. Records every call (method, path and query, body). */
function backend(search: unknown = HITS, transcript: unknown = TRANSCRIPT, summary: unknown = SUMMARY) {
  const calls: string[] = [];
  const bodies: unknown[] = [];
  const fetcher = vi.fn(async (input: Request | string | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(new URL(String(input), "http://localhost"), init);
    const url = new URL(req.url);
    calls.push(`${req.method === "GET" ? "" : req.method + " "}${url.pathname}${url.search}`);
    if (req.method !== "GET") bodies.push(await req.json().catch(() => null));
    if (url.pathname.endsWith("/search")) return Response.json(search);
    if (url.pathname.endsWith("/speech-languages")) return Response.json(req.method === "PUT" ? { ...SPEECH, ...(bodies.at(-1) as object), queued: 2 } : SPEECH);
    if (url.pathname.endsWith("/speech-language")) return Response.json({ ...(bodies.at(-1) as object), queued: true });
    if (url.pathname.endsWith("/transcript")) return Response.json(transcript);
    return Response.json(summary);
  });
  vi.stubGlobal("fetch", fetcher);
  return Object.assign(calls, { bodies });
}

const panel = (props: Partial<Parameters<typeof TranscriptPanel>[0]> = {}) => (
  <TranscriptPanel mediaId="m1" projectId="p1" clipLanguage={null} time={0} onSeek={vi.fn()} {...props} />
);

it("follows playback: highlights the spoken word, and a click on a word or a time seeks there", async () => {
  backend();
  const onSeek = vi.fn();
  wrap(panel({ time: 1.3, onSeek }));
  const region = within(await screen.findByRole("region", { name: "Transcript" }));
  expect(region.getByText(/English \(93% sure\) · Whisper small · 2 segments/)).toBeInTheDocument();
  const [first] = region.getAllByRole("listitem");
  expect(first).toHaveAttribute("aria-current", "true");
  expect(region.getByRole("button", { name: "camera" })).toHaveClass("bg-blue-600");
  expect(region.getByRole("button", { name: "Hello" })).not.toHaveClass("bg-blue-600");

  await userEvent.click(region.getByRole("button", { name: "rolling." }));
  expect(onSeek).toHaveBeenLastCalledWith(1.7);
  await userEvent.click(region.getByRole("button", { name: "Show them" }));
  await userEvent.click(region.getByRole("button", { name: "forest" }));
  expect(onSeek).toHaveBeenLastCalledWith(5.5);
  await userEvent.click(region.getByRole("button", { name: "Jump to 0:04.00" }));
  expect(onSeek).toHaveBeenLastCalledWith(4);
});

it("hides what the model was unsure about until asked, and says the text is machine-made", async () => {
  backend(HITS, { ...TRANSCRIPT, language_probability: 0.31, language_uncertain: true });
  wrap(panel());
  const region = within(await screen.findByRole("region", { name: "Transcript" }));
  expect(region.getAllByRole("listitem")).toHaveLength(1);
  const notes = region.getAllByRole("note").map((n) => n.textContent);
  expect(notes[0]).toContain("The language was a guess (31% sure)");
  expect(notes[1]).toContain("1 of 2 lines are hidden: the speech model was unsure about them.");
  expect(region.getByText(/Machine transcript; it can be wrong/)).toHaveTextContent("Unsure means the model's own likelihood is under -1");

  await userEvent.click(region.getByRole("button", { name: "Show them" }));
  const [first, second] = region.getAllByRole("listitem") as [HTMLElement, HTMLElement];
  expect(within(second).getByText("uncertain")).toBeInTheDocument();
  expect(within(first).queryByText("uncertain")).not.toBeInTheDocument();
  await userEvent.type(region.getByLabelText("Find in this transcript"), "FOREST");
  expect(region.getAllByRole("listitem")).toHaveLength(1);
  await userEvent.type(region.getByLabelText("Find in this transcript"), "x");
  expect(region.getByText(/Nothing in this transcript contains “FORESTx”/)).toBeInTheDocument();
});

it("says when every line was unsure, and lets the user set the clip's language", async () => {
  const calls = backend(HITS, { ...TRANSCRIPT, segments: TRANSCRIPT.segments.map((s) => ({ ...s, uncertain: true })) });
  wrap(panel());
  const region = within(await screen.findByRole("region", { name: "Transcript" }));
  expect(await region.findByText(/unsure about all 2 lines of this clip, so they are hidden/)).toBeInTheDocument();
  expect(region.queryAllByRole("listitem")).toHaveLength(0);
  const picker = await region.findByRole("combobox");
  expect(within(picker).getByRole("option", { name: "Detect among English, Kannada" })).toBeInTheDocument();
  expect(within(picker).getByRole("option", { name: "Kannada (detect only)" })).toBeInTheDocument();
  await userEvent.selectOptions(picker, "en");
  await waitFor(() => expect(calls).toContain("PUT /api/media/m1/speech-language"));
  expect(calls.bodies).toEqual([{ language: "en" }]);
});

it("shows speech in a detect-only language without text", async () => {
  backend(HITS, { ...TRANSCRIPT, status: "not_written", language: "kn", speech_s: 67.6, segments: [], message: "Speech found in a language set to \"detect only\"." });
  wrap(panel({ clipLanguage: "kn" }));
  const region = within(await screen.findByRole("region", { name: "Transcript" }));
  expect(region.getByText("Kannada speech, 68 s.")).toBeInTheDocument();
  expect(region.getByRole("note")).toHaveTextContent("detect only");
  expect(await region.findByRole("combobox")).toHaveValue("kn");
});

it.each([
  ["model_missing", "The speech model 'small' (487 MB) is not downloaded. Run `uv run cinemind models pull` once (needs internet), then press Reprocess."],
  ["no_speech", "No speech was found in this clip."],
  ["no_audio", "This clip has no audio track."],
  ["pending", "Not transcribed yet. Processing may still be running; otherwise press Reprocess."],
])("says why there is no text (%s)", async (status, message) => {
  backend(HITS, { ...TRANSCRIPT, status, message, language: null, segments: [] });
  wrap(panel());
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
  expect(calls).toContain("/api/projects/p1/transcripts/search?q=forest&include_uncertain=false");
  const hit = results.getByRole("link");
  expect(hit).toHaveAttribute("href", "/library/m1?t=5.5");
  expect(hit).toHaveTextContent("0:05.50 interview.mov");
  expect(within(hit).getByText("forest").tagName).toBe("MARK");
  expect(within(hit).getByText("uncertain")).toBeInTheDocument();

  await userEvent.click(screen.getByLabelText(/Include lines the speech model was unsure about/));
  await waitFor(() => expect(calls).toContain("/api/projects/p1/transcripts/search?q=forest&include_uncertain=true"));
});

it("edits the project's spoken languages and transcribes again", async () => {
  useCurrentProject.setState({ id: "p1" });
  const calls = backend();
  wrap(<TranscriptsPage />);
  const box = within(await screen.findByRole("region", { name: "Spoken languages" }));
  expect(box.getByLabelText("Write transcripts in English")).toBeChecked();
  expect(box.getByLabelText("Write transcripts in Kannada")).not.toBeChecked();
  const save = box.getByRole("button", { name: "Save and transcribe again" });
  expect(save).toBeDisabled();
  await userEvent.selectOptions(box.getByLabelText("Add a spoken language"), "hi");
  await userEvent.click(box.getByLabelText("Write transcripts in Kannada"));
  await userEvent.click(box.getByRole("button", { name: "Remove English" }));
  await userEvent.click(save);
  await waitFor(() => expect(calls).toContain("PUT /api/projects/p1/speech-languages"));
  expect(calls.bodies).toEqual([{ languages: ["kn", "hi"], detect_only: [] }]);
});

it("says when nothing matches, and what to do when the speech model is missing", async () => {
  useCurrentProject.setState({ id: "p1" });
  backend({ query: "zebra crossing", terms: ["zebra", "crossing"], hits: [] });
  wrap(<TranscriptsPage />, "/transcripts?q=zebra%20crossing");
  expect(await screen.findByText(/No transcript contains all of “zebra crossing”/)).toBeInTheDocument();
  expect(screen.getByLabelText("Search transcripts")).toHaveValue("zebra crossing");

  const hint = "The speech model 'small' (487 MB) is not downloaded. Run `uv run cinemind models pull` once (needs internet), then press Reprocess.";
  backend(HITS, TRANSCRIPT, [{ ...SUMMARY[1], status: "model_missing", message: hint }]);
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
