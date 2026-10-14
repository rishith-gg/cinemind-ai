"""Zero-shot tags from picture vectors (SPEC section 5, stage 12).

Existing model: the picture model's text tower (CLIP or SigLIP), which places a short text in
the same space as a picture. Ours: the small fixed vocabulary, the prompts, how scores are formed,
and that a tag is only shown above a threshold set on labelled data by `eval/tag_calibration.py`
(stored in `tag_thresholds.json`). A tag with no evaluated threshold is never shown.

How a score is formed. Each group is a choice between texts, and a picture's score for a tag is
the share the model gives that tag inside its group (softmax of the similarities times the
model's own temperature):
- `setting` (indoor | outdoor), `time` (day | night / low light) and `shot_size` (close-up |
  medium | wide): each tag has its own descriptions.
- `place`: all 365 Places365 scene categories compete, and a place tag adds up the categories it
  stands for (beach + coast for "beach or coast"). The other categories soak up pictures of
  places outside the vocabulary.
Each description is used in three phrasings (TEMPLATES) whose vectors are averaged.
"""

# numpy's linear algebra functions are only partly typed.
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np

from cinemind.core.embed_config import EmbedModel

VOCAB_VERSION = "1"
TEMPLATES = ("a photo of {}.", "a video frame of {}.", "a film still of {}.")
THRESHOLDS_FILE = Path(__file__).with_name("tag_thresholds.json")
_PLACES_FILE = Path(__file__).with_name("places365_io.txt")


@dataclass(frozen=True)
class TagDef:
    name: str
    label: str
    group: str
    # Descriptions for the template (prompt groups), or Places365 categories (group `place`).
    texts: tuple[str, ...]


PROMPT_TAGS: tuple[TagDef, ...] = (
    TagDef("indoor", "Indoor", "setting", ("an indoor scene", "the inside of a room or building")),
    TagDef(
        "outdoor", "Outdoor", "setting", ("an outdoor scene", "a place outside in the open air")
    ),
    TagDef("day", "Daylight", "time", ("a scene in daylight", "a bright scene lit by the sun")),
    TagDef("night", "Night / low light", "time", ("a scene at night", "a dark scene in low light")),
    TagDef("close_up", "Close-up", "shot_size", ("a close-up shot", "a close view of a face")),
    TagDef(
        "medium", "Medium shot", "shot_size", ("a medium shot", "a person seen from the waist up")
    ),
    TagDef("wide", "Wide shot", "shot_size", ("a wide shot", "a distant view of a whole place")),
)
PLACE_TAGS: tuple[TagDef, ...] = (
    TagDef("beach", "Beach or coast", "place", ("/b/beach", "/c/coast")),
    TagDef("sea", "Open sea", "place", ("/o/ocean",)),
    TagDef("underwater", "Underwater", "place", ("/u/underwater/ocean_deep",)),
    TagDef("waterfall", "Waterfall", "place", ("/w/waterfall",)),
    TagDef("river_lake", "River or lake", "place", ("/r/river", "/l/lake/natural", "/c/creek")),
    TagDef(
        "pool", "Swimming pool", "place", ("/s/swimming_pool/indoor", "/s/swimming_pool/outdoor")
    ),
    TagDef(
        "forest",
        "Forest",
        "place",
        (
            "/f/forest/broadleaf",
            "/f/forest_path",
            "/f/forest_road",
            "/r/rainforest",
            "/b/bamboo_forest",
        ),
    ),
    TagDef(
        "mountain", "Mountain", "place", ("/m/mountain", "/m/mountain_path", "/m/mountain_snowy")
    ),
    TagDef(
        "field",
        "Field",
        "place",
        ("/f/field/cultivated", "/f/field/wild", "/w/wheat_field", "/h/hayfield", "/r/rice_paddy"),
    ),
    TagDef("street", "Street", "place", ("/s/street", "/a/alley", "/c/crosswalk", "/d/downtown")),
    TagDef("highway", "Highway", "place", ("/h/highway",)),
    TagDef(
        "vehicle",
        "Inside a vehicle",
        "place",
        ("/b/bus_interior", "/c/car_interior", "/t/train_interior", "/a/airplane_cabin"),
    ),
    TagDef("temple", "Temple", "place", ("/t/temple/asia", "/p/pagoda")),
    TagDef("kitchen", "Kitchen", "place", ("/k/kitchen", "/r/restaurant_kitchen")),
    TagDef("bedroom", "Bedroom", "place", ("/b/bedroom",)),
    TagDef("living_room", "Living room", "place", ("/l/living_room",)),
    TagDef(
        "restaurant",
        "Restaurant or café",
        "place",
        (
            "/r/restaurant",
            "/c/cafeteria",
            "/c/coffee_shop",
            "/f/fastfood_restaurant",
            "/f/food_court",
        ),
    ),
    TagDef("office", "Office", "place", ("/o/office", "/o/office_cubicles", "/h/home_office")),
    TagDef("classroom", "Classroom", "place", ("/c/classroom", "/l/lecture_room")),
    TagDef("stage", "Stage", "place", ("/s/stage/indoor", "/s/stage/outdoor")),
)
MODEL_TAGS = PROMPT_TAGS + PLACE_TAGS
BY_NAME = {tag.name: tag for tag in MODEL_TAGS}
GROUP_LABELS = {
    "setting": "Indoor / outdoor",
    "time": "Light",
    "shot_size": "Shot size",
    "place": "Place",
    "faces": "Faces",
    "speech": "Speech",
}


