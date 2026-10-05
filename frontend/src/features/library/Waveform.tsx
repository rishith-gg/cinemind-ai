import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import WaveSurfer from "wavesurfer.js";

import { getWaveformOptions } from "../../api/@tanstack/react-query.gen";

interface WaveformData {
  duration: number;
  peaks: number[];
}

function isWaveform(x: unknown): x is WaveformData {
  const w = x as WaveformData | null;
  return !!w && typeof w.duration === "number" && Array.isArray(w.peaks);
}

/** Waveform drawn from the precomputed peaks (no audio decoding in the browser), synced with
 * the player element: clicking it seeks the video. */
export function Waveform({ mediaId, video }: { mediaId: string; video: HTMLMediaElement | null }) {
  const box = useRef<HTMLDivElement>(null);
  const { data } = useQuery(getWaveformOptions({ path: { media_id: mediaId } }));
  const wave = isWaveform(data) ? data : null;

  useEffect(() => {
    if (!wave || !video || !box.current) return;
    const ws = WaveSurfer.create({
      container: box.current,
      media: video,
      peaks: [wave.peaks],
      duration: wave.duration,
      height: 64,
      waveColor: "#525252",
      progressColor: "#3b82f6",
      cursorColor: "#f5f5f5",
      barWidth: 2,
    });
    return () => ws.destroy();
  }, [wave, video]);

  if (!wave) return null;
  return <div ref={box} aria-label="Audio waveform" data-testid="waveform" className="rounded bg-neutral-900 p-2" />;
}
