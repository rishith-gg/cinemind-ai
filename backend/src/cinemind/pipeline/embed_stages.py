"""Ingest stages `embed_visual`, `embed_text` (SPEC section 5, stage 11) and `tags` (stage 12).

`embed_visual` turns every keyframe into a picture vector and a colour histogram; `embed_text`
turns every transcript segment into a sentence vector; `tags` scores the keyframes against the
tag vocabulary. Vectors are written to the `embeddings` table, from which the vector index is
built (`search/vector_index.py`). None of the stages downloads anything: without a model on disk
they record `model_missing`, the clip's other results stay usable, and the next run tries again.

As with the quality stages (D-045), `tags` caches raw scores only. Whether a tag is shown is
decided when it is stored, from the thresholds in `ai/tag_thresholds.json`.
"""

import hashlib
import json
import shutil
from typing import Any

import cv2
import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cinemind.ai import embedder, tagger
from cinemind.core.config import Settings
from cinemind.core.errors import UnreadableMediaError
from cinemind.db.analysis import Embedding, EmbeddingSet
from cinemind.db.models import Keyframe, Shot, TranscriptSegment
from cinemind.jobs.registry import Stage, StageContext
from cinemind.pipeline import tag_stage
from cinemind.pipeline.stage_utils import media_id, project_dir

PIPELINE_VERSION = "1"
VECTORS, COLORS = "vectors.npy", "colors.npy"
COLOR_MODEL = f"hsv-hist-{'x'.join(map(str, embedder.HIST_BINS))}"


def visual_params(settings: Settings) -> dict[str, Any]:
    spec = embedder.choose_visual(settings)
    return {"model": spec.key, "revision": spec.revision}


def text_params(settings: Settings) -> dict[str, Any]:
    spec = embedder.choose_text(settings)
    return {"model": spec.key, "revision": spec.revision}


def _folder(ctx: StageContext, kind: str, basis: Any) -> str:
    """One folder per model and settings, so a cached result only names its own files."""
    key = json.dumps([basis, PIPELINE_VERSION], sort_keys=True)
    return f"analysis/embed/{media_id(ctx)}/{kind}-{hashlib.sha256(key.encode()).hexdigest()[:12]}"


def _clear_others(ctx: StageContext, kind: str, keep: str | None) -> None:
    folder = project_dir(ctx) / "analysis" / "embed" / media_id(ctx)
    if folder.is_dir():
        for child in folder.glob(f"{kind}-*"):
            if keep is None or child.name != keep.rsplit("/", 1)[-1]:
                shutil.rmtree(child, ignore_errors=True)


