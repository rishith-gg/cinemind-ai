import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useNavigate } from "react-router";

import { listMediaOptions } from "../../api/@tanstack/react-query.gen";
import { FILTERS, neighbours, useLibraryView } from "./libraryView";
import { isTyping } from "./playerKeys";

const LINK = "rounded bg-neutral-800 px-3 py-1.5 text-sm hover:bg-neutral-700";
const OFF = "rounded bg-neutral-900 px-3 py-1.5 text-sm text-neutral-600";

/** Previous / Next clip in the library's current filter and sort, plus the P and N keys, so
 * the user can go through the footage without returning to the grid. */
export function ClipNav({ projectId, mediaId }: { projectId: string; mediaId: string }) {
  const navigate = useNavigate();
  const { filter, sort } = useLibraryView();
  const { data } = useQuery(listMediaOptions({ path: { project_id: projectId } }));
  const near = data ? neighbours(data, mediaId, filter, sort) : null;
  const previous = near?.previous?.id;
  const next = near?.next?.id;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      const key = e.key.toLowerCase();
      const target = key === "n" ? next : key === "p" ? previous : undefined;
      if (!target) return;
      e.preventDefault();
      void navigate(`/library/${target}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate, previous, next]);

  if (!near) return null;
  return (
    <nav aria-label="Clips" className="flex items-center gap-2">
      {near.previous ? (
        <Link className={LINK} to={`/library/${near.previous.id}`} title={`${near.previous.filename} (P)`} aria-label="Previous clip">
          ← Previous
        </Link>
      ) : (
        <span className={OFF} aria-disabled="true">
          ← Previous
        </span>
      )}
      <span className="text-xs text-neutral-400" title={near.filtered ? `Only clips shown by the library filter: ${FILTERS[filter].label}` : undefined}>
        {near.position} of {near.total}
        {near.filtered ? " (filtered)" : ""}
      </span>
      {near.next ? (
        <Link className={LINK} to={`/library/${near.next.id}`} title={`${near.next.filename} (N)`} aria-label="Next clip">
          Next →
        </Link>
      ) : (
        <span className={OFF} aria-disabled="true">
          Next →
        </span>
      )}
    </nav>
  );
}