@cache
def places() -> tuple[tuple[str, int], ...]:
    """(category, 1 = indoor | 2 = outdoor) for the 365 Places365 categories, in their order."""
    rows: list[tuple[str, int]] = []
    for line in _PLACES_FILE.read_text().splitlines():
        if line and not line.startswith("#"):
            name, io = line.split()
            rows.append((name, int(io)))
    return tuple(rows)


def category_text(category: str) -> str:
    """'/s/swimming_pool/indoor' -> 'indoor swimming pool'."""
    parts = [part.replace("_", " ") for part in category.split("/")[2:]]
    return " ".join([*parts[1:], parts[0]])


def prompts() -> list[str]:
    """Every text the vocabulary needs, in a fixed order (see `score`)."""
    out = [t.format(d) for tag in PROMPT_TAGS for d in tag.texts for t in TEMPLATES]
    out += [t.format(category_text(c)) for c, _ in places() for t in TEMPLATES]
    return out


def class_vectors(prompt_vectors: Any) -> tuple[Any, Any]:
    """Average the prompt vectors per prompt tag and per Places category (unit length)."""
    n_t = len(TEMPLATES)
    tags: list[Any] = []
    row = 0
    for tag in PROMPT_TAGS:
        count = len(tag.texts) * n_t
        tags.append(prompt_vectors[row : row + count].mean(axis=0))
        row += count
    cats = prompt_vectors[row:].reshape(len(places()), n_t, -1).mean(axis=1)

    def unit(m: Any) -> Any:
        a: Any = np.asarray(m, dtype=np.float32)
        return a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)

    return unit(np.stack(tags)), unit(cats)


def _softmax(logits: Any) -> Any:
    shifted = logits - logits.max(axis=1, keepdims=True)
    e = np.exp(shifted)
    return e / e.sum(axis=1, keepdims=True)


def score(
    image_vectors: Any, tag_vectors: Any, category_vectors: Any, scale: float
) -> tuple[dict[str, Any], Any]:
    """Scores (0..1) per model tag for each picture, plus the Places365 probabilities
    (n, 365), kept for the "why" (the top categories)."""
    out: dict[str, Any] = {}
    sims = image_vectors @ tag_vectors.T
    for group in dict.fromkeys(t.group for t in PROMPT_TAGS):
        cols = [i for i, t in enumerate(PROMPT_TAGS) if t.group == group]
        probs = _softmax(scale * sims[:, cols])
        for j, i in enumerate(cols):
            out[PROMPT_TAGS[i].name] = probs[:, j]
    cat_probs = _softmax(scale * (image_vectors @ category_vectors.T))
    index = {name: i for i, (name, _) in enumerate(places())}
    for tag in PLACE_TAGS:
        out[tag.name] = cat_probs[:, [index[c] for c in tag.texts]].sum(axis=1)
    return out, cat_probs


def top_places(cat_probs_row: Any, k: int = 3) -> list[list[Any]]:
    order = [int(i) for i in np.argsort(-cat_probs_row)[:k]]
    return [[category_text(places()[i][0]), round(float(cat_probs_row[i]), 4)] for i in order]


# --- thresholds -------------------------------------------------------------------------------


def calibration_key(spec: EmbedModel) -> str:
    """Thresholds belong to one model revision and one vocabulary version."""
    return f"{spec.key}@{spec.revision[:12]}+v{VOCAB_VERSION}"


def load_thresholds(path: Path | None = None) -> dict[str, Any]:
    path = path or THRESHOLDS_FILE
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


def calibration_for(spec: EmbedModel, path: Path | None = None) -> dict[str, Any] | None:
    """The evaluated thresholds for this model, or None if it was never calibrated."""
    return load_thresholds(path).get("models", {}).get(calibration_key(spec))


def threshold_floor(name: str) -> float:
    """Lowest allowed threshold. In a two-way group (indoor/outdoor, day/night) the shares add up
    to 1, so a threshold under 0.5 could show both tags on one picture; 0.5 means a tag must also
    be the more likely of the two. Applied in the calibration, so the reported precision is that
    of this rule."""
    tag = BY_NAME.get(name)
    if tag is None or tag.group == "place":
        return 0.0
    return 1 / sum(1 for t in PROMPT_TAGS if t.group == tag.group)


# The thresholds are evaluated on single photos, so the decision is made per keyframe with exactly
# the evaluated rule; a shot shows the tag when more than half of its keyframes pass.
SHOT_RULE = (
    "shown when more than half of the shot's keyframes reach the threshold "
    "(on a tie, when their mean score does)"
)


def decide(
    name: str, keyframe_scores: Sequence[float], calibration: dict[str, Any] | None
) -> tuple[str, float | None]:
    """(status, threshold) for one tag of one shot: see `db.analysis.TAG_STATUSES`."""
    entry = (calibration or {}).get("tags", {}).get(name)
    if entry is None:
        return "not_evaluated", None
    threshold = float(entry["threshold"]) if entry.get("threshold") is not None else None
    if not entry.get("enabled") or threshold is None:
        return "disabled", threshold
    threshold = max(threshold, threshold_floor(name))
    if not keyframe_scores:
        return "below", threshold
    passing, total = sum(score >= threshold for score in keyframe_scores), len(keyframe_scores)
    # More than half pass; on a tie (two keyframes, one each way) the mean decides, so the two
    # tags of a two-way group, whose means add up to 1, are never both shown.
    tie_won = 2 * passing == total and sum(keyframe_scores) / total >= threshold
    return ("shown" if 2 * passing > total or tie_won else "below"), threshold
