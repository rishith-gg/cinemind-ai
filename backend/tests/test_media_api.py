import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cinemind.api.app import create_app
from cinemind.core.config import Settings
from cinemind.db.base import make_engine, make_session_factory
from cinemind.jobs import queue
from cinemind.jobs.runner import run_job

ALL_CLIPS = [
    "a_h264.mp4",
    "b_prores.mov",
    "c_ntsc_noaudio.mkv",
    "d_audio.wav",
    "e_vfr.mp4",
    "f_corrupt.mp4",
]


@pytest.fixture
def api_settings(settings: Settings, footage: Path) -> Settings:
    settings.media_roots = [footage]
    settings.max_upload_mb = 1
    return settings


@pytest.fixture
def client(api_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(frontend_dist=None, settings=api_settings)) as c:
        yield c


@pytest.fixture
def pid(client: TestClient) -> str:
    return client.post("/api/projects", json={"name": "p"}).json()["id"]


def drain(settings: Settings) -> None:
    """Run every queued job inline (what the worker process does)."""
    factory = make_session_factory(make_engine(settings.db_path))
    while (job_id := queue.claim_next(factory)) is not None:
        run_job(factory, settings, job_id)


def tree_digest(root: Path) -> dict[str, str]:
    files = sorted(p for p in root.rglob("*") if p.is_file())
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def import_one(
    client: TestClient, pid: str, path: Path, mode: str = "reference"
) -> dict[str, object]:
    res = client.post(f"/api/projects/{pid}/media", json={"paths": [str(path)], "mode": mode})
    assert res.status_code == 201
    return res.json()["items"][0]


def test_browse_lists_roots_and_folders(client: TestClient, footage: Path) -> None:
    roots = client.get("/api/fs/browse").json()
    assert roots["roots"] == [str(footage.resolve())] and roots["parent"] is None
    listing = client.get("/api/fs/browse", params={"path": str(footage)}).json()
    names = {e["name"]: e for e in listing["entries"]}
    assert names["a_h264.mp4"]["is_media_candidate"]
    assert not names["notes.txt"]["is_media_candidate"]
    assert listing["parent"] is None  # at a root


