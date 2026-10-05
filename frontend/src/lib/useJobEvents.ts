import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { getJobQueryKey } from "../api/@tanstack/react-query.gen";

export interface JobEvent {
  job_id: string;
  type: string;
  data: Record<string, unknown>;
}

/** Subscribe to the backend's SSE stream (`/api/jobs/events`). Newer events only; the browser
 * reconnects by itself and resends Last-Event-ID, so nothing is missed. Job queries are
 * invalidated on each event so job views refresh. */
export function useJobEvents(onEvent?: (e: JobEvent) => void): { connected: boolean } {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent; // callers may pass an inline function without resubscribing
  });

  useEffect(() => {
    if (typeof EventSource === "undefined") return; // e.g. jsdom
    const source = new EventSource("/api/jobs/events");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    const handle = (raw: Event) => {
      let e: JobEvent;
      try {
        e = JSON.parse((raw as MessageEvent<string>).data) as JobEvent;
      } catch {
        console.warn("Ignoring malformed job event", raw);
        return;
      }
      void qc.invalidateQueries({ queryKey: getJobQueryKey({ path: { job_id: e.job_id } }) });
      handler.current?.(e);
    };
    const types = ["queued", "started", "stage", "progress", "cancel_requested", "succeeded", "failed", "cancelled"];
    types.forEach((t) => source.addEventListener(t, handle));
    return () => source.close();
  }, [qc]);

  return { connected };
}
