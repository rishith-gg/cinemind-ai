# CineMind AI

Local-first, AI-assisted pre-editing for filmmakers: raw footage → searchable, organised library → ranked shots →
**AI-assisted rough cut** → FCP7 XML / EDL / OTIO → DaVinci Resolve. Everything runs on your own machine; the human
editor makes every creative decision.

What it does: imports a footage folder without touching it; detects shots, keyframes and scenes; measures technical
quality (focus, exposure, loudness, clipping); transcribes speech with word timings; groups faces into actors;
tags shots; searches by words, meaning, picture or a reference image with an explained score; finds repeated takes
and suggests the best one; aligns a screenplay to the footage; builds a rough cut from a one-sentence brief; and
exports a timeline that opens in DaVinci Resolve.

## Requirements
- macOS, Linux or Windows; 8 GB RAM is enough (tested on an Apple M1, 8 GB). No NVIDIA GPU needed.
- Python 3.11+ with [uv](https://docs.astral.sh/uv/), Node.js 20+ with [pnpm](https://pnpm.io/), FFmpeg (with
  ffprobe) on the PATH.
- About 1.5 GB of disk for the models (downloaded once).

## Run it (steps to execute the project)
```bash
git clone <this repository> cinemind && cd cinemind
uv sync                                   # Python dependencies
(cd frontend && pnpm install)             # UI dependencies
uv run cinemind doctor                    # checks ffmpeg, Python, Node, RAM, GPU; prints the model tier
uv run cinemind models pull               # speech, face, picture and text models (needs internet once)
echo 'CINEMIND_MEDIA_ROOTS=["/path/to/your/footage"]' > .env   # folders the app may read
uv run python scripts/tasks.py build-ui   # build the web UI once
uv run cinemind serve                     # API + UI + worker → open http://127.0.0.1:8000
```
Then in the browser: **Projects → New project → Library → Import folder → Process all**, and follow the pages in
the sidebar (Shots / Scenes, Actors, Transcripts, Search, Takes, Script, Timeline, Export). See
[docs/USER_GUIDE.md](docs/USER_GUIDE.md) for a walk-through and [docs/DEMO.md](docs/DEMO.md) for the demo script.

Development: `uv run python scripts/tasks.py dev-api` and `uv run python scripts/tasks.py dev-ui` (Vite on :5173).
Checks: `uv run python scripts/tasks.py check` (ruff, pyright, pytest, tsc, eslint, vitest); E2E:
`uv run python scripts/tasks.py e2e`.

## Documentation
| File | Contents |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | Product and technical specification |
| [docs/AI_PIPELINE.md](docs/AI_PIPELINE.md) | Every stage, model and formula |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Every measured figure, with the script that produced it |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Engineering decisions and why |
| [docs/API.md](docs/API.md), [docs/DATABASE.md](docs/DATABASE.md) | API and data model |
| [docs/TESTING.md](docs/TESTING.md) | Tests and the manual DaVinci Resolve checklist |
| [docs/PROGRESS.md](docs/PROGRESS.md) | Current state and known limitations |

## Principles
Local-first (no cloud, no paid APIs, no internet while processing) · non-destructive (source footage is never
modified) · explainable (every tag, rank and cut stores its inputs) · honest (every number in the docs comes from a
script in `eval/`) · works on CPU.
