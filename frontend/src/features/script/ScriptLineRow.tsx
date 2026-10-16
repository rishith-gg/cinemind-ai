import { Link } from "react-router";

import type { ScriptLineOut, TakeOut } from "../../api";
import { formatTime } from "../library/format";

function scoreText(t: TakeOut): string {
  const parts = [`words ${t.lexical.toFixed(2)}`];
  if (t.semantic !== null) parts.push(`meaning ${t.semantic.toFixed(2)}`);
  return `match ${t.score.toFixed(2)} (${parts.join(", ")})`;
}

/** One script line: scene headings and action as text, dialogue with its take and a choice. */
export function ScriptLineRow({
  line,
  number,
  busy,
  onChoose,
}: {
  line: ScriptLineOut;
  number: number;
  busy: boolean;
  onChoose: (choice: { take_id?: string; not_filmed?: boolean }) => void;
}) {
  if (line.kind === "scene")
    return (
      <li>
        <h3 className="pt-3 text-sm font-semibold uppercase tracking-wide text-neutral-300">{line.text}</h3>
      </li>
    );
  if (line.kind === "action") return <li className="text-sm italic text-neutral-500">{line.text}</li>;
  const take = line.takes.find((t) => t.id === line.chosen_take_id);
  const lost = line.choice === "take" && !take; // the chosen take is no longer found
  const value = line.choice === "not_filmed" ? "not_filmed" : line.choice === "take" ? (take?.id ?? "lost") : "auto";
  return (
    <li aria-label={`Line ${number}`} className="rounded border border-neutral-800 bg-neutral-900 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm">
          <span className="text-neutral-500">{number}.</span>{" "}
          {line.character && <span className="font-semibold">{line.character}: </span>}
          {line.text}
        </p>
        <select
          aria-label={`Take for line ${number}`}
          className="max-w-xs rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs"
          value={value}
          disabled={busy}
          onChange={(e) => {
            const v = e.target.value;
            onChoose(v === "auto" ? {} : v === "not_filmed" ? { not_filmed: true } : { take_id: v });
          }}
        >
          <option value="auto">Best match</option>
          {lost && (
            <option value="lost" disabled>
              Your take (no longer found)
            </option>
          )}
          {line.takes.map((t) => (
            <option key={t.id} value={t.id}>
              Take {t.rank}: {t.filename} {formatTime(t.start_s)} · {t.score.toFixed(2)}
            </option>
          ))}
          <option value="not_filmed">Not filmed</option>
        </select>
      </div>
      {take ? (
        <p className="mt-1 text-xs text-neutral-400">
          <Link className="underline" to={`/library/${take.media_id}?t=${take.start_s}`}>
            {take.filename} {formatTime(take.start_s)}–{formatTime(take.end_s)}
          </Link>{" "}
          · heard “{take.text}” · {scoreText(take)} · {line.why}
        </p>
      ) : (
        <p className="mt-1 text-xs text-amber-400">No take used: {line.why}.</p>
      )}
    </li>
  );
}
