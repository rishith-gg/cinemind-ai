import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { item } from "./testItems";
import { TimelinePlayer } from "./TimelinePlayer";

const items = [item("a", 0, 2), item("b", 4, 6, { media_id: "m2" })];

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => setTimeout(() => cb(0), 5));
  vi.stubGlobal("cancelAnimationFrame", (id: number) => clearTimeout(id));
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** jsdom does not play media: say the visible clip has run to its end. */
function endShownClip() {
  Object.defineProperty(screen.getByTestId("timeline-player"), "ended", { value: true, configurable: true });
}

/** A real element is no longer ended once it seeks back (the override above stays otherwise). */
function rewindAll() {
  for (const v of document.querySelectorAll("video")) Object.defineProperty(v, "ended", { value: false, configurable: true });
}

it("cuts to the next clip when the proxy ends before the out-point, and starts over at the end", async () => {
  render(<TimelinePlayer items={items} durationS={4} />);
  expect(screen.getByText(/Clip 1 of 2/)).toBeInTheDocument();
  const firstVideo = screen.getByTestId("timeline-player");
  await userEvent.click(screen.getByRole("button", { name: "Play timeline" }));
  endShownClip();
  expect(await screen.findByText(/Clip 2 of 2/)).toBeInTheDocument();
  expect(screen.getByTestId("timeline-player")).not.toBe(firstVideo); // the pre-seeked element
  expect(screen.getByTestId("timeline-player").getAttribute("src")).toBe("/api/media/m2/stream");

  endShownClip();
  expect(await screen.findByRole("button", { name: "Play timeline" })).toBeInTheDocument();
  expect(screen.getByText(/Clip 2 of 2/)).toBeInTheDocument();
  // Play at the end starts over from the first clip (a real element stops being "ended" there).
  const playAgain = screen.getByRole("button", { name: "Play timeline" });
  const shown = screen.getByTestId("timeline-player");
  Object.defineProperty(shown, "ended", { value: true, configurable: true });
  fireEvent.click(playAgain);
  rewindAll();
  expect(await screen.findByText(/Clip 1 of 2/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
});

it("reports a broken clip only when it is the one shown", async () => {
  render(<TimelinePlayer items={items} durationS={4} />);
  const hidden = document.querySelector("video.invisible")!;
  fireEvent.error(hidden);
  expect(screen.queryByRole("alert")).toBeNull();
  fireEvent.error(screen.getByTestId("timeline-player"));
  expect(screen.getByRole("alert")).toHaveTextContent("could not be played");
  await userEvent.click(screen.getByRole("button", { name: "Next clip" }));
  expect(screen.queryByRole("alert")).toBeNull();
});
