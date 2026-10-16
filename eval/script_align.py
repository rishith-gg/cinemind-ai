"""Script-to-footage alignment accuracy (SPEC P1-A) on the Blender open movie Tears of Steel.

Usage:
  uv run python eval/script_align.py fetch          # film (372 MB) + English subtitles
  uv run python eval/script_align.py run [--out]

Data: "Tears of Steel" (CC) Blender Foundation | mango.blender.org, Creative Commons Attribution
3.0; downloaded to data/eval/tears_of_steel/, never committed. The "script" is the film's
official English subtitles, one line per subtitle (76); their times are the ground truth. A
real screenplay differs more from what was said than subtitles do, so these figures are an
upper bound for that case. 20 distractor lines that are not in the film (written by Claude for
this test, below) check that a line that was not filmed is reported as not found.

The film is transcribed once with the app's speech model (cached), lines not marked uncertain
are kept as in the app, and the app's own alignment code (`rough_cut/script_align.py`) runs on
them. A film line counts as right when its best take reaches the score limit and the take's
middle lies at one of the places where the line is said (its own subtitle, or another subtitle
holding the same words; never the subtitles just before or after it), within 0.5 s; a
distractor counts as right when no take reaches the limit. Every rate is given with its count
and a 95 % Wilson interval: with 48 lines per half, a difference of a few lines is noise.
Weights and limit are chosen on the development half (even subtitles, first 10 distractors) and
reported on the test half (odd subtitles, last 10 distractors). Ablation: words only, meaning
only, both.
"""

import argparse
import datetime
import hashlib
import json
import math
import platform
import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from cinemind.ai import embedder, transcriber  # noqa: E402
from cinemind.core.config import REPO_ROOT, get_settings  # noqa: E402
from cinemind.core.script_config import ScriptConfig  # noqa: E402
from cinemind.core.transcribe_config import is_uncertain  # noqa: E402
from cinemind.rough_cut.script_align import Segment, Take, align, normalise  # noqa: E402
from cinemind.search.spoken import Word  # noqa: E402

BASE = "https://download.blender.org/demo/movies/ToS/"
# name -> (url, SHA-256 of the file as downloaded on 2026-10-16)
FILES = {
    "tears_of_steel_720p.mov": (
        BASE + "tears_of_steel_720p.mov",
        "efa9062d9cdb7a338e40ad530dfdf234806743f29ae6a1a136b97ece4e588e8f",
    ),
    "TOS-en.srt": (
        BASE + "subtitles/TOS-en.srt",
        "ce9578f6fe098a5821045a38884b229160f9e7ba27890448a92f5be330c6e6fe",
    ),
}
DATA = REPO_ROOT / "data" / "eval" / "tears_of_steel"
RESULTS = REPO_ROOT / "eval" / "results"
TOLERANCE_S = 0.5
DISTRACTORS = (
    "The harbour lights went out an hour before the ferry arrived.",
    "Grandmother always kept the good biscuits in a tin above the fridge.",
    "If the train is late again I am walking to the office.",
    "Put the violin back in its case before the rain starts.",
    "We sold the farm the summer my brother left for college.",
    "Nobody told me the wedding was moved to Saturday.",
    "The bakery on the corner closes early on Sundays.",
    "Can you water the tomatoes while I fix the fence?",
    "My dog chased a kite across the whole beach this morning.",
    "The election results will be announced at midnight.",
    "She painted the kitchen yellow without asking anyone.",
    "Turn left at the old church and follow the river.",
    "I think the soup needs more salt and a little lemon.",
    "The library fines doubled after the new mayor took office.",
    "He learned to juggle from a street performer in Lisbon.",
    "Our flight to Chennai was cancelled because of the storm.",
    "The cricket match went on long after sunset.",
    "Bring a warm jacket, the mountains get cold at night.",
    "I left my umbrella on the bus again.",
    "The museum has a new exhibition about ancient maps.",
)
WEIGHTS = (0.0, 0.3, 0.5, 0.7, 1.0)  # lexical weight; semantic weight is 1 - this
LIMITS = tuple(round(i * 0.05, 2) for i in range(21))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for name, (url, sha) in FILES.items():
        target = DATA / name
        if not target.exists():
            print(f"downloading {url}")
            partial = DATA / (name + ".partial")
            cmd = [
                "curl",
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "-o",
                str(partial),
                url,
            ]
            subprocess.run(cmd, check=True, timeout=7200)  # noqa: S603
            partial.replace(target)
        if _sha256(target) != sha:
            raise SystemExit(
                f"{target} is not the file this evaluation was written for (checksum)."
            )
    print("data ready, checksums match")


