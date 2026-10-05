import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, vi } from "vitest";

import { createQueryClient } from "./queryClient";
import { errorMessage } from "./errors";
import { useJobEvents } from "./useJobEvents";

class FakeEventSource {
  static last: FakeEventSource;
  listeners = new Map<string, (e: Event) => void>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeEventSource.last = this;
  }
  addEventListener(t: string, fn: (e: Event) => void) {
    this.listeners.set(t, fn);
  }
  close() {
    this.closed = true;
  }
}

afterEach(() => vi.unstubAllGlobals());

it("connects, forwards events and closes on unmount", () => {
  vi.stubGlobal("EventSource", FakeEventSource);
  const seen: string[] = [];
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={createQueryClient()}>{children}</QueryClientProvider>
  );
  const onEvent = (e: { type: string }) => seen.push(e.type);
  const { result, unmount } = renderHook(() => useJobEvents(onEvent), { wrapper });
  const es = FakeEventSource.last;
  expect(es.url).toBe("/api/jobs/events");
  act(() => es.onopen?.());
  expect(result.current.connected).toBe(true);
  act(() =>
    es.listeners.get("stage")?.(new MessageEvent("stage", { data: JSON.stringify({ job_id: "j", type: "stage", data: {} }) })),
  );
  expect(seen).toEqual(["stage"]);
  unmount();
  expect(es.closed).toBe(true);
});

it("turns errors into plain language", () => {
  expect(errorMessage({ code: "not_found", message: "Gone." })).toBe("Gone.");
  expect(errorMessage(new TypeError("fetch failed"))).toMatch(/Can't reach/);
  expect(errorMessage({ detail: [{}] })).toMatch(/not valid/);
  expect(errorMessage(null)).toMatch(/Something went wrong/);
});

it("keeps one EventSource when the caller passes a new callback each render", () => {
  let created = 0;
  class Counting extends FakeEventSource {
    constructor(url: string) {
      super(url);
      created++;
    }
  }
  vi.stubGlobal("EventSource", Counting);
  const qc = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const { rerender } = renderHook(() => useJobEvents(() => undefined), { wrapper });
  rerender();
  rerender();
  expect(created).toBe(1);
});
