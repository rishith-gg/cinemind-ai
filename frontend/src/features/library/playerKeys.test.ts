import { vi } from "vitest";

import { handlePlayerKey, type PlayerState } from "./playerKeys";

function fakeVideo(over: Partial<HTMLVideoElement> = {}) {
  const v = {
    paused: true,
    currentTime: 10,
    duration: 100,
    playbackRate: 1,
    pause: vi.fn(function (this: { paused: boolean }) {
      this.paused = true;
    }),
    play: vi.fn(function (this: { paused: boolean }) {
      this.paused = false;
      return Promise.resolve();
    }),
    ...over,
  };
  return v as unknown as HTMLVideoElement;
}

const key = (k: string, shiftKey = false) => ({ key: k, shiftKey });

it("steps exactly one frame at the clip frame rate", () => {
  const v = fakeVideo();
  const st: PlayerState = { speedIndex: 0 };
  handlePlayerKey(key("ArrowRight"), v, 25, st);
  expect(v.currentTime).toBeCloseTo(10.04);
  handlePlayerKey(key("ArrowLeft"), v, 25, st);
  expect(v.currentTime).toBeCloseTo(10);
  handlePlayerKey(key("ArrowRight", true), v, 25, st);
  expect(v.currentTime).toBeCloseTo(11);
});

it("never seeks before the start or past the end", () => {
  const v = fakeVideo({ currentTime: 0.01 });
  handlePlayerKey(key("j"), v, 25, { speedIndex: 0 });
  expect(v.currentTime).toBe(0);
});

it("space toggles, L speeds up while playing, K stops and resets speed", () => {
  const v = fakeVideo();
  const st: PlayerState = { speedIndex: 0 };
  handlePlayerKey(key(" "), v, 25, st);
  expect(v.paused).toBe(false);
  handlePlayerKey(key("l"), v, 25, st);
  expect(v.playbackRate).toBe(2);
  handlePlayerKey(key("k"), v, 25, st);
  expect(v.paused).toBe(true);
  expect(v.playbackRate).toBe(1);
});

it("reports in/out marks and ignores other keys", () => {
  const onIn = vi.fn();
  const v = fakeVideo({ currentTime: 3.5 });
  expect(handlePlayerKey(key("i"), v, 25, { speedIndex: 0 }, { onIn })).toBe(true);
  expect(onIn).toHaveBeenCalledWith(3.5);
  expect(handlePlayerKey(key("q"), v, 25, { speedIndex: 0 })).toBe(false);
});