def _subtitles() -> list[tuple[str, float, float]]:
    text = (DATA / "TOS-en.srt").read_text(encoding="utf-8-sig")
    found: list[tuple[str, float, float]] = []
    stamp = r"(\d+):(\d+):(\d+),(\d+)"
    for block in re.split(r"\n\s*\n", text.strip()):
        rows = block.strip().split("\n")
        times = re.match(stamp + r"\s*-->\s*" + stamp, rows[1]) if len(rows) > 2 else None
        if not times:
            continue
        g = [int(x) for x in times.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        words = " ".join(rows[2:]).replace("...", " ").strip(" -")
        found.append((" ".join(words.split()), start, end))
    return found


def _check_data() -> None:
    for name, (_, sha) in FILES.items():
        if not (DATA / name).exists():
            raise SystemExit("The data is not downloaded: uv run python eval/script_align.py fetch")
        if _sha256(DATA / name) != sha:
            raise SystemExit(f"{DATA / name} is not the file this evaluation was written for.")


def _commit() -> str:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True, text=True, check=True, cwd=REPO_ROOT, timeout=10,
        )  # fmt: skip
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _transcript() -> tuple[dict[str, Any], str]:
    settings = get_settings()
    choice = transcriber.choose_model(settings)
    film = DATA / "tears_of_steel_720p.mov"
    # Keyed by the film, the model and every transcription setting.
    key = hashlib.sha256(
        json.dumps([FILES[film.name][1], choice.name, choice.revision,
                    settings.transcribe.model_dump()], sort_keys=True).encode()
    ).hexdigest()[:16]  # fmt: skip
    cache = REPO_ROOT / "data" / "eval" / "cache" / f"tos_transcript_{key}.json"
    if cache.exists():
        return json.loads(cache.read_text()), choice.name
    if not choice.path.exists():
        raise SystemExit("The speech model is not downloaded: uv run cinemind models pull")
    print(f"transcribing the film with {choice.name} (once; cached in {cache})")
    audio = transcriber.decode_audio(film, lambda: None)
    plan = transcriber.LanguagePlan(forced="en", allowed=(), detect_only=())
    found = transcriber.transcribe(
        choice, audio, settings.transcribe, lambda _: None, lambda: None, plan
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(found))
    return found, choice.name


def _segments(found: dict[str, Any]) -> list[Segment]:
    segs: list[Segment] = []
    for n, s in enumerate(found["segments"]):
        if is_uncertain(s["avg_logprob"], s["compression_ratio"]):
            continue
        words = tuple(Word(w[0], w[1], w[2]) for w in s.get("words") or [])
        segs.append(Segment(n, "film", s["start"], s["end"], s["text"], words))
    return segs


Place = tuple[float, float]


def _norm(text: str) -> str:
    return " ".join(w for w in (normalise(p) for p in text.split()) if w)


def _contains(words: str, text: str) -> bool:
    """`words` occur in `text` as whole words ("no" is not in "nothing")."""
    return bool(words) and f" {words} " in f" {text} "


