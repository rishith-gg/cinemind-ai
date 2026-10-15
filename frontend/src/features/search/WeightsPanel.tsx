import { SIGNAL_LABEL } from "./labels";

export const SIGNALS = ["relevance", "quality", "selection", "person", "scene", "duplicate"] as const;

interface Props {
  weights: Record<string, number>;
  defaults: Record<string, number>;
  onChange: (weights: Record<string, number> | null) => void;
}

/** What-if sliders: the weight of every ranking signal. Results are ranked again with the new
 * weights; the same weights always give the same order. Nothing is saved. */
export function WeightsPanel({ weights, defaults, onChange }: Props) {
  const changed = SIGNALS.some((s) => (weights[s] ?? 0) !== (defaults[s] ?? 0));
  return (
    <details className="rounded border border-neutral-800 p-2 text-xs" open={changed}>
      <summary className="cursor-pointer text-sm">Ranking weights{changed ? " (changed)" : ""}</summary>
      <p className="my-1 text-neutral-400">
        Score = sum of signal × weight, minus duplicate × its weight. Try other weights to see the order change; they apply to this page
        only. Defaults come from the [ranking] settings and are a starting point, not tested values.
      </p>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {SIGNALS.map((s) => (
          <label key={s} className="flex items-center gap-2">
            <span className="w-28">{SIGNAL_LABEL[s]}</span>
            <input
              type="range"
              min={0}
              max={5}
              step={0.1}
              value={weights[s] ?? 0}
              aria-label={`Weight of ${SIGNAL_LABEL[s]}`}
              onChange={(e) => onChange({ ...weights, [s]: Number(e.target.value) })}
            />
            <span className="w-8 font-mono">{(weights[s] ?? 0).toFixed(1)}</span>
          </label>
        ))}
      </div>
      {changed && (
        <button className="mt-1 text-blue-300 underline" onClick={() => onChange(null)}>
          Back to the defaults
        </button>
      )}
    </details>
  );
}
