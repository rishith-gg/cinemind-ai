"""Ingest stages `shots` and `keyframes` (SPEC section 5, stages 3 and 5)."""

import hashlib
from fractions import Fraction
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cinemind.db.models import Keyframe, Shot
from cinemind.jobs.registry import Stage, StageContext
from cinemind.pipeline import shots as shot_lib
from cinemind.pipeline.stage_utils import media_id, project_dir, proxy_file, source_info

PIPELINE_VERSION = "1"


def stable_id(*parts: object) -> str:
    """Deterministic id, so re-running detection keeps ids that other tables point at."""
    return hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()[:32]


def _proxy_fps(ctx: StageContext) -> Fraction:
    return Fraction(*ctx.previous["proxy"]["fps"])


# --- shots ------------------------------------------------------------------------------------


def run_shots(ctx: StageContext) -> dict[str, Any]:
    if not source_info(ctx).has_video:
        return {"fps": None, "frames": 0, "shots": [], "detection": {}}
    fps = _proxy_fps(ctx)
    found = shot_lib.detect_shots(
        proxy_file(ctx),
        fps,
        str(ctx.params.get("shot_detector", ctx.settings.shot_detector)),
        ctx.params.get("shot_threshold", ctx.settings.shot_threshold),
        float(ctx.params.get("shot_min_len_s", ctx.settings.shot_min_len_s)),
        ctx.progress,
        ctx.check_cancelled,
    )
    return {
        "fps": [fps.numerator, fps.denominator],
        "frames": found.frames,
        "shots": [list(s) for s in found.shots],
        "detection": {
            "library": "PySceneDetect",
            "version": shot_lib.SCENEDETECT_VERSION,
            "detector": found.detector,
            "threshold": found.threshold,
            "min_len_frames": found.min_len_frames,
            "analysed": "proxy",
        },
    }


def persist_shots(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    media = media_id(ctx)
    existing = {s.id: s for s in session.scalars(select(Shot).where(Shot.media_id == media))}
    keep: set[str] = set()
    if result["fps"]:
        num, den = result["fps"]
        for index, (start, end) in enumerate(result["shots"]):
            shot_id = stable_id(media, start, end)
            keep.add(shot_id)
            shot = existing.get(shot_id)
            if shot is None:
                shot = Shot(id=shot_id, media_id=media)
                session.add(shot)
            shot.index, shot.start_frame, shot.end_frame = index, start, end
            shot.start_s, shot.end_s = start * den / num, end * den / num
            shot.fps_num, shot.fps_den = num, den
            shot.detection = result["detection"]
    gone = [shot_id for shot_id in existing if shot_id not in keep]
    if gone:
        session.execute(delete(Shot).where(Shot.id.in_(gone)))


# --- keyframes --------------------------------------------------------------------------------


def _keyframe_dir(ctx: StageContext) -> str:
    return f"keyframes/{media_id(ctx)}"


def run_keyframes(ctx: StageContext) -> dict[str, Any]:
    shots = [(int(a), int(b)) for a, b in ctx.previous["shots"]["shots"]]
    if not shots:
        return {"dir": None, "keyframes": []}
    rel = _keyframe_dir(ctx)
    found = shot_lib.extract_keyframes(
        proxy_file(ctx),
        shots,
        _proxy_fps(ctx),
        int(ctx.params.get("keyframes_per_shot", ctx.settings.keyframes_per_shot)),
        project_dir(ctx) / rel,
        ctx.progress,
        ctx.check_cancelled,
    )
    return {"dir": rel, "keyframes": found}


def verify_keyframes(ctx: StageContext, result: dict[str, Any]) -> bool:
    if result["dir"] is None:
        return True
    folder = project_dir(ctx) / result["dir"]
    return all((folder / k["file"]).is_file() for k in result["keyframes"])


def persist_keyframes(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    media = media_id(ctx)
    session.execute(delete(Keyframe).where(Keyframe.media_id == media))
    shots = list(session.scalars(select(Shot).where(Shot.media_id == media)))
    by_index = {s.index: s for s in shots}
    for item in result["keyframes"]:
        shot = by_index.get(item["shot"])
        if shot is None:
            continue
        session.add(
            Keyframe(
                id=stable_id(shot.id, item["slot"], item["frame"]),
                shot_id=shot.id,
                media_id=media,
                slot=item["slot"],
                frame=item["frame"],
                time_s=item["frame"] * shot.fps_den / shot.fps_num,
                path=f"{result['dir']}/{item['file']}",
                sharpness=item["sharpness"],
            )
        )


SHOT_STAGES = [
    Stage(
        "shots",
        run_shots,
        model_name="pyscenedetect",
        model_version=f"{shot_lib.SCENEDETECT_VERSION}+{PIPELINE_VERSION}",
        param_keys=("shot_detector", "shot_threshold", "shot_min_len_s"),
        persist=persist_shots,
    ),
    Stage(
        "keyframes",
        run_keyframes,
        model_name="opencv-laplacian",
        model_version=PIPELINE_VERSION,
        params={
            "candidates": shot_lib.CANDIDATES_PER_ANCHOR,
            "window_s": shot_lib.ANCHOR_WINDOW_S,
        },
        param_keys=("keyframes_per_shot",),
        scope_project=True,
        verify=verify_keyframes,
        persist=persist_keyframes,
    ),
]
