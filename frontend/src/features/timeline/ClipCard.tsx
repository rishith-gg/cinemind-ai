import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useState } from "react";

import type { AlternativeOut, TimelineItemOut } from "../../api";
import { formatTime } from "../library/format";
import { LIST_LABEL, SIGNAL_LABEL } from "../search/labels";
import { clampTrim } from "./edits";

type Reason = {
  summary?: string;
  found_by?: Record<string, number>;
  matched_line?: string | null;
  matched_labels?: string[];
  breakdown?: Record<string, { value: number; weight: number; contribution: number }>;
  trim?: { how?: string; detail?: string; lines?: string[] };
};

/** Why the rough cut chose this clip and cut it where it did (stored by the backend). */
function Why({ reason }: { reason: Reason }) {
  return (
    <details className="text-xs text-neutral-300">
      <summary className="cursor-pointer text-neutral-400">Why this clip</summary>
      <div className="mt-2 space-y-1">
        {reason.summary && <p>{reason.summary}</p>}
        {reason.found_by && Object.keys(reason.found_by).length > 0 && (
          <p>
            Found by:{" "}
            {Object.entries(reason.found_by)
              .map(([name, rank]) => `${LIST_LABEL[name] ?? name} #${rank}`)
              .join(", ")}
          </p>
        )}
        {reason.matched_line && <p>Matched line: “{reason.matched_line}”</p>}
        {reason.matched_labels && reason.matched_labels.length > 0 && <p>Matched labels: {reason.matched_labels.join(", ")}</p>}
        {reason.trim?.detail && <p>Trim: {reason.trim.detail}</p>}
        {reason.trim?.lines && reason.trim.lines.length > 0 && <p>Lines kept: {reason.trim.lines.map((l) => `“${l}”`).join(" ")}</p>}
        {reason.breakdown && (
          <table aria-label="Score breakdown" className="mt-1">
            <tbody>
              {Object.entries(reason.breakdown).map(([name, b]) => (
                <tr key={name}>
                  <td className="pr-3">{SIGNAL_LABEL[name] ?? name}</td>
                  <td className="pr-3 tabular-nums">
                    {b.value.toFixed(2)} × {b.weight}
                  </td>
                  <td className="tabular-nums">{b.contribution >= 0 ? `+${b.contribution.toFixed(3)}` : b.contribution.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </details>
  );
}

function TrimSlider({
  label,
  edge,
  item,
  frame,
  onCommit,
}: {
  label: string;
  edge: "in" | "out";
  item: TimelineItemOut;
  frame: number;
  onCommit: (inS: number, outS: number) => void;
}) {
  const saved = edge === "in" ? item.source_in_s : item.source_out_s;
  const [draft, setDraft] = useState<number | null>(null);
  const value = draft ?? saved;
  const commit = () => {
    if (draft === null) return;
    setDraft(null);
    const [inS, outS] = clampTrim(item, edge, draft, frame);
    if (inS !== item.source_in_s || outS !== item.source_out_s) onCommit(inS, outS);
  };
  return (
    <label className="flex items-center gap-2 text-xs">
      <span className="w-14 text-neutral-400">{label}</span>
      <input
        type="range"
        aria-label={label}
        className="flex-1"
        min={0}
        max={item.media_duration_s ?? item.source_out_s}
        step={frame}
        value={value}
        onChange={(e) => setDraft(Number(e.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
      />
      <span className="w-14 text-right tabular-nums">{formatTime(value)}</span>
    </label>
  );
}

export function ClipCard({
  item,
  number,
  frame,
  suggestions,
  busy,
  onTrim,
  onRemove,
  onSwap,
  onPlay,
}: {
  item: TimelineItemOut;
  number: number;
  frame: number;
  suggestions: AlternativeOut[];
  busy: boolean;
  onTrim: (inS: number, outS: number) => void;
  onRemove: () => void;
  onSwap: (shotId: string) => void;
  onPlay: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item.id });
  const reason = (item.reason ?? {}) as Reason;
  const length = item.source_out_s - item.source_in_s;
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      aria-label={`Clip ${number}: ${item.filename}`}
      className={`flex gap-3 rounded border border-neutral-800 bg-neutral-900 p-3 ${isDragging ? "opacity-60" : ""}`}
    >
      <button
        type="button"
        className="cursor-grab self-stretch rounded bg-neutral-800 px-1 text-neutral-400"
        aria-label={`Move clip ${number}`}
        {...attributes}
        {...listeners}
      >
        ⋮⋮
      </button>
      <div className="h-20 w-36 shrink-0 overflow-hidden rounded bg-black">
        {item.keyframe_id && <img src={`/api/keyframes/${item.keyframe_id}/image`} alt="" className="h-full w-full object-cover" loading="lazy" />}
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="truncate text-sm font-medium">
            {number}. {item.filename}{" "}
            <span className="font-normal text-neutral-400">
              {formatTime(item.source_in_s)}–{formatTime(item.source_out_s)} · {length.toFixed(2)} s
              {reason.trim?.how === "speech" ? " · speech" : reason.trim?.how === "by you" ? " · trimmed by you" : ""}
            </span>
          </p>
          <div className="flex gap-2 text-xs">
            <button type="button" className="rounded bg-neutral-800 px-2 py-1" onClick={onPlay}>
              Play from here
            </button>
            <button type="button" className="rounded bg-neutral-800 px-2 py-1 hover:text-red-400" onClick={onRemove} disabled={busy}>
              Remove
            </button>
          </div>
        </div>
        <TrimSlider label="In point" edge="in" item={item} frame={frame} onCommit={onTrim} />
        <TrimSlider label="Out point" edge="out" item={item} frame={frame} onCommit={onTrim} />
        <div className="flex flex-wrap items-center gap-3">
          {suggestions.length > 0 && (
            <select
              aria-label={`Swap clip ${number}`}
              className="max-w-xs rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs"
              value=""
              disabled={busy}
              onChange={(e) => e.target.value && onSwap(e.target.value)}
            >
              <option value="">Swap with a suggestion…</option>
              {suggestions.map((s) => (
                <option key={s.shot_id} value={s.shot_id}>
                  {s.rank ? `#${s.rank} ` : ""}
                  {s.filename} {formatTime(s.start_s)}
                  {s.scene_id && s.scene_id === item.scene_id ? " (same scene)" : ""}
                </option>
              ))}
            </select>
          )}
        </div>
        {item.reason && <Why reason={reason} />}
      </div>
    </li>
  );
}
