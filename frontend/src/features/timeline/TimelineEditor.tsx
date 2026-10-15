import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import type { TimelineDetail, TimelineItemOut } from "../../api";
import {
  getTimelineOptions,
  getTimelineQueryKey,
  listTimelinesQueryKey,
  swapTimelineItemMutation,
  updateTimelineMutation,
} from "../../api/@tanstack/react-query.gen";
import { ErrorState, Loading } from "../../components/states";
import { downloadExport, EXPORT_FORMATS } from "../../lib/download";
import { errorMessage } from "../../lib/errors";
import { toast } from "../../lib/toast";
import { formatDuration, rateLabel } from "../library/format";
import { ClipCard } from "./ClipCard";
import { frameSeconds, moveItem, suggestionsFor, toEdits, withItems } from "./edits";
import { TimelinePlayer } from "./TimelinePlayer";

type LeftOut = { shot_id: string; filename: string; start_s: number; why: string };

function BuildNotes({ timeline }: { timeline: TimelineDetail }) {
  const p = timeline.params;
  const understood = (p.understood as string[] | undefined) ?? [];
  const leftOut = (p.left_out as LeftOut[] | undefined) ?? [];
  const target = p.target_s as number | undefined;
  return (
    <div className="space-y-1 text-sm text-neutral-300">
      {typeof p.brief === "string" && (
        <p>
          Brief: “{p.brief}” <span className="text-neutral-400">· read as {understood.join(" · ")}</span>
        </p>
      )}
      <p className="text-neutral-400">
        {timeline.item_count} clips · {formatDuration(timeline.duration_s)}
        {target ? ` (asked for ${formatDuration(target)})` : ""} · {rateLabel(timeline.fps_num, timeline.fps_den)} fps ·{" "}
        {timeline.width}×{timeline.height}
        {typeof p.order === "string" ? ` · order: ${p.order}` : ""}
        {typeof p.candidates === "number" ? ` · ${p.candidates} candidates considered` : ""}
        {typeof p.built_s === "number" ? ` · built in ${p.built_s.toFixed(1)} s` : ""}
      </p>
      {leftOut.length > 0 && (
        <details>
          <summary className="cursor-pointer text-neutral-400">{leftOut.length} matching shot(s) left out</summary>
          <ul className="mt-1 list-disc pl-5 text-xs">
            {leftOut.map((l) => (
              <li key={l.shot_id}>
                {l.filename} at {l.start_s.toFixed(2)} s: {l.why}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Editor({ timeline }: { timeline: TimelineDetail }) {
  const qc = useQueryClient();
  const key = getTimelineQueryKey({ path: { timeline_id: timeline.id } });
  const [name, setName] = useState(timeline.name);
  const [startAt, setStartAt] = useState({ index: 0, nonce: 0 });
  const settle = (t: TimelineDetail) => {
    qc.setQueryData(key, t);
    void qc.invalidateQueries({ queryKey: listTimelinesQueryKey({ path: { project_id: t.project_id } }) });
  };
  const fail = (e: unknown) => {
    toast.error(errorMessage(e));
    void qc.invalidateQueries({ queryKey: key });
  };
  // Each edit sends the whole item list: one at a time (same scope), so replies cannot arrive
  // out of order and put an older list back.
  const scope = { id: `timeline-${timeline.id}` };
  const update = useMutation({ ...updateTimelineMutation(), scope, onSuccess: settle, onError: fail });
  const swap = useMutation({ ...swapTimelineItemMutation(), scope, onSuccess: settle, onError: fail });
  const busy = update.isPending || swap.isPending;
  const frame = frameSeconds(timeline);
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));

  const save = (items: TimelineItemOut[]) => {
    qc.setQueryData(key, withItems(timeline, items)); // optimistic; the reply replaces it
    update.mutate({ path: { timeline_id: timeline.id }, body: { items: toEdits(items) } });
  };
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const from = timeline.items.findIndex((i) => i.id === active.id);
    const to = timeline.items.findIndex((i) => i.id === over.id);
    if (from >= 0 && to >= 0) save(moveItem(timeline.items, from, to));
  };

  return (
    <section className="mx-auto max-w-5xl space-y-5">
      <p className="text-sm">
        <Link className="text-neutral-400 underline" to="/timeline">
          ← Rough cuts
        </Link>
      </p>
      {typeof timeline.params.banner === "string" && (
        <p role="note" className="rounded border border-amber-700 bg-amber-950 px-3 py-2 text-sm font-medium text-amber-200">
          {timeline.params.banner}
        </p>
      )}
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim() && name.trim() !== timeline.name)
            update.mutate({ path: { timeline_id: timeline.id }, body: { name: name.trim() } });
        }}
      >
        <input
          aria-label="Timeline name"
          className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-lg font-semibold"
          value={name}
          maxLength={200}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="rounded bg-neutral-800 px-3 py-1.5 text-sm" disabled={busy || name.trim() === timeline.name}>
          Rename
        </button>
      </form>
      <BuildNotes timeline={timeline} />
      {timeline.warnings.map((w) => (
        <p key={w} role="note" className="rounded border border-amber-800 bg-amber-950 p-2 text-sm">
          {w}
        </p>
      ))}

      <TimelinePlayer
        key={startAt.nonce}
        items={timeline.items}
        durationS={timeline.duration_s}
        startIndex={startAt.index}
        autoPlay={startAt.nonce > 0}
      />

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-neutral-400">Export:</span>
        {timeline.formats.map((f) => (
          <button key={f} type="button" className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium" onClick={() => void downloadExport(timeline.id, f)}>
            Download {EXPORT_FORMATS[f] ?? f}
          </button>
        ))}
      </div>
      <p className="text-xs text-neutral-500">
        Files are also saved in <code>{timeline.export_dir}</code> and point at your original footage. Each clip carries a marker
        saying why it was chosen. Subtitles (SRT) use only transcript lines that are not marked uncertain and start at 00:00:00.
      </p>

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={timeline.items.map((i) => i.id)} strategy={verticalListSortingStrategy}>
          <ol aria-label="Timeline clips" className="space-y-2">
            {timeline.items.map((item, n) => (
              <ClipCard
                key={item.id}
                item={item}
                number={n + 1}
                frame={frame}
                busy={busy}
                suggestions={suggestionsFor(item, timeline.alternatives ?? [])}
                onTrim={(inS, outS) =>
                  save(timeline.items.map((i) => (i.id === item.id ? { ...i, source_in_s: inS, source_out_s: outS } : i)))
                }
                onRemove={() => save(timeline.items.filter((i) => i.id !== item.id))}
                onSwap={(shotId) => swap.mutate({ path: { timeline_id: timeline.id, item_id: item.id }, body: { shot_id: shotId } })}
                onPlay={() => setStartAt({ index: n, nonce: Date.now() })}
              />
            ))}
          </ol>
        </SortableContext>
      </DndContext>
      {timeline.items.length === 0 && <p className="text-sm text-neutral-400">Every clip was removed. Build a new rough cut from the Timeline page.</p>}
    </section>
  );
}

export function TimelineEditorPage() {
  const { timelineId = "" } = useParams();
  const { data, error, isPending, refetch } = useQuery(getTimelineOptions({ path: { timeline_id: timelineId } }));
  if (isPending) return <Loading label="Loading timeline…" />;
  if (error) return <ErrorState message={errorMessage(error)} onRetry={() => void refetch()} />;
  return <Editor key={data.id} timeline={data} />;
}
