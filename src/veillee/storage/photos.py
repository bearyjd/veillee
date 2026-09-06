"""Photographs on disk.

Same promise as the recordings: the file he gave us is kept exactly as he gave
it, a derived copy is made for the screen, and a sidecar describes both so the
archive can be rebuilt without the database.

Photographs of photographs are the common case here - a phone held over a framed
print - so the derived copy is generous rather than thumbnail-sized, and the
original is never touched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.Image import Resampling

from ..config import Settings
from .answers import atomic_write
from .audio import sha256_file
from .paths import recording_dir_for

SIDECAR_VERSION = 1
VIEW_MAX_EDGE = 2000
VIEW_QUALITY = 82

SUPPORTED_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}
)


class PhotoError(ValueError):
    """The image could not be taken in. Nothing partial is left behind."""


@dataclass(frozen=True)
class Photograph:
    photo_id: str
    question_id: str
    created: str
    caption: str
    original_path: str
    view_path: str
    sidecar_path: str
    sha256_original: str
    sha256_view: str
    width: int
    height: int


def photo_paths(settings: Settings, photo_id: str, original_suffix: str) -> dict[str, Path]:
    directory = settings.photographs_dir / recording_dir_for(photo_id)
    suffix = original_suffix if original_suffix.startswith(".") else f".{original_suffix}"
    return {
        "original": directory / f"{photo_id}.orig{suffix}",
        "view": directory / f"{photo_id}.jpg",
        "sidecar": directory / f"{photo_id}.json",
    }


def make_view_copy(source: Path, destination: Path) -> tuple[int, int]:
    """A screen-sized JPEG. Returns the size of the derived image.

    Honours the EXIF orientation tag and then discards it, because a phone photo
    of a framed picture is almost always rotated, and a viewer that ignores the
    tag would show his great-grandparents on their side.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source) as image:
            upright = (ImageOps.exif_transpose(image) or image).convert("RGB")
            upright.thumbnail((VIEW_MAX_EDGE, VIEW_MAX_EDGE), Resampling.LANCZOS)
            temporary = destination.with_suffix(destination.suffix + ".part")
            upright.save(temporary, "JPEG", quality=VIEW_QUALITY, optimize=True)
            temporary.replace(destination)
            return upright.width, upright.height
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        destination.with_suffix(destination.suffix + ".part").unlink(missing_ok=True)
        raise PhotoError(
            "That file does not appear to be a photograph we can read. "
            "JPEG, PNG, HEIC and TIFF all work."
        ) from exc


def write_sidecar(
    sidecar_path: Path,
    *,
    photo_id: str,
    question_id: str,
    created: str,
    caption: str,
    original: Path,
    view: Path,
    width: int,
    height: int,
) -> None:
    payload = {
        "sidecar_version": SIDECAR_VERSION,
        "photo_id": photo_id,
        "question_id": question_id,
        "created": created,
        "caption": caption,
        "width": width,
        "height": height,
        "files": {
            "original": {
                "name": original.name,
                "sha256": sha256_file(original),
                "bytes": original.stat().st_size,
            },
            "view": {
                "name": view.name,
                "sha256": sha256_file(view),
                "bytes": view.stat().st_size,
            },
        },
    }
    atomic_write(sidecar_path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def read_sidecar(sidecar_path: Path) -> Photograph:
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    files = payload.get("files", {})
    directory = sidecar_path.parent

    def entry(kind: str, key: str) -> str:
        return str(files.get(kind, {}).get(key, ""))

    return Photograph(
        photo_id=str(payload["photo_id"]),
        question_id=str(payload["question_id"]),
        created=str(payload.get("created", "")),
        caption=str(payload.get("caption", "")),
        original_path=str(directory / entry("original", "name")),
        view_path=str(directory / entry("view", "name")),
        sidecar_path=str(sidecar_path),
        sha256_original=entry("original", "sha256"),
        sha256_view=entry("view", "sha256"),
        width=int(payload.get("width", 0)),
        height=int(payload.get("height", 0)),
    )


def iter_sidecars(settings: Settings) -> list[Path]:
    if not settings.photographs_dir.is_dir():
        return []
    return sorted(settings.photographs_dir.rglob("*.json"))


def verify_photograph(photo: Photograph) -> list[str]:
    problems: list[str] = []
    for label, path_text, expected in (
        ("original", photo.original_path, photo.sha256_original),
        ("view", photo.view_path, photo.sha256_view),
    ):
        path = Path(path_text)
        if not path.exists():
            problems.append(f"{photo.photo_id}: {label} file is missing ({path.name})")
        elif expected and sha256_file(path) != expected:
            problems.append(f"{photo.photo_id}: {label} checksum does not match")
    return problems
