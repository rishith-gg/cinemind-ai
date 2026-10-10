"""Ingest stage `faces` (SPEC section 5, stage 9): faces and face tracks of one clip.

The stage never downloads anything. Without the models on disk it records `model_missing`, the
clip's other results stay usable, and the next run tries again. Grouping the tracks of a whole
project into actors is not part of this stage (see `pipeline/actors.py`).
"""

import hashlib
import json
import shutil
from fractions import Fraction
from typing import Any

import numpy as np
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from cinemind.ai import faces as face_engine
from cinemind.core import face_config
from cinemind.core.config import Settings
from cinemind.core.errors import ModelMissingError
from cinemind.core.face_config import FaceConfig
from cinemind.db.models import Shot
from cinemind.db.people import Face, FacePin, FaceScan, FaceTrack
from cinemind.jobs.registry import Stage, StageContext
from cinemind.pipeline import face_scan
from cinemind.pipeline.shot_stages import stable_id
from cinemind.pipeline.stage_utils import media_id, project_dir, proxy_file, source_info

PIPELINE_VERSION = "2"  # 2: tracks link by highest total similarity; one folder per scan
# Settings that change which faces and tracks are found. The grouping settings are left out, so
# changing them regroups the project without scanning any video again.
_GROUPING = {"cluster_method", "cluster_distance"}


def job_params(settings: Settings) -> dict[str, Any]:
    """What a clip's faces depend on (part of the stage cache key)."""
    return {
        "engine": face_config.ENGINE,
        "revisions": [spec.revision for spec in face_config.FACE_MODELS],
        **settings.faces.model_dump(exclude=_GROUPING),
    }


def _face_dir(ctx: StageContext, params: dict[str, Any]) -> str:
    """One folder per parameter set and pipeline version: a cached result names files that can
    only have come from the scan it describes, whatever was scanned in between."""
    basis = json.dumps([params, face_engine.engine_version(), PIPELINE_VERSION], sort_keys=True)
    return f"faces/{media_id(ctx)}/{hashlib.sha256(basis.encode()).hexdigest()[:12]}"


def run_faces(ctx: StageContext) -> dict[str, Any]:
    params: dict[str, Any] = ctx.params.get("faces") or job_params(ctx.settings)
    base: dict[str, Any] = {
        "engine": params["engine"],
        "revisions": params["revisions"],
        "dir": None,
        "faces": [],
        "tracks": [],
    }
    shots = [(int(a), int(b)) for a, b in ctx.previous["shots"]["shots"]]
    if not source_info(ctx).has_video or not shots:
        return {**base, "status": "no_video"}
    try:
        engine = face_engine.FaceEngine(ctx.settings.models_path)
    except ModelMissingError as exc:
        return {**base, "status": "model_missing", "reason": exc.message}
    fields = set(FaceConfig.model_fields) - _GROUPING
    cfg = ctx.settings.faces.model_copy(update={k: v for k, v in params.items() if k in fields})
    rel = _face_dir(ctx, params)
    fps = Fraction(*ctx.previous["shots"]["fps"])
    found = face_scan.scan(
        proxy_file(ctx),
        fps,
        shots,
        cfg,
        engine,
        project_dir(ctx) / rel,
        ctx.progress,
        ctx.check_cancelled,
    )
    return {
        **base,
        **found,
        "status": "done" if found["tracks"] else "no_faces",
        "dir": rel,
        "fps": [fps.numerator, fps.denominator],
        "software": face_engine.engine_version(),
        "settings": cfg.model_dump(exclude=_GROUPING),
    }


def verify_faces(ctx: StageContext, cached: dict[str, Any]) -> bool:
    """Missing models are not a result worth keeping, and the files must still be there."""
    if cached.get("status") == "model_missing":
        return False
    if cached.get("dir") is None:
        return True
    folder = project_dir(ctx) / cached["dir"]
    names = [face_scan.TRACKS_FILE, *(track["crop"] for track in cached["tracks"])]
    return all((folder / name).is_file() for name in names)


