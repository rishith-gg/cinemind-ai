"""Vector indexes over the `embeddings` table (SPEC section 10: FAISS behind an interface).

Existing library: FAISS (`IndexFlatIP`, exact inner product; on unit-length vectors that is the
cosine similarity). Ours: the `VectorIndex` interface, a numpy fallback with the same results,
and building the index files from the database. The files under the project's `index/` folder
are derived data: `rebuild` recreates them from the rows at any time, and an index whose rows
changed is rebuilt the next time it is asked for.
"""

# faiss ships without type information.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.core.config import Settings
from cinemind.db.analysis import Embedding, VectorIndexRow
from cinemind.db.base import utcnow
from cinemind.db.models import MediaAsset
from cinemind.pipeline.actors import lock

log = logging.getLogger(__name__)

# Index kinds and what each holds. Colour histograms are compared pairwise, not searched.
KINDS = ("keyframe", "segment")


class VectorIndex(Protocol):
    backend: str

    def add(self, vectors: Any) -> None: ...

    def search(self, queries: Any, k: int) -> tuple[Any, Any]:
        """(scores, positions), each (n_queries, k); position -1 where fewer than k exist."""
        ...

    def save(self, path: Path) -> None: ...


class NumpyIndex:
    """Exact inner-product search with numpy; used when FAISS is not installed."""

    backend = "numpy"

    def __init__(self, dim: int) -> None:
        self.vectors: Any = np.zeros((0, dim), dtype=np.float32)

    def add(self, vectors: Any) -> None:
        self.vectors = np.concatenate([self.vectors, np.asarray(vectors, dtype=np.float32)])

    def search(self, queries: Any, k: int) -> tuple[Any, Any]:
        queries = np.atleast_2d(np.asarray(queries, dtype=np.float32))
        scores = queries @ self.vectors.T
        take = min(k, len(self.vectors))
        order = np.argsort(-scores, axis=1, kind="stable")[:, :take]
        top = np.take_along_axis(scores, order, axis=1)
        pad = k - take
        if pad:
            order = np.pad(order, ((0, 0), (0, pad)), constant_values=-1)
            top = np.pad(top, ((0, 0), (0, pad)), constant_values=-np.inf)
        return top, order

    def save(self, path: Path) -> None:
        with path.open("wb") as handle:
            np.save(handle, self.vectors)

    @classmethod
    def load(cls, path: Path) -> "NumpyIndex":
        vectors = np.load(path)
        index = cls(vectors.shape[1])
        index.vectors = vectors
        return index


class FaissIndex:
    backend = "faiss"

    def __init__(self, dim: int, raw: Any = None) -> None:
        import faiss

        self._faiss = faiss
        self.raw: Any = raw if raw is not None else faiss.IndexFlatIP(dim)

    def add(self, vectors: Any) -> None:
        self.raw.add(np.ascontiguousarray(vectors, dtype=np.float32))

    def search(self, queries: Any, k: int) -> tuple[Any, Any]:
        queries = np.ascontiguousarray(np.atleast_2d(queries), dtype=np.float32)
        scores, positions = self.raw.search(queries, k)
        return scores, positions

    def save(self, path: Path) -> None:
        self._faiss.write_index(self.raw, str(path))

    @classmethod
    def load(cls, path: Path) -> "FaissIndex":
        import faiss

        raw = faiss.read_index(str(path))
        return cls(raw.d, raw)


def faiss_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("faiss") is not None


def choose_backend(setting: str) -> str:
    """`[embed] index_backend`. "auto" is numpy on macOS: torch and faiss each bundle their own
    OpenMP runtime there, and the second one to start aborts the whole process (reproduced with
    torch 2.14.1 and faiss-cpu 1.15.1, D-079). Elsewhere FAISS if installed."""
    if setting != "auto":
        return setting if setting != "faiss" or faiss_available() else "numpy"
    if sys.platform == "darwin" or not faiss_available():
        return "numpy"
    return "faiss"


def new_index(dim: int, backend: str = "numpy") -> VectorIndex:
    return FaissIndex(dim) if backend == "faiss" else NumpyIndex(dim)