def test_browse_rejects_outside_traversal_and_symlinks(
    client: TestClient, footage: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.mp4").write_bytes(b"x")
    for bad in (str(outside), str(footage / ".." / "x"), "/etc"):
        res = client.get("/api/fs/browse", params={"path": bad})
        assert res.status_code == 403 and res.json()["code"] == "path_not_allowed"
    assert client.get("/api/fs/browse", params={"path": "relative"}).status_code == 422
    link = footage / "link_out"
    link.symlink_to(outside)
    try:
        listing = client.get("/api/fs/browse", params={"path": str(footage)}).json()
        assert "link_out" not in {e["name"] for e in listing["entries"]}
        assert client.get("/api/fs/browse", params={"path": str(link)}).status_code == 403
    finally:
        link.unlink()


def test_import_folder_end_to_end(
    client: TestClient, api_settings: Settings, pid: str, footage: Path
) -> None:
    before = tree_digest(footage)
    res = client.post(f"/api/projects/{pid}/media", json={"paths": [str(footage)]})
    assert res.status_code == 201
    assert sorted(Path(i["path"]).name for i in res.json()["items"]) == ALL_CLIPS
    drain(api_settings)

    media = {m["filename"]: m for m in client.get(f"/api/projects/{pid}/media").json()}
    for name in ALL_CLIPS[:5]:
        m = media[name]
        assert m["job"]["status"] == "succeeded" and m["has_proxy"] and m["probed"], name
    ntsc = media["c_ntsc_noaudio.mkv"]
    assert (ntsc["fps_num"], ntsc["fps_den"]) == (30000, 1001)
    assert media["e_vfr.mp4"]["is_vfr"] and media["b_prores.mov"]["video_codec"] == "prores"
    bad = media["f_corrupt.mp4"]
    assert bad["job"]["status"] == "failed" and bad["job"]["error_code"] == "unreadable_media"
    assert "corrupt" in bad["job"]["error_message"]

    prores = media["b_prores.mov"]
    assert client.get(f"/api/media/{prores['id']}/poster").headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/media/{prores['id']}/strip").status_code == 200
    assert len(client.get(f"/api/media/{prores['id']}/waveform").json()["peaks"]) == 1000
    assert client.get(f"/api/media/{ntsc['id']}/waveform").status_code == 404  # no audio
    assert tree_digest(footage) == before  # sources untouched (rule 2)


def test_stream_supports_range_requests(
    client: TestClient, api_settings: Settings, pid: str, footage: Path
) -> None:
    import_one(client, pid, footage / "a_h264.mp4")
    drain(api_settings)
    media_id = client.get(f"/api/projects/{pid}/media").json()[0]["id"]
    url = f"/api/media/{media_id}/stream"
    full = client.get(url)
    assert full.status_code == 200 and full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-type"] == "video/mp4"
    part = client.get(url, headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == full.content[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(full.content)}"
    suffix = client.get(url, headers={"Range": "bytes=-50"})
    assert suffix.status_code == 206 and suffix.content == full.content[-50:]


def test_stream_before_processing_is_a_friendly_404(
    client: TestClient, pid: str, footage: Path
) -> None:
    import_one(client, pid, footage / "a_h264.mp4")
    media_id = client.get(f"/api/projects/{pid}/media").json()[0]["id"]
    res = client.get(f"/api/media/{media_id}/stream")
    assert res.status_code == 404 and "not been generated" in res.json()["message"]


def test_duplicate_detection_and_copy_mode(
    client: TestClient, api_settings: Settings, pid: str, footage: Path
) -> None:
    path = footage / "a_h264.mp4"
    first = import_one(client, pid, path)
    again = import_one(client, pid, path)
    assert not first["duplicate"] and again["duplicate"]
    assert again["media"]["id"] == first["media"]["id"]  # type: ignore[index]
    assert import_one(client, pid, path, "copy")["duplicate"]  # same content, still one asset
    assert len(client.get(f"/api/projects/{pid}/media").json()) == 1
    assert not list((api_settings.project_dir(pid) / "media").glob("*/*"))  # copy cleaned up

    other = client.post("/api/projects", json={"name": "q"}).json()["id"]
    item = import_one(client, other, path, "copy")["media"]
    stored = Path(item["path"])  # type: ignore[index]
    assert item["import_mode"] == "copy" and stored.is_file() and stored != path  # type: ignore[index]
    assert api_settings.project_dir(other) in stored.parents


def test_import_rejects_paths_outside_roots(client: TestClient, pid: str, tmp_path: Path) -> None:
    (tmp_path / "x.mp4").write_bytes(b"x")
    res = client.post(f"/api/projects/{pid}/media", json={"paths": [str(tmp_path / "x.mp4")]})
    assert res.status_code == 403 and res.json()["code"] == "path_not_allowed"
    res = client.post(f"/api/projects/{pid}/media", json={"paths": ["rel/x.mp4"]})
    assert res.status_code == 422


def test_upload_streams_and_enforces_limit(
    client: TestClient, api_settings: Settings, pid: str, footage: Path
) -> None:
    url = f"/api/projects/{pid}/media/upload"
    data = (footage / "a_h264.mp4").read_bytes()
    res = client.post(url, params={"filename": "../x y.mp4"}, content=data)
    assert res.status_code == 201
    item = res.json()["media"]
    assert item["filename"] == "x y.mp4" and item["import_mode"] == "upload"
    assert api_settings.project_dir(pid) in Path(item["path"]).parents
    drain(api_settings)
    assert client.get(f"/api/media/{item['id']}").json()["has_proxy"]

    big = b"\0" * (api_settings.max_upload_mb * 1024 * 1024 + 1)
    res = client.post(url, params={"filename": "big.mp4"}, content=big)
    assert res.status_code == 413 and res.json()["code"] == "too_large"
    assert len(client.get(f"/api/projects/{pid}/media").json()) == 1
    assert len(list((api_settings.project_dir(pid) / "media").iterdir())) == 1  # no leftovers
    assert client.post(url, params={"filename": "e.mp4"}, content=b"").status_code == 422


def test_missing_source_and_relink(client: TestClient, pid: str, footage: Path) -> None:
    src = footage / "temp_clip.mp4"
    src.write_bytes((footage / "a_h264.mp4").read_bytes())
    media_id = import_one(client, pid, src)["media"]["id"]  # type: ignore[index]
    moved = footage / "moved_clip.mp4"
    src.rename(moved)
    try:
        assert client.get(f"/api/media/{media_id}").json()["source_missing"] is True
        res = client.post(f"/api/media/{media_id}/relink", json={"path": str(moved)})
        assert res.status_code == 200 and res.json()["source_missing"] is False
        assert res.json()["filename"] == "moved_clip.mp4"
        wrong = client.post(
            f"/api/media/{media_id}/relink", json={"path": str(footage / "d_audio.wav")}
        )
        assert wrong.status_code == 422 and "does not match" in wrong.json()["message"]
    finally:
        moved.unlink(missing_ok=True)


def test_delete_media_keeps_the_source(
    client: TestClient, api_settings: Settings, pid: str, footage: Path
) -> None:
    src = footage / "a_h264.mp4"
    import_one(client, pid, src)
    media_id = client.get(f"/api/projects/{pid}/media").json()[0]["id"]
    assert client.delete(f"/api/media/{media_id}").status_code == 409  # still queued
    drain(api_settings)
    proxy_dir = api_settings.project_dir(pid) / "proxies"
    assert list(proxy_dir.iterdir())
    assert client.delete(f"/api/media/{media_id}").status_code == 204
    assert src.is_file() and not list(proxy_dir.iterdir())
    assert client.get(f"/api/media/{media_id}").status_code == 404


def test_process_enqueues_once(
    client: TestClient, api_settings: Settings, pid: str, footage: Path
) -> None:
    import_one(client, pid, footage / "a_h264.mp4")
    media_id = client.get(f"/api/projects/{pid}/media").json()[0]["id"]
    first = client.post(f"/api/media/{media_id}/process")
    second = client.post(f"/api/projects/{pid}/process")
    assert first.status_code == 202 and second.json()[0]["id"] == first.json()["id"]
    drain(api_settings)
    jobs = client.get("/api/jobs", params={"project_id": pid}).json()
    assert len(jobs) == 1 and jobs[0]["status"] == "succeeded"


def test_reference_symlink_leaving_roots_is_rejected(
    client: TestClient, pid: str, footage: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.mp4"
    outside.write_bytes((footage / "a_h264.mp4").read_bytes())
    link = footage / "sneaky.mp4"
    link.symlink_to(outside)
    try:
        res = client.post(f"/api/projects/{pid}/media", json={"paths": [str(link)]})
        assert res.status_code == 403 and res.json()["code"] == "path_not_allowed"
    finally:
        link.unlink()


def test_relink_rules(client: TestClient, pid: str, footage: Path, tmp_path: Path) -> None:
    media_id = import_one(client, pid, footage / "a_h264.mp4")["media"]["id"]  # type: ignore[index]
    outside = tmp_path / "copy.mp4"
    outside.write_bytes((footage / "a_h264.mp4").read_bytes())
    res = client.post(f"/api/media/{media_id}/relink", json={"path": str(outside)})
    assert res.status_code == 403
    other = client.post("/api/projects", json={"name": "q"}).json()["id"]
    copy_id = import_one(client, other, footage / "a_h264.mp4", "copy")["media"]["id"]  # type: ignore[index]
    res = client.post(f"/api/media/{copy_id}/relink", json={"path": str(footage / "a_h264.mp4")})
    assert res.status_code == 422


def test_playlist_files_are_rejected_not_followed(
    client: TestClient, api_settings: Settings, pid: str, footage: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.wav"
    secret.write_bytes((footage / "d_audio.wav").read_bytes())
    playlist = footage / "evil.mp4"
    playlist.write_text(f"ffconcat version 1.0\nfile '{secret}'\n")
    try:
        import_one(client, pid, playlist)
        drain(api_settings)
        media = next(
            m
            for m in client.get(f"/api/projects/{pid}/media").json()
            if m["filename"] == "evil.mp4"
        )
        assert media["job"]["status"] == "failed" and not media["has_proxy"]
    finally:
        playlist.unlink()


def test_unreadable_file_does_not_abort_the_batch(
    client: TestClient, pid: str, footage: Path
) -> None:
    locked = footage / "locked.mp4"
    locked.write_bytes(b"x" * 100)
    locked.chmod(0)
    try:
        res = client.post(
            f"/api/projects/{pid}/media",
            json={"paths": [str(locked), str(footage / "a_h264.mp4")]},
        )
        assert res.status_code == 201
        items = {Path(i["path"]).name: i for i in res.json()["items"]}
        assert items["locked.mp4"]["error_code"] == "unreadable_file"
        assert items["a_h264.mp4"]["media"] is not None
    finally:
        locked.chmod(0o644)
        locked.unlink()


def test_chunked_upload_without_content_length_hits_the_limit(
    client: TestClient, api_settings: Settings, pid: str
) -> None:
    def body() -> Iterator[bytes]:
        for _ in range(api_settings.max_upload_mb + 1):
            yield b"\0" * (1024 * 1024)

    res = client.post(
        f"/api/projects/{pid}/media/upload", params={"filename": "c.mp4"}, content=body()
    )
    assert res.status_code == 413
    assert not list((api_settings.project_dir(pid) / "media").iterdir())


def test_same_footage_in_two_projects_gets_its_own_artifacts(
    client: TestClient, api_settings: Settings, footage: Path
) -> None:
    ids: list[str] = []
    for name in ("one", "two"):
        project = client.post("/api/projects", json={"name": name}).json()["id"]
        import_one(client, project, footage / "a_h264.mp4")
        drain(api_settings)
        media = client.get(f"/api/projects/{project}/media").json()[0]
        assert media["has_proxy"]
        ids.append(project)
    for project in ids:
        assert len(list((api_settings.project_dir(project) / "proxies").iterdir())) == 1