def persist_faces(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    media = media_id(ctx)
    digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    row = session.get(FaceScan, media)
    if row is not None and row.digest == digest:
        return  # same result as stored: keep the tracks, their ids and their actors
    if row is not None and result["status"] == "model_missing":
        # Nothing was scanned. What an earlier scan found stays (tracks, actors, names) until a
        # real result replaces it; only the state and the reason are shown.
        row.status = "model_missing"
        row.details = {**row.details, "reason": result.get("reason")}
        return
    # A track that starts on the same face as before keeps its actor as a starting point, so a
    # rescan does not renumber every person; the next grouping still decides.
    before = dict(
        session.execute(
            select(FaceTrack.id, FaceTrack.actor_id).where(FaceTrack.media_id == media)
        ).all()
    )
    session.execute(delete(FaceTrack).where(FaceTrack.media_id == media))
    # Corrections are anchored to where the face was; they find their new tracks when the
    # project is grouped again.
    session.execute(update(FacePin).where(FacePin.media_id == media).values(track_id=None))
    if row is None:
        row = FaceScan(media_id=media)
        session.add(row)
    row.status = result["status"]
    row.frames_sampled = int(result.get("frames_sampled", 0))
    row.faces_detected = int(result.get("faces_detected", 0))
    row.faces_used = len(result["faces"])
    row.max_in_frame = int(result.get("max_in_frame", 0))
    row.digest = digest
    keys = ("engine", "revisions", "software", "settings", "rejected", "step_frames", "reason")
    row.details = {key: result[key] for key in keys if key in result}
    _remove_other_scans(ctx, result)
    if not result["tracks"]:
        return
    num, den = result["fps"]
    vectors = np.load(project_dir(ctx) / result["dir"] / face_scan.TRACKS_FILE)
    shots = {s.index: s for s in session.scalars(select(Shot).where(Shot.media_id == media))}
    members: dict[int, list[list[float]]] = {}
    for face in result["faces"]:
        members.setdefault(int(face[9]), []).append(face)
    for index, track in enumerate(result["tracks"]):
        faces = members[index]
        first, shot = faces[0], shots.get(track["shot"])
        end_s = (int(faces[-1][0]) + result["step_frames"]) * den / num
        session.add(
            FaceTrack(
                id=(track_id := stable_id(media, "face", int(first[0]), first[1], first[2])),
                media_id=media,
                actor_id=before.get(track_id),
                shot_id=shot.id if shot else None,
                index=index,
                start_s=int(first[0]) * den / num,
                end_s=min(end_s, shot.end_s) if shot else end_s,
                face_count=len(faces),
                embedding=vectors[index].astype(np.float32).tobytes(),
                crop_path=f"{result['dir']}/{track['crop']}",
                faces=[
                    Face(
                        media_id=media,
                        frame=int(f[0]),
                        time_s=int(f[0]) * den / num,
                        x=f[1],
                        y=f[2],
                        w=f[3],
                        h=f[4],
                        score=f[5],
                        size_px=f[6],
                        sharpness=f[7],
                        turn=f[8],
                    )
                    for f in faces
                ],
            )
        )


def _remove_other_scans(ctx: StageContext, result: dict[str, Any]) -> None:
    """Drop the folders of earlier parameter sets: no row points at them any more."""
    folder = project_dir(ctx) / "faces" / media_id(ctx)
    keep = str(result["dir"]).rsplit("/", 1)[-1] if result.get("dir") else None
    if folder.is_dir():
        for child in folder.iterdir():
            if child.name == keep:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)


FACE_STAGES = [
    Stage(
        "faces",
        run_faces,
        model_name=face_config.ENGINE,
        model_version=f"{face_engine.engine_version()}+{PIPELINE_VERSION}",
        params={"detect_floor": face_engine.DETECT_FLOOR, "crop_side": face_engine.CROP_SIDE},
        param_keys=("faces",),
        scope_project=True,
        upstream=("shots",),
        verify=verify_faces,
        persist=persist_faces,
    ),
]
