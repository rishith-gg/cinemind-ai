import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { getMediaTranscriptOptions } from "../../api/@tanstack/react-query.gen";
import { errorMessage } from "../../lib/errors";
import { formatTime } from "../library/format";
import { ClipLanguage } from "./ClipLanguage";
import { languageName, UNCERTAIN_HINT } from "./labels";

interface Props {
  mediaId: string;
  projectId: string;
  clipLanguage: string | null;
  time: number;
  onSeek: (seconds: number) => void;
}

/** The clip's machine transcript, following playback: the word being spoken is highlighted and
 * any word or time can be clicked to jump there. Says which model produced it. Lines the model
 * itself did not accept are hidden unless the user asks for them. */
export function TranscriptPanel({ mediaId, projectId, clipLanguage, time, onSeek }: Props) {
  const { data, error } = useQuery(getMediaTranscriptOptions({ path: { media_id: mediaId } }));
  const [filter, setFilter] = useState("");
  const [showUnsure, setShowUnsure] = useState(false);
  const [follow, setFollow] = useState(true);
  const list = useRef<HTMLOListElement | null>(null);
  const active = useRef<HTMLLIElement | null>(null);
  const visible = (data?.segments ?? []).filter((s) => showUnsure || !s.uncertain);
  const activeId = visible.find((s) => time >= s.start_s && time < s.end_s)?.id;

  // Keep the spoken segment in view by scrolling the list itself, never the page.
  useEffect(() => {
    const box = list.current;
    const row = active.current;
    if (!follow || !box || !row) return;
    if (row.offsetTop < box.scrollTop || row.offsetTop + row.offsetHeight > box.scrollTop + box.clientHeight)
      box.scrollTop = row.offsetTop - box.clientHeight / 3;
  }, [activeId, follow]);

  if (error) return <p className="text-sm text-red-300">{errorMessage(error)}</p>;
  if (!data) return null;
  const language = <ClipLanguage mediaId={mediaId} projectId={projectId} value={clipLanguage} />;
  if (data.status !== "done") {
    return (
      <section aria-label="Transcript" className="space-y-1 text-sm text-neutral-400">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-medium text-neutral-200">Transcript</h2>
          {data.status !== "no_audio" && language}
        </div>
        {data.status === "not_written" && (
          <p>
            {languageName(data.language)} speech, {Math.round(data.speech_s)} s.
          </p>
        )}
        <p role="note">{data.message}</p>
      </section>
    );
  }
  const needle = filter.trim().toLowerCase();
  const shown = needle ? visible.filter((s) => s.text.toLowerCase().includes(needle)) : visible;
  const uncertain = data.segments.filter((s) => s.uncertain).length;
  const probability = data.language_probability == null ? "" : ` (${Math.round(data.language_probability * 100)}% sure)`;
  return (
    <section aria-label="Transcript" className="space-y-2 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-medium">Transcript</h2>
        <p className="text-xs text-neutral-400">
          {languageName(data.language)}
          {probability} · Whisper {data.model} · {data.segments.length} segments
        </p>
      </div>
      {language}
      {data.language_uncertain && (
        <p role="note" className="rounded border border-amber-800 bg-amber-950 p-2 text-xs">
          The language was a guess{probability}. If it is wrong, choose the right one above, or set the project's spoken languages
          on the Transcripts page.
        </p>
      )}
      {uncertain > 0 && (
        <p role="note" className="text-xs text-neutral-400">
          {uncertain === data.segments.length
            ? `The speech model was unsure about all ${uncertain} lines of this clip, so they are hidden.`
            : `${uncertain} of ${data.segments.length} lines are hidden: the speech model was unsure about them.`}{" "}
          <button className="text-blue-300 underline" onClick={() => setShowUnsure((v) => !v)}>
            {showUnsure ? "Hide them" : "Show them"}
          </button>
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="search"
          aria-label="Find in this transcript"
          placeholder="Find in this transcript"
          className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <label className="flex items-center gap-1 text-xs text-neutral-400">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Follow playback
        </label>
      </div>
      {shown.length === 0 && needle && <p className="text-xs text-neutral-500">Nothing in this transcript contains “{filter.trim()}”.</p>}
      <ol ref={list} aria-label="Transcript segments" hidden={shown.length === 0} className="relative max-h-72 space-y-1 overflow-y-auto rounded bg-neutral-900 p-2">
        {shown.map((segment) => {
          const current = segment.id === activeId;
          return (
            <li
              key={segment.id}
              ref={current ? active : undefined}
              aria-current={current ? "true" : undefined}
              className={`flex gap-2 rounded px-1 ${current ? "bg-neutral-800" : ""}`}
            >
              <button
                type="button"
                aria-label={`Jump to ${formatTime(segment.start_s)}`}
                className="shrink-0 font-mono text-xs text-blue-300 hover:underline"
                onClick={() => onSeek(segment.start_s)}
              >
                {formatTime(segment.start_s)}
              </button>
              <p className={segment.uncertain ? "italic text-neutral-500" : ""}>
                {segment.words.length === 0 && segment.text}
                {segment.words.map((word, i) => {
                  const spoken = current && time >= word.start_s && time < word.end_s;
                  return (
                    <button
                      key={i}
                      type="button"
                      title={`${formatTime(word.start_s)} · ${Math.round(word.probability * 100)}% word probability`}
                      className={`mr-1 rounded hover:underline ${spoken ? "bg-blue-600 text-white" : ""}`}
                      onClick={() => onSeek(word.start_s)}
                    >
                      {word.word}
                    </button>
                  );
                })}
                {segment.uncertain && (
                  <span title={UNCERTAIN_HINT} className="ml-1 rounded bg-amber-900/50 px-1 text-xs not-italic text-amber-300">
                    uncertain
                  </span>
                )}
              </p>
            </li>
          );
        })}
      </ol>
      <p className="text-xs text-neutral-500">
        Machine transcript; it can be wrong, most of all with music, noise or several people talking. Click a word to jump to it.
        {uncertain > 0 &&
          ` Unsure means the model's own likelihood is under ${data.thresholds.uncertain_logprob_below} (log) or the text repeats itself.`}{" "}
        One language applies to the whole clip.
      </p>
    </section>
  );
}
