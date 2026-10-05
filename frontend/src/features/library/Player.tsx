import { useCallback, useEffect, useRef, useState } from "react";

import type { MediaOut } from "../../api";
import { handlePlayerKey, type PlayerState } from "./playerKeys";
import { Waveform } from "./Waveform";

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
}

/** Proxy player with editor shortcuts (Space/K/L/J, arrows = frame step, I/O marks), a
 * thumbnail strip (click to seek) and the waveform. Always plays the browser-safe proxy. */
export function Player({ media }: { media: MediaOut }) {
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const [time, setTime] = useState(0);
  const [marks, setMarks] = useState<{ in?: number; out?: number }>({});
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const state = useRef<PlayerState>({ speedIndex: 0 });
  const fps = media.fps_num && media.fps_den ? media.fps_num / media.fps_den : 25;
  const duration = media.duration_s ?? 0;

  useEffect(() => {
    if (!video) return;
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      const handled = handlePlayerKey(e, video, fps, state.current, {
        onIn: (t) => setMarks((m) => ({ ...m, in: t })),
        onOut: (t) => setMarks((m) => ({ ...m, out: t })),
      });
      if (handled) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [video, fps]);

  // Stable callback ref: an inline one would re-fire (null, then element) on every render.
  const attachVideo = useCallback((el: HTMLVideoElement | null) => {
    videoRef.current = el;
    setVideo(el); // state copy so the shortcuts/waveform effects re-run when it mounts
  }, []);

  const seekToFraction = (fraction: number) => {
    if (videoRef.current) videoRef.current.currentTime = Math.min(1, Math.max(0, fraction)) * duration;
  };

  return (
    <div className="space-y-3">
      <video
        ref={attachVideo}
        data-testid="player"
        className="aspect-video w-full rounded bg-black"
        src={`/api/media/${media.id}/stream`}
        poster={media.has_poster ? `/api/media/${media.id}/poster` : undefined}
        controls
        preload="metadata"
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
      />
      <p className="font-mono text-xs text-neutral-400" aria-live="off">
        {time.toFixed(2)} s · frame {Math.round(time * fps)}
        {marks.in !== undefined && ` · in ${marks.in.toFixed(2)}`}
        {marks.out !== undefined && ` · out ${marks.out.toFixed(2)}`}
      </p>
      {media.has_strip && (
        <button
          type="button"
          aria-label="Thumbnail strip: click to seek"
          className="block h-[90px] w-full overflow-hidden rounded"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            seekToFraction((e.clientX - r.left) / r.width);
          }}
        >
          <img src={`/api/media/${media.id}/strip`} alt="" className="h-full w-full object-fill" />
        </button>
      )}
      {media.has_waveform && <Waveform mediaId={media.id} video={video} />}
      <p className="text-xs text-neutral-500">
        Keys: Space/K play·pause · L play (again = faster) · J back 1 s · ←/→ one frame (Shift: 1 s) · I/O mark
      </p>
    </div>
  );
}
