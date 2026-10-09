import { useQuery } from "@tanstack/react-query";

import { getMediaQualityOptions } from "../../api/@tanstack/react-query.gen";
import { errorMessage } from "../../lib/errors";
import { formatTime } from "../library/format";
import { explainFlag, flagLabel, scoreText } from "./labels";

function Bar({ value }: { value: number }) {
  return (
    <span className="inline-block h-1.5 w-12 rounded bg-neutral-800 align-middle" aria-hidden>
      <span className="block h-full rounded bg-blue-500" style={{ width: `${Math.round(value * 100)}%` }} />
    </span>
  );
}

/** The clip's Technical Quality Score with everything behind it: sub-scores per shot, audio
 * measurements, and each flag's measured value against its threshold. */
export function QualityPanel({ mediaId }: { mediaId: string }) {
  const { data, error } = useQuery(getMediaQualityOptions({ path: { media_id: mediaId } }));
  if (error) return <p className="text-sm text-red-300">{errorMessage(error)}</p>;
  if (!data) return null;
  if (!data.measured) {
    return (
      <section aria-label="Technical quality" className="text-sm text-neutral-400">
        <h2 className="mb-1 font-medium text-neutral-200">Technical quality</h2>
        No technical score. Processing may still be running, or nothing in this clip could be measured.
      </section>
    );
  }
  const weights = data.config;
  return (
    <section aria-label="Technical quality" className="space-y-3 text-sm">
      <div className="flex items-baseline justify-between">
        <h2 className="font-medium">Technical quality</h2>
        <p>
          <span className={`text-2xl font-semibold ${data.low_quality ? "text-red-300" : ""}`}>{scoreText(data.score)}</span>
          <span className="text-neutral-400"> / 100{data.low_quality && " · low"}</span>
        </p>
      </div>
      {data.shots.length > 0 && (
        <table className="w-full text-left text-xs">
          <caption className="sr-only">Technical sub-scores per shot, 0 to 100</caption>
          <thead className="text-neutral-400">
            <tr>
              {["Shot", "Score", "Focus", "Exposure", "Contrast"].map((h) => (
                <th key={h} scope="col" className="font-normal">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.shots.map((s) => (
              <tr key={s.shot_id} title={`${s.frames} frames measured · blur ${s.blur.toFixed(2)} · brightness ${s.luma_mean.toFixed(2)} · tonal range ${s.spread.toFixed(2)}`}>
                <td>{s.index + 1}</td>
                <td>{scoreText(s.score)}</td>
                <td>
                  {s.sharpness_score == null ? (
                    <span title="No tonal range in this shot (black, fog, a plain surface): focus cannot be judged.">not judged</span>
                  ) : (
                    <>
                      <Bar value={s.sharpness_score} /> {scoreText(s.sharpness_score)}
                    </>
                  )}
                </td>
                <td>
                  <Bar value={s.exposure_score} /> {scoreText(s.exposure_score)}
                </td>
                <td>
                  <Bar value={s.contrast_score} /> {scoreText(s.contrast_score)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data.audio ? (
        <p className="text-xs text-neutral-300">
          Audio {scoreText(data.audio.score)} / 100 · loudness{" "}
          {data.audio.integrated_lufs == null
            ? (data.audio.details as { loudness_note?: string }).loudness_note === "too_short"
              ? "too short to measure"
              : "silent"
            : `${data.audio.integrated_lufs.toFixed(1)} LUFS`}{" "}
          · peak{" "}
          {data.audio.true_peak_db == null ? "–" : `${data.audio.true_peak_db.toFixed(1)} dBFS`} · clipped{" "}
          {data.audio.clipped_pct.toFixed(2)}% · silent {data.audio.silence_pct.toFixed(0)}%
        </p>
      ) : (
        <p className="text-xs text-neutral-500">No audio measurements.</p>
      )}
      {data.flags.length > 0 ? (
        <ul aria-label="QC flag list" className="space-y-1 text-xs">
          {data.flags.map((f, i) => (
            <li key={`${f.kind}-${f.start_s}-${i}`}>
              <span className="text-amber-300">{flagLabel(f.kind)}</span>{" "}
              <span className="font-mono text-neutral-400">
                {formatTime(f.start_s)}–{formatTime(f.end_s)}
              </span>{" "}
              <span className="text-neutral-400">{explainFlag(f)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-neutral-500">No QC flags.</p>
      )}
      {data.settings_changed && (
        <p role="note" className="rounded border border-amber-800 bg-amber-950 p-2 text-xs">
          The quality settings have changed since this clip was scored. Press Reprocess to re-score it.
        </p>
      )}
      <p className="text-xs text-neutral-500">
        Shot score: weighted average of focus ({weights.weight_sharpness}), exposure ({weights.weight_exposure}) and contrast (
        {weights.weight_contrast}). Clip score: shot scores weighted by shot length
        {data.audio && `, blended with the audio score at ${weights.weight_audio}`}. These are technical measurements, not a
        judgement of the shot. “Soft picture” also fires on fog, water or heavy compression. Flag limits were calibrated on
        frames degraded on purpose, not on human ratings.
      </p>
    </section>
  );
}
