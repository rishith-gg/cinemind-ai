from pathlib import Path

import pytest

from cinemind.core.errors import InvalidInputError, PathNotAllowedError
from cinemind.core.paths import resolve_in_roots, sanitize_filename, validate_project_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("clip.mov", "clip.mov"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\win\\sys.ini", "sys.ini"),
        (".hidden", "hidden"),
        ("a b;rm -rf *.mp4", "a b_rm -rf _.mp4"),
        ("café.mp4", "cafe.mp4"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_rejects_empty_and_truncates_keeping_extension() -> None:
    with pytest.raises(InvalidInputError):
        sanitize_filename("///")
    with pytest.raises(InvalidInputError):
        sanitize_filename("..")
    out = sanitize_filename("x" * 300 + ".mp4", max_length=50)
    assert len(out) == 50 and out.endswith(".mp4")


def test_project_id_validation() -> None:
    assert validate_project_id("a" * 32)
    for bad in ("../x", "A" * 32, "abc", "a" * 31 + "/"):
        with pytest.raises(InvalidInputError):
            validate_project_id(bad)


def test_resolve_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    f = root / "a.mov"
    f.write_text("x")
    assert resolve_in_roots(f, [root]) == f.resolve()


def test_rejects_outside_dotdot_and_empty_roots(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("s")
    with pytest.raises(PathNotAllowedError):
        resolve_in_roots(tmp_path / "secret.txt", [root])
    with pytest.raises(PathNotAllowedError):
        resolve_in_roots(root / ".." / "secret.txt", [root])
    with pytest.raises(PathNotAllowedError):
        resolve_in_roots(root / "a.mov", [])


def test_rejects_symlink_escape_and_prefix_sibling(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.mov").write_text("x")
    (root / "link").symlink_to(outside)
    with pytest.raises(PathNotAllowedError):
        resolve_in_roots(root / "link" / "x.mov", [root])
    sibling = tmp_path / "media2"
    sibling.mkdir()
    with pytest.raises(PathNotAllowedError):  # "media2" shares a string prefix with "media"
        resolve_in_roots(sibling, [root])