def places(subs: list[tuple[str, float, float]]) -> list[list[Place]]:
    """Where each subtitle's words are said: its own time, and every other place that holds the
    same words: another subtitle (or two neighbouring subtitles, neither of them this one) that
    contains them as whole words or reads almost the same (similarity 0.9). The film repeats
    lines on purpose (the break-up scene is played again), and for a script assembly any of
    those is a right take. The subtitles just before and after a line never count for it."""
    norms = [_norm(t) for t, _, _ in subs]
    found: list[list[Place]] = []
    for i, line in enumerate(norms):
        here: list[Place] = [(subs[i][1], subs[i][2])]
        for j in range(len(subs)):
            if j in (i - 1, i, i + 1):
                continue
            if _contains(line, norms[j]) or SequenceMatcher(None, line, norms[j]).ratio() >= 0.9:
                here.append((subs[j][1], subs[j][2]))
            elif (
                j + 1 < len(subs)
                and j + 1 not in (i - 1, i, i + 1)
                and _contains(line, f"{norms[j]} {norms[j + 1]}")
            ):
                here.append((subs[j][1], subs[j + 1][2]))
        found.append(here)
    return found


def heard(line: str, where: list[Place], segs: list[Segment]) -> bool:
    """Whether the transcript has at least half of the line's words at one of its places: when it
    has not, the speech model missed the line and no alignment can find it."""
    words = set(_norm(line).split())
    for a, b in where:
        near = {
            normalise(w.text)
            for s in segs
            for w in s.words
            if w.end_s > a - TOLERANCE_S and w.start_s < b + TOLERANCE_S
        }
        if words and len(words & near) >= len(words) / 2:
            return True
    return False


def right(takes: list[Take], where: list[Place] | None, limit: float) -> bool:
    """A film line: its best take reaches the limit and the take's middle lies at one of the
    line's places (within TOLERANCE_S). A line not in the film: no take reaches the limit."""
    best = takes[0] if takes else None
    if where is None:
        return best is None or best.score < limit
    if best is None or best.score < limit:
        return False
    middle = (best.start_s + best.end_s) / 2
    return any(a - TOLERANCE_S <= middle <= b + TOLERANCE_S for a, b in where)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95 % Wilson score interval of k successes in n."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(centre - half, 3), round(centre + half, 3))


def _rate(k: int, n: int) -> dict[str, Any]:
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else 0.0, "ci95": wilson(k, n)}


