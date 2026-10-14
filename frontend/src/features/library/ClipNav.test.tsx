import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router";
import { afterEach, beforeEach, vi } from "vitest";

import type { MediaOut } from "../../api";
import { client } from "../../api/client.gen";
import { ClipNav } from "./ClipNav";
import { neighbours, useLibraryView } from "./libraryView";

const clip = (id: string, filename: string, quality_score: number | null, qc = 0) =>
  ({ id, filename, quality_score, low_quality: false, qc_flags: Array(qc).fill({}) }) as unknown as MediaOut;
const clips = [clip("a", "c.mov", 0.9), clip("b", "a.mov", 0.2, 1), clip("c", "b.mov", 0.5, 1)];

beforeEach(() => client.setConfig({ baseUrl: "http://localhost" }));
afterEach(() => {
  vi.unstubAllGlobals();
  useLibraryView.setState({ filter: "all", sort: "newest" });
});

it("follows the library's sort and filter", () => {
  expect(neighbours(clips, "a", "all", "newest")).toMatchObject({ previous: null, next: { id: "b" }, position: 1, total: 3 });
  const byName = neighbours(clips, "c", "all", "name");
  expect(byName).toMatchObject({ previous: { id: "b" }, next: { id: "a" }, position: 2 });
  expect(neighbours(clips, "c", "flagged", "newest")).toMatchObject({ previous: { id: "b" }, next: null, total: 2, filtered: true });
});

it("places a clip the filter hides among all clips", () => {
  expect(neighbours(clips, "a", "flagged", "worst")).toMatchObject({ previous: { id: "c" }, next: null, total: 3, filtered: false });
  expect(neighbours(clips, "zzz", "all", "newest")).toBeNull();
});

function Where() {
  const { mediaId = "" } = useParams();
  return (
    <>
      <p>at {mediaId}</p>
      <ClipNav projectId="p1" mediaId={mediaId} />
    </>
  );
}

it("moves to the next and previous clip with the buttons and the N / P keys", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(clips)));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/library/b"]}>
        <Routes>
          <Route path="/library/:mediaId" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("2 of 3")).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Next clip"));
  expect(await screen.findByText("at c")).toBeInTheDocument();
  expect(screen.getByText("Next →")).toHaveAttribute("aria-disabled", "true");
  fireEvent.keyDown(window, { key: "p" });
  expect(await screen.findByText("at b")).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "P" });
  expect(await screen.findByText("at a")).toBeInTheDocument();
});
