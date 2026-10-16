import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import type { TakeGroupOut, TakeGroupsOut, TakeMemberOut } from "../../api";
import { listTakeGroupsQueryKey, setBestTakeMutation, setTakeApartMutation } from "../../api/@tanstack/react-query.gen";
import { toast } from "../../lib/toast";
import { formatTime } from "../library/format";
import { MarkButtons } from "../marks/MarkButtons";
import { SIGNALS, bestByText, pairText } from "./labels";

export function useSetTakes(projectId: string): (data: TakeGroupsOut) => void {
  const qc = useQueryClient();
  return (data) => qc.setQueryData(listTakeGroupsQueryKey({ path: { project_id: projectId } }), data);
}

function Signals({ member }: { member: TakeMemberOut }) {
  const shown = SIGNALS.filter(([key]) => key in member.signals);
  return (
    <dl className="grid grid-cols-[auto_1fr_auto] items-center gap-x-2 gap-y-0.5">
      {shown.map(([key, label, help]) => {
        const value = member.signals[key];
        return (
          <div key={key} className="contents" title={help}>
            <dt className="text-neutral-400">{label}</dt>
            <dd className="h-1.5 overflow-hidden rounded bg-neutral-800" aria-hidden="true">
              {value !== null && value !== undefined && <div className="h-full bg-blue-500" style={{ width: `${Math.round(value * 100)}%` }} />}
            </dd>
            <dd className="text-right font-mono">{value === null || value === undefined ? "—" : value.toFixed(2)}</dd>
          </div>
        );
      })}
    </dl>
  );
}

function MemberCard({ projectId, group, member }: { projectId: string; group: TakeGroupOut; member: TakeMemberOut }) {
  const qc = useQueryClient();
  const setTakes = useSetTakes(projectId);
  const label = `${member.filename}, shot ${member.index + 1}`;
  const best = useMutation({
    ...setBestTakeMutation(),
    onSuccess: (fresh, vars) => {
      setTakes(fresh);
      toast.success(vars.body.best ? `${label} is now the best take.` : "The signals choose the best take again.");
    },
  });
  const apart = useMutation({
    ...setTakeApartMutation(),
    onSuccess: (fresh) => {
      setTakes(fresh);
      toast.success(`${label} is no longer grouped with these takes.`);
    },
  });
  const busy = best.isPending || apart.isPending;
  const body = (b: { best?: boolean; apart?: boolean }) => ({ path: { project_id: projectId }, body: { shot_id: member.shot_id, ...b } });
  return (
    <li className={`w-56 overflow-hidden rounded border bg-neutral-900 ${member.best ? "border-green-600" : "border-neutral-800"}`}>
      <Link to={`/library/${member.media_id}?t=${member.start_s}`} aria-label={`Open ${label}`} className="block hover:bg-neutral-800/60">
        <div className="relative flex aspect-video items-center justify-center bg-black text-xs text-neutral-500">
          {member.keyframe_id ? (
            <img src={`/api/keyframes/${member.keyframe_id}/image`} alt="" className="h-full w-full object-cover" loading="lazy" />
          ) : (
            <span>No keyframe</span>
          )}
          <span className={`absolute left-1 top-1 rounded px-1 text-[10px] ${member.best ? "bg-green-700" : "bg-black/70"}`}>
            {member.best ? "Best take" : `Take ${member.rank}`}
          </span>
        </div>
        <div className="p-2">
          <p className="truncate text-xs font-medium" title={member.filename}>
            {member.filename} · {member.index + 1}
          </p>
          <p className="font-mono text-xs text-neutral-400">
            {formatTime(member.start_s)} – {formatTime(member.end_s)}
          </p>
        </div>
      </Link>
      <div className="space-y-1.5 border-t border-neutral-800 p-2 text-xs">
        <p>
          Take score <span className="font-mono">{member.score === null || member.score === undefined ? "not measured" : member.score.toFixed(2)}</span>
        </p>
        <Signals member={member} />
        {member.text && <p className="line-clamp-3 italic text-neutral-300">“{member.text}”</p>}
        {member.notes.length > 0 && (
          <ul aria-label={`Notes on ${label}`} className="list-inside list-disc text-amber-300">
            {member.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {!member.best && member.mark !== "reject" && (
            <button className="text-blue-300 underline" disabled={busy} onClick={() => best.mutate(body({ best: true }))} aria-label={`Make ${label} the best take`}>
              Make best take
            </button>
          )}
          {member.best && group.best_by === "you" && (
            <button className="text-blue-300 underline" disabled={busy} onClick={() => best.mutate(body({ best: false }))}>
              Let the signals choose
            </button>
          )}
          <button className="text-blue-300 underline" disabled={busy} onClick={() => apart.mutate(body({ apart: true }))} aria-label={`${label} is not a take of these`}>
            Not a take of these
          </button>
        </div>
      </div>
      <div className="border-t border-neutral-800 px-2 py-1">
        <MarkButtons
          shotId={member.shot_id}
          label={label}
          mark={member.mark ?? null}
          stars={member.stars ?? 0}
          onChanged={() => void qc.invalidateQueries({ queryKey: listTakeGroupsQueryKey({ path: { project_id: projectId } }) })}
        />
      </div>
    </li>
  );
}

export function TakeGroupCard({ projectId, group }: { projectId: string; group: TakeGroupOut }) {
  const names = new Map(group.members.map((m) => [m.shot_id, `${m.filename} · ${m.index + 1}`]));
  const title = `Take group ${group.index + 1}`;
  return (
    <article aria-label={title} className="space-y-2 rounded border border-neutral-800 p-3">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="font-semibold">{title}</h2>
        <span className="text-xs text-neutral-400">
          {group.members.length} takes · {group.kind === "speech" ? "same words" : "same picture, no speech"} · {bestByText(group)}
        </span>
      </header>
      <ul className="flex flex-wrap gap-3">
        {group.members.map((m) => (
          <MemberCard key={m.shot_id} projectId={projectId} group={group} member={m} />
        ))}
      </ul>
      <details className="text-xs text-neutral-400">
        <summary className="cursor-pointer">Why these are grouped</summary>
        <ul className="mt-1 space-y-0.5">
          {group.pairs.map((p) => (
            <li key={`${p.a}-${p.b}`}>
              {names.get(p.a) ?? p.a} ↔ {names.get(p.b) ?? p.b}: {pairText(p)}
            </li>
          ))}
        </ul>
      </details>
    </article>
  );
}