def _digest(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _set_row(session: Session, media: str, kind: str) -> EmbeddingSet:
    row = session.get(EmbeddingSet, (media, kind))
    if row is None:
        row = EmbeddingSet(media_id=media, kind=kind, status="", digest="")
        session.add(row)
    return row


# --- embed_visual -----------------------------------------------------------------------------


def run_embed_visual(ctx: StageContext) -> dict[str, Any]:
    params: dict[str, Any] = ctx.params.get("embed_visual") or visual_params(ctx.settings)
    spec = embedder.choose_visual(ctx.settings, params["model"])
    base: dict[str, Any] = {
        "model": spec.key,
        "revision": spec.revision,
        "dir": None,
        "keyframes": [],
    }
    keyframes = ctx.previous["keyframes"]
    if keyframes["dir"] is None or not keyframes["keyframes"]:
        return {**base, "status": "no_video"}
    if not spec.ready(ctx.settings.models_path):
        return {
            **base,
            "status": "model_missing",
            "reason": f"The picture model '{spec.key}' ({spec.size_mb} MB) is not downloaded.",
        }
    source = project_dir(ctx) / keyframes["dir"]
    items = keyframes["keyframes"]
    vectors: list[Any] = []
    colors: list[Any] = []
    batch = ctx.settings.embed.batch_size
    for start in range(0, len(items), batch):
        ctx.check_cancelled()
        frames = [cv2.imread(str(source / item["file"])) for item in items[start : start + batch]]
        if any(frame is None for frame in frames):
            raise UnreadableMediaError("A keyframe image is missing. Press Reprocess.")
        vectors.append(embedder.embed_images(spec, ctx.settings, frames))
        colors.extend(embedder.color_histogram(frame) for frame in frames)
        ctx.progress((start + len(frames)) / len(items))
    rel = _folder(ctx, "visual", [params, keyframes["dir"]])
    folder = project_dir(ctx) / rel
    folder.mkdir(parents=True, exist_ok=True)
    np.save(folder / VECTORS, np.concatenate(vectors).astype(np.float32))
    np.save(folder / COLORS, np.stack(colors).astype(np.float32))
    return {
        **base,
        "status": "done",
        "dir": rel,
        "dim": spec.dim,
        "keyframes": [[int(k["shot"]), int(k["slot"]), int(k["frame"])] for k in items],
        "engine": embedder.engine_version(),
        "device": embedder.pick_device(ctx.settings.embed.device),
    }


def _verify_files(ctx: StageContext, cached: dict[str, Any], names: tuple[str, ...]) -> bool:
    if cached.get("status") in ("model_missing", "no_transcript"):
        return False
    if cached.get("dir") is None:
        return True
    return all((project_dir(ctx) / cached["dir"] / name).is_file() for name in names)


def verify_embed_visual(ctx: StageContext, cached: dict[str, Any]) -> bool:
    return _verify_files(ctx, cached, (VECTORS, COLORS))


def _keyframe_rows(session: Session, media: str) -> dict[tuple[int, int], tuple[str, str]]:
    """(shot index, slot) -> (keyframe id, shot id) for the keyframes stored for this clip."""
    query = (
        select(Shot.index, Keyframe.slot, Keyframe.id, Shot.id)
        .join(Shot, Shot.id == Keyframe.shot_id)
        .where(Keyframe.media_id == media)
    )
    return {(i, s): (k, sh) for i, s, k, sh in session.execute(query)}


def persist_embed_visual(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    media = media_id(ctx)
    refs = _keyframe_rows(session, media)
    row = _set_row(session, media, "visual")
    digest = _digest(result, sorted(refs.items()))
    if row.digest == digest:
        # The stored rows are exactly this result's (also after a model-missing run in between).
        row.status = result["status"]
        return
    if result["status"] == "model_missing" and row.status in ("done", "model_missing"):
        row.status, row.details = result["status"], {**row.details, "reason": result.get("reason")}
        return  # what an earlier run found stays until a real result replaces it
    session.execute(
        delete(Embedding).where(
            Embedding.media_id == media, Embedding.kind.in_(("keyframe", "color"))
        )
    )
    row.status, row.model, row.revision, row.digest = (
        result["status"],
        result["model"],
        result["revision"],
        digest,
    )
    row.details = {k: result[k] for k in ("engine", "device", "reason", "dim") if k in result}
    row.count = 0
    _clear_others(ctx, "visual", result.get("dir"))
    if result["status"] != "done":
        return
    folder = project_dir(ctx) / result["dir"]
    vectors, colors = np.load(folder / VECTORS), np.load(folder / COLORS)
    for (shot, slot, _frame), vector, color in zip(
        result["keyframes"], vectors, colors, strict=True
    ):
        ref = refs.get((shot, slot))
        if ref is None:
            continue
        keyframe_id, shot_id = ref
        common = {"media_id": media, "ref_id": keyframe_id, "shot_id": shot_id}
        session.add(
            Embedding(
                **common,
                kind="keyframe",
                model=result["model"],
                dim=len(vector),
                vector=vector.tobytes(),
            )
        )
        session.add(
            Embedding(
                **common, kind="color", model=COLOR_MODEL, dim=len(color), vector=color.tobytes()
            )
        )
        row.count += 1


# --- embed_text -------------------------------------------------------------------------------


def run_embed_text(ctx: StageContext) -> dict[str, Any]:
    params: dict[str, Any] = ctx.params.get("embed_text") or text_params(ctx.settings)
    spec = embedder.choose_text(ctx.settings, params["model"])
    base: dict[str, Any] = {"model": spec.key, "revision": spec.revision, "dir": None, "count": 0}
    transcript = ctx.previous["transcribe"]
    if transcript.get("status") not in ("done", "no_speech", "no_audio"):
        # No transcript yet (speech model missing, unreadable audio): try again next run.
        return {
            **base,
            "status": "no_transcript",
            "reason": f"transcribe: {transcript.get('status')}",
        }
    segments: list[dict[str, Any]] = transcript.get("segments") or []
    if not segments:
        return {**base, "status": "no_speech"}
    if not spec.ready(ctx.settings.models_path):
        return {
            **base,
            "status": "model_missing",
            "reason": f"The text model '{spec.key}' ({spec.size_mb} MB) is not downloaded.",
        }
    texts = [str(seg["text"]).strip() for seg in segments]
    vectors: list[Any] = []
    batch = ctx.settings.embed.batch_size * 4
    for start in range(0, len(texts), batch):
        ctx.check_cancelled()
        vectors.append(embedder.embed_texts(spec, ctx.settings, texts[start : start + batch]))
        ctx.progress(min(1.0, (start + batch) / len(texts)))
    rel = _folder(ctx, "text", [params, _digest(texts)])
    folder = project_dir(ctx) / rel
    folder.mkdir(parents=True, exist_ok=True)
    np.save(folder / VECTORS, np.concatenate(vectors).astype(np.float32))
    return {
        **base,
        "status": "done",
        "dir": rel,
        "dim": spec.dim,
        "count": len(texts),
        "engine": embedder.engine_version(),
        "device": embedder.pick_device(ctx.settings.embed.device),
    }


def verify_embed_text(ctx: StageContext, cached: dict[str, Any]) -> bool:
    return _verify_files(ctx, cached, (VECTORS,))


def persist_embed_text(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    media = media_id(ctx)
    segments = list(
        session.execute(
            select(TranscriptSegment.index, TranscriptSegment.id)
            .where(TranscriptSegment.media_id == media)
            .order_by(TranscriptSegment.index)
        )
    )
    segment_ids = [segment_id for _, segment_id in segments]
    row = _set_row(session, media, "text")
    digest = _digest(result, segment_ids)  # segment ids change when the transcript is rewritten
    if row.digest == digest:
        # The stored rows are exactly this result's (also after a model-missing run in between).
        row.status = result["status"]
        return
    kept = ("done", "model_missing", "no_transcript")
    if result["status"] in ("model_missing", "no_transcript") and row.status in kept:
        row.status, row.details = result["status"], {**row.details, "reason": result.get("reason")}
        return
    session.execute(
        delete(Embedding).where(Embedding.media_id == media, Embedding.kind == "segment")
    )
    row.status, row.model, row.revision, row.digest = (
        result["status"],
        result["model"],
        result["revision"],
        digest,
    )
    row.details = {k: result[k] for k in ("engine", "device", "reason", "dim") if k in result}
    row.count = 0
    _clear_others(ctx, "text", result.get("dir"))
    if result["status"] != "done":
        return
    vectors = np.load(project_dir(ctx) / result["dir"] / VECTORS)
    # Segment rows are written one per transcript segment, `index` = its position, from the same
    # stage result the vectors were made from.
    for index, segment_id in segments:
        if index >= len(vectors):
            continue
        vector = vectors[index]
        session.add(
            Embedding(
                media_id=media,
                kind="segment",
                ref_id=str(segment_id),
                model=result["model"],
                dim=len(vector),
                vector=vector.tobytes(),
            )
        )
        row.count += 1


EMBED_STAGES = [
    Stage(
        "embed_visual",
        run_embed_visual,
        model_name="picture-embedding",
        model_version=f"{embedder.engine_version()}+{PIPELINE_VERSION}",
        params={"color_bins": list(embedder.HIST_BINS)},
        param_keys=("embed_visual",),
        scope_project=True,
        upstream=("keyframes",),
        verify=verify_embed_visual,
        persist=persist_embed_visual,
    ),
    Stage(
        "embed_text",
        run_embed_text,
        model_name="text-embedding",
        model_version=f"{embedder.engine_version()}+{PIPELINE_VERSION}",
        param_keys=("embed_text",),
        scope_project=True,
        upstream=("transcribe",),
        verify=verify_embed_text,
        persist=persist_embed_text,
    ),
    Stage(
        "tags",
        tag_stage.run_tags,
        model_name="zero-shot-tags",
        model_version=f"v{tagger.VOCAB_VERSION}+{PIPELINE_VERSION}",
        params={"templates": list(tagger.TEMPLATES)},
        param_keys=(),
        upstream=("embed_visual",),
        verify=tag_stage.verify_tags,
        persist=tag_stage.persist_tags,
    ),
]
