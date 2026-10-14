import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";

import type { MediaOut } from "../../api";
import { QcLane } from "../quality/QcLane";
import { ShotStrip } from "../shots/ShotStrip";
import { PeoplePanel } from "../actors/PeoplePanel";
import { TagsPanel } from "../tags/TagsPanel";
import { TranscriptPanel } from "../transcripts/TranscriptPanel";
import { handlePlayerKey, type PlayerState } from "./playerKeys";
import { Waveform } from "./Waveform";

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
}

/** Proxy player with editor shortcuts (Space/K/L/J, arrows = frame step, I/O marks), a
 * thumbnail strip (click to seek), the shot strip, the waveform and the transcript following
 * playback. Always plays the browser-safe proxy. */
export function Player({ media }: { media: MediaOut }) {
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const [time, setTime] = useState(0);
  const [marks, setMarks] = useState<{ in?: number; out?: number }>({});
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const state = useRef<PlayerState>({ speedIndex: 0 });
  const fps = media.fps_num && media.fps_den ? media.fps_num / media.fps_den : 25;
  const duration = media.duration_s ?? 0;
  // `?t=12.5` opens the clip at that second (links from the Shots page).
  const [params] = useSearchParams();
  const startAt = Number(params.get("t")) || 0;

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

  const seekTo = (seconds: number) => {
    if (videoRef.current) videoRef.current.currentTime = Math.max(0, seconds);
  };
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
        onLoadedMetadata={(e) => {
          if (startAt > 0) e.currentTarget.currentTime = startAt;
        }}
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
      {duration > 0 && !!media.width && <ShotStrip mediaId={media.id} duration={duration} time={time} onSeek={(t) => seekToFraction(t / duration)} />}
      <QcLane mediaId={media.id} duration={duration} onSeek={(t) => seekToFraction(t / duration)} />
      {media.has_waveform && <Waveform mediaId={media.id} video={video} />}
      {media.probed && !!media.width && <PeoplePanel mediaId={media.id} onSeek={seekTo} />}
      {media.probed && !!media.width && <TagsPanel mediaId={media.id} time={time} onSeek={seekTo} />}
      {media.probed && <TranscriptPanel mediaId={media.id} time={time} onSeek={seekTo} />}
      <p className="text-xs text-neutral-500">
        Keys: Space/K play·pause · L play (again = faster) · J back 1 s · ←/→ one frame (Shift: 1 s) · I/O mark
      </p>
    </div>
  );
}
