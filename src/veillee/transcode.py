"""ffmpeg and ffprobe wrappers.

The original upload is never touched. These produce the two derived files: FLAC
at 48kHz for the archive, and Opus at 48kbps for playing back in a browser.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

ARCHIVE_SAMPLE_RATE = 48_000
PLAYBACK_BITRATE = "48k"
_TIMEOUT_SECONDS = 3600


class TranscodeError(RuntimeError):
    """ffmpeg could not produce a usable file."""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False
        )
    except FileNotFoundError as exc:
        raise TranscodeError(f"{args[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise TranscodeError(f"{args[0]} timed out after {_TIMEOUT_SECONDS}s") from exc


def probe_duration(path: Path) -> float:
    """Duration in seconds. Returns 0.0 when the container does not declare one."""
    result = _run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ]
    )
    if result.returncode != 0:
        logger.warning("ffprobe could not read %s: %s", path.name, result.stderr.strip()[:200])
        return 0.0
    try:
        payload = json.loads(result.stdout)
        return float(payload.get("format", {}).get("duration", 0.0) or 0.0)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.0


def is_decodable(path: Path) -> bool:
    """True when ffmpeg can actually decode the file, not merely open it."""
    result = _run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"])
    return result.returncode == 0


def _transcode(
    source: Path, destination: Path, codec_args: list[str], label: str, container: str
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    # The temp name ends in .part, so ffmpeg cannot infer the container from the
    # extension; state it explicitly rather than letting it guess.
    result = _run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(source), "-vn",
            *codec_args, "-f", container, str(temporary),
        ]
    )
    if result.returncode != 0 or not temporary.exists() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise TranscodeError(
            f"could not produce {label} from {source.name}: {result.stderr.strip()[:300]}"
        )
    temporary.replace(destination)
    return destination


def to_flac(source: Path, destination: Path) -> Path:
    """Archival copy: FLAC, 48kHz, lossless."""
    return _transcode(
        source,
        destination,
        ["-ar", str(ARCHIVE_SAMPLE_RATE), "-c:a", "flac", "-compression_level", "5"],
        "FLAC",
        "flac",
    )


def to_opus(source: Path, destination: Path) -> Path:
    """Playback copy: Opus, small enough to stream over a phone connection."""
    return _transcode(
        source,
        destination,
        ["-ar", str(ARCHIVE_SAMPLE_RATE), "-c:a", "libopus", "-b:a", PLAYBACK_BITRATE],
        "Opus",
        "opus",
    )


def probe_codec(path: Path) -> str:
    """Codec name of the first audio stream, or '' when it cannot be determined."""
    result = _run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name", "-of", "json", str(path),
        ]
    )
    if result.returncode != 0:
        return ""
    try:
        streams = json.loads(result.stdout).get("streams", [])
        return str(streams[0].get("codec_name", "")) if streams else ""
    except (json.JSONDecodeError, IndexError, TypeError):
        return ""