def _accuracy(
    rows: list[tuple[list[Take], list[Place] | None, bool]], limit: float
) -> dict[str, Any]:
    film = [r for r in rows if r[1] is not None]
    other = [r for r in rows if r[1] is None]
    right_film = sum(right(t, g, limit) for t, g, _ in film)
    right_heard = sum(right(t, g, limit) for t, g, h in film if h)
    right_other = sum(right(t, g, limit) for t, g, _ in other)
    # In-point error of lines found at their own subtitle (the first place), in seconds.
    errors = sorted(abs(t[0].start_s - g[0][0]) for t, g, _ in film if right(t, g[:1], limit) and t)
    return {
        "accuracy": _rate(right_film + right_other, len(rows)),
        "film_lines_found": _rate(right_film, len(film)),
        "transcribed_lines_found": _rate(right_heard, sum(1 for r in film if r[2])),
        "not_filmed_rejected": _rate(right_other, len(other)),
        "median_in_point_error_s": round(errors[len(errors) // 2], 2) if errors else None,
    }


def run(out: bool) -> None:
    settings = get_settings()
    _check_data()
    subs = _subtitles()
    found, model = _transcript()
    segs = _segments(found)
    spec = embedder.choose_text(settings)
    embed = None
    if spec.ready(settings.models_path):
        embed = lambda texts: embedder.embed_texts(spec, settings, texts)  # noqa: E731
    lines = [s[0] for s in subs] + list(DISTRACTORS)
    where = places(subs)
    truth: list[list[Place] | None] = [*where, *([None] * len(DISTRACTORS))]
    spoken = [heard(t, w, segs) for (t, _, _), w in zip(subs, where, strict=True)]
    spoken += [False] * len(DISTRACTORS)
    dev = [i for i in range(len(subs)) if i % 2 == 0] + [len(subs) + i for i in range(10)]
    test = [i for i in range(len(subs)) if i % 2 == 1] + [len(subs) + i for i in range(10, 20)]
    families = {"words only": (1.0,), "meaning only": (0.0,), "both": (0.3, 0.5, 0.7)}
    report: dict[str, Any] = {}
    for family, weights in families.items():
        if embed is None and family != "words only":
            continue
        best: tuple[float, float, float] | None = None  # dev accuracy, weight, limit
        results: dict[float, list[list[Take]]] = {}
        for w in weights:
            cfg = ScriptConfig(lexical_weight=w, semantic_weight=1 - w, takes_kept=1)
            results[w] = align(lines, segs, cfg, embed if w < 1 else None)
            for limit in LIMITS:
                acc = _accuracy([(results[w][i], truth[i], spoken[i]) for i in dev], limit)
                score = acc["accuracy"]["rate"]
                if best is None or score > best[0]:  # ties keep the first: lower weight, limit
                    best = (score, w, limit)
        if best is None:
            continue
        _, w, limit = best
        report[family] = {
            "lexical_weight": w,
            "semantic_weight": round(1 - w, 2),
            "min_score": limit,
            "dev": _accuracy([(results[w][i], truth[i], spoken[i]) for i in dev], limit),
            "test": _accuracy([(results[w][i], truth[i], spoken[i]) for i in test], limit),
        }
    meta = {
        "date": str(datetime.date.today()),
        "data": "Tears of Steel 720p, (CC) Blender Foundation | mango.blender.org, CC BY 3.0",
        "script": "official English subtitles (76 lines) + 20 distractor lines written by Claude",
        "speech_model": model,
        "text_model": spec.key if embed else None,
        "segments_kept": len(segs),
        "segments_total": len(found["segments"]),
        "machine": f"{platform.platform()}, {platform.processor()}",
        "tolerance_s": TOLERANCE_S,
        "right_take": "the take's middle within tolerance of one of the line's places",
        "split": "dev = even subtitles + distractors 1-10, test = odd subtitles + 11-20",
        "commit": _commit(),
        "script_settings": ScriptConfig().model_dump(),
        "transcribe_settings": get_settings().transcribe.model_dump(),
    }
    lines_out = [f"script alignment, {meta['date']}: {json.dumps(meta)}", ""]

    def fmt(r: dict[str, Any]) -> str:
        return f"{r['k']}/{r['n']} = {r['rate']:.3f} [{r['ci95'][0]:.2f}, {r['ci95'][1]:.2f}]"

    for family, r in report.items():
        t = r["test"]
        lines_out.append(
            f"{family}: words {r['lexical_weight']} / meaning {r['semantic_weight']}, limit "
            f"{r['min_score']} (chosen on dev, dev accuracy {fmt(r['dev']['accuracy'])}). TEST: "
            f"accuracy {fmt(t['accuracy'])}; film lines found {fmt(t['film_lines_found'])}; "
            f"lines the speech model wrote down found {fmt(t['transcribed_lines_found'])}; "
            f"not-filmed lines rejected {fmt(t['not_filmed_rejected'])}; median in-point error "
            f"{t['median_in_point_error_s']} s"
        )
    text = "\n".join(lines_out)
    print(text)
    if out:
        RESULTS.mkdir(parents=True, exist_ok=True)
        stem = RESULTS / f"script_align_tears_of_steel_{meta['date']}"
        stem.with_suffix(".txt").write_text(text + "\n", encoding="utf-8")
        stem.with_suffix(".json").write_text(json.dumps({"meta": meta, "report": report}, indent=2))
        print(f"written: {stem}.txt / .json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch")
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--out", action="store_true")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch()
    else:
        run(args.out)


if __name__ == "__main__":
    main()