def _slug(model: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", model.lower())


def _rows(session: Session, project_id: str, kind: str, model: str) -> list[tuple[int, str, bytes]]:
    query = (
        select(Embedding.id, Embedding.ref_id, Embedding.vector)
        .join(MediaAsset, MediaAsset.id == Embedding.media_id)
        .where(
            MediaAsset.project_id == project_id, Embedding.kind == kind, Embedding.model == model
        )
        .order_by(Embedding.id)
    )
    return [(i, r, v) for i, r, v in session.execute(query)]


def models_in_use(session: Session, project_id: str, kind: str) -> list[str]:
    query = (
        select(Embedding.model)
        .join(MediaAsset, MediaAsset.id == Embedding.media_id)
        .where(MediaAsset.project_id == project_id, Embedding.kind == kind)
        .distinct()
    )
    return sorted(session.scalars(query))


def _digest(rows: list[tuple[int, str, bytes]]) -> str:
    h = hashlib.sha256()
    for row_id, ref, vector in rows:
        h.update(f"{row_id}:{ref}:".encode())
        h.update(hashlib.sha256(vector).digest())
    return h.hexdigest()


def current_digest(session: Session, project_id: str, kind: str, model: str) -> str:
    """The digest an index of these rows would have now (compare with the stored one)."""
    return _digest(_rows(session, project_id, kind, model))


def rebuild(
    session: Session,
    settings: Settings,
    project_id: str,
    kind: str,
    model: str,
    force: bool = False,
) -> VectorIndexRow | None:
    """Write the index file for (project, kind, model) from the rows, unless the stored one
    already holds exactly these rows. None (and any old file removed) if there are no rows.
    Takes the write lock first, so the API and the worker never build the same index at once.
    The caller commits."""
    lock(session)
    rows = _rows(session, project_id, kind, model)
    record = session.scalar(
        select(VectorIndexRow).where(
            VectorIndexRow.project_id == project_id,
            VectorIndexRow.kind == kind,
            VectorIndexRow.model == model,
        )
    )
    folder = settings.project_dir(project_id) / "index"
    if not rows:
        if record is not None:
            (settings.project_dir(project_id) / record.path).unlink(missing_ok=True)
            Path(settings.project_dir(project_id) / record.path).with_suffix(".ids.json").unlink(
                missing_ok=True
            )
            session.delete(record)
        return None
    digest = _digest(rows)
    if (
        record is not None
        and record.digest == digest
        and record.backend == choose_backend(settings.embed.index_backend)
        and not force
        and (settings.project_dir(project_id) / record.path).is_file()
    ):
        return record
    vectors = np.stack([np.frombuffer(v, dtype=np.float32) for _, _, v in rows])
    index = new_index(vectors.shape[1], choose_backend(settings.embed.index_backend))
    index.add(vectors)
    folder.mkdir(parents=True, exist_ok=True)
    # Each build gets its own pair of files (named by its digest), so an index and its ids always
    # belong together; the record is switched to them, then older builds are removed.
    stem = f"{kind}-{_slug(model)}"
    name = f"{stem}-{digest[:12]}"
    suffix = ".faiss" if index.backend == "faiss" else ".npy"
    partial = f".partial-{os.getpid()}"
    ids_tmp = folder / f"{name}.ids.json{partial}"
    ids_tmp.write_text(json.dumps([ref for _, ref, _ in rows]))
    ids_tmp.replace(folder / f"{name}.ids.json")
    tmp = folder / f"{name}{suffix}{partial}"
    index.save(tmp)
    tmp.replace(folder / f"{name}{suffix}")
    keep = {f"{name}{suffix}", f"{name}.ids.json"}
    ours = re.compile(rf"{re.escape(stem)}(-[0-9a-f]{{12}})?\.")  # this index's builds only
    for other in folder.iterdir():
        if other.name not in keep and ours.match(other.name):
            other.unlink(missing_ok=True)
    if record is None:
        record = VectorIndexRow(project_id=project_id, kind=kind, model=model)
        session.add(record)
    record.backend, record.dim, record.count = index.backend, int(vectors.shape[1]), len(rows)
    record.digest, record.path, record.built_at = digest, f"index/{name}{suffix}", utcnow()
    log.info(
        "built %s index %s for project %s (%d vectors)", index.backend, name, project_id, len(rows)
    )
    return record


def rebuild_project(
    session: Session, settings: Settings, project_id: str, force: bool = False
) -> list[VectorIndexRow]:
    """Every index of the project, plus removal of records whose rows are all gone."""
    built: list[VectorIndexRow] = []
    wanted = {(kind, model) for kind in KINDS for model in models_in_use(session, project_id, kind)}
    for record in session.scalars(
        select(VectorIndexRow).where(VectorIndexRow.project_id == project_id)
    ):
        wanted.add((record.kind, record.model))
    for kind, model in sorted(wanted):
        record = rebuild(session, settings, project_id, kind, model, force)
        if record is not None:
            built.append(record)
    return built


def load(settings: Settings, record: VectorIndexRow) -> tuple[VectorIndex, list[str]]:
    """The index file of a record and the ref ids of its positions."""
    path = settings.project_dir(record.project_id) / record.path
    ids = json.loads(path.with_suffix(".ids.json").read_text())
    index: VectorIndex = (
        FaissIndex.load(path) if record.backend == "faiss" else NumpyIndex.load(path)
    )
    return index, ids


def search(
    session: Session, settings: Settings, project_id: str, kind: str, model: str, query: Any, k: int
) -> list[tuple[str, float]]:
    """(ref id, cosine similarity) of the k nearest vectors; the index is brought up to date
    first."""
    record = rebuild(session, settings, project_id, kind, model)
    if record is None:
        return []
    index, ids = load(settings, record)
    scores, positions = index.search(np.asarray(query, dtype=np.float32), k)
    return [(ids[p], float(s)) for s, p in zip(scores[0], positions[0], strict=True) if p >= 0]
