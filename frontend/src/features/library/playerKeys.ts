const SPEEDS = [1, 2, 4];

/** True while the user types in a field, so single-letter shortcuts stay out of the way. */
export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
}

export interface PlayerState {
  speedIndex: number;
}

/** Editor-style shortcuts for the proxy player. Returns true when the key was handled.
 * Space/K play-pause, L play (again = faster), J step back 1 s, arrows step one frame
 * (Shift: 1 s), I/O are reported through the callbacks for marking in/out. */
export function handlePlayerKey(
  e: Pick<KeyboardEvent, "key" | "shiftKey">,
  video: HTMLVideoElement,
  fps: number,
  state: PlayerState,
  marks?: { onIn?: (t: number) => void; onOut?: (t: number) => void },
): boolean {
  const frame = 1 / (fps > 0 ? fps : 25);
  const seek = (delta: number) => {
    video.pause();
    video.currentTime = Math.min(video.duration || Infinity, Math.max(0, video.currentTime + delta));
  };
  switch (e.key.toLowerCase()) {
    case " ":
      if (video.paused) void video.play();
      else video.pause();
      state.speedIndex = 0;
      video.playbackRate = 1;
      return true;
    case "k":
      video.pause();
      state.speedIndex = 0;
      video.playbackRate = 1;
      return true;
    case "l":
      if (video.paused) state.speedIndex = 0;
      else state.speedIndex = Math.min(SPEEDS.length - 1, state.speedIndex + 1);
      video.playbackRate = SPEEDS[state.speedIndex] ?? 1;
      void video.play();
      return true;
    case "j":
      seek(-1);
      return true;
    case "arrowleft":
      seek(e.shiftKey ? -1 : -frame);
      return true;
    case "arrowright":
      seek(e.shiftKey ? 1 : frame);
      return true;
    case "i":
      marks?.onIn?.(video.currentTime);
      return true;
    case "o":
      marks?.onOut?.(video.currentTime);
      return true;
    default:
      return false;
  }
}
