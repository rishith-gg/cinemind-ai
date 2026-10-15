import { useCallback, useEffect, useState } from "react";

import type { TimelineItemOut } from "../../api";
import { formatDuration } from "../library/format";

const BROKEN = "A clip could not be played. Its proxy may still be processing or missing.";

/** Load `item` into `el` and seek to its in-point (once per item and range). */
function cue(el: HTMLVideoElement | null, item: TimelineItemOut | undefined) {
  if (!el || !item) return;
  const key = `${item.id}:${item.source_in_s}:${item.source_out_s}`;
  if (el.dataset.cued === key) return;
  el.dataset.cued = key;
  const seek = () => {
    el.currentTime = item.source_in_s;
  };
  if (el.dataset.media !== item.media_id) {
    el.dataset.media = item.media_id;
    el.src = `/api/media/${item.media_id}/stream`;
    el.addEventListener("loadedmetadata", seek, { once: true });
    el.load();
  } else {
    seek();
  }
}

function forget(els: (HTMLVideoElement | null)[]) {
  for (const el of els) {
    el?.pause();
    if (el) delete el.dataset.cued;
  }
}

/** Plays the timeline through the proxies, clip after clip. Two video elements take turns:
 * while one plays, the other has the next clip loaded and seeked to its in-point, so the cut
 * comes without waiting for the next file (sequential playback with pre-seek). */
export function TimelinePlayer({
  items,
  durationS,
  startIndex = 0,
  autoPlay = false,
}: {
  items: TimelineItemOut[];
  durationS: number;
  /** "Play from here" remounts the player (new `key`) with these. */
  startIndex?: number;
  autoPlay?: boolean;
}) {
  // Elements kept in state (not refs) so the effects below re-run once they mount.
  const [first, setFirst] = useState<HTMLVideoElement | null>(null);
  const [second, setSecond] = useState<HTMLVideoElement | null>(null);
  const attach = [useCallback((el: HTMLVideoElement | null) => setFirst(el), []), useCallback((el: HTMLVideoElement | null) => setSecond(el), [])];
  const [front, setFront] = useState(0);
  const [index, setIndex] = useState(startIndex);
  const [playing, setPlaying] = useState(autoPlay);
  const [error, setError] = useState<string | null>(null);
  const startOf = (i: number) => items.slice(0, i).reduce((sum, item) => sum + (item.source_out_s - item.source_in_s), 0);
  const [elapsed, setElapsed] = useState(() => startOf(startIndex));
  const els = front === 0 ? [first, second] : [second, first]; // [showing, waiting]
  const shown = els[0] ?? null;
  const waiting = els[1] ?? null;
  const at = Math.min(index, Math.max(0, items.length - 1));
  const current = items[at];
  const before = startOf(at);

  useEffect(() => {
    cue(shown, items[at]);
    cue(waiting, items[at + 1]);
  }, [shown, waiting, at, items]);

  // While playing, check the clock every frame and cut to the next clip at the out-point.
  useEffect(() => {
    if (!playing || !shown || !current) return;
    const stop = () => {
      setPlaying(false);
      if (shown.error) setError(BROKEN);
    };
    void shown.play().catch(stop);
    let frame = 0;
    const tick = () => {
      setElapsed(before + Math.max(0, shown.currentTime - current.source_in_s));
      // A proxy can end a few milliseconds before the shot's end: ended counts as the out-point.
      const done = shown.ended || shown.currentTime >= current.source_out_s - 0.02;
      // Paused by something else (the browser, a stalled load): try again, else show "Play".
      if (!done && shown.paused && !shown.seeking && shown.readyState >= 2) void shown.play().catch(stop);
      if (done) {
        shown.pause();
        if (at + 1 >= items.length) setPlaying(false);
        else {
          setFront(1 - front);
          setIndex(at + 1);
        }
        return;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, shown, current, before, at, front, items.length]);

  if (!items.length) return <p className="text-sm text-neutral-400">The timeline is empty.</p>;

  const pause = () => {
    shown?.pause();
    setPlaying(false);
  };
  const go = (to: number) => {
    pause();
    setError(null);
    forget([first, second]);
    const target = Math.max(0, Math.min(items.length - 1, to));
    setIndex(target);
    setElapsed(startOf(target));
  };
  const play = () => {
    setError(null);
    // At the end of the timeline, Play starts again from the first clip.
    if (shown && current && at === items.length - 1 && (shown.ended || shown.currentTime >= current.source_out_s - 0.02)) go(0);
    setPlaying(true);
  };

  return (
    <div className="space-y-2">
      <div className="relative aspect-video w-full overflow-hidden rounded bg-black">
        {attach.map((ref, n) => (
          <video
            key={n}
            ref={ref}
            data-testid={n === front ? "timeline-player" : undefined}
            className={`absolute inset-0 h-full w-full ${n === front ? "" : "invisible"}`}
            preload="auto"
            playsInline
            onError={() => {
              if (n !== front) return; // the clip waiting in the background reports when it is shown
              setError(BROKEN);
              setPlaying(false);
            }}
          />
        ))}
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-400">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <button type="button" className="rounded bg-neutral-800 px-3 py-1.5" onClick={() => go(at - 1)} disabled={at === 0}>
          Previous clip
        </button>
        <button type="button" className="rounded bg-blue-600 px-4 py-1.5 font-medium" onClick={() => (playing ? pause() : play())}>
          {playing ? "Pause" : "Play timeline"}
        </button>
        <button type="button" className="rounded bg-neutral-800 px-3 py-1.5" onClick={() => go(at + 1)} disabled={at >= items.length - 1}>
          Next clip
        </button>
        <span className="text-neutral-400" aria-live="polite">
          Clip {at + 1} of {items.length} · {formatDuration(elapsed)} / {formatDuration(durationS)}
        </span>
      </div>
    </div>
  );
}
