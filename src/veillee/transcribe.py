"""Turning audio into a draft transcript.

Two backends. `local` runs faster-whisper on the CPU; `remote` posts to any
OpenAI-compatible /v1/audio/transcriptions endpoint. The default is local with
the `small` model, chosen so a cold start cannot hang: it is the largest model
that reliably loads and runs on a homelab CPU without a long stall.

Output is always a markdown transcript with segment timestamps, plus the raw
machine output alongside it, because the raw output is evidence and the markdown
is a convenience.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import Settings
from .storage.answers import atomic_write
from .storage.frontmatter import dumps
from .storage.paths import utc_now_iso

logger = logging.getLogger(__name__)

_model_cache: dict[str, object] = {}
REMOTE_TIMEOUT_SECONDS = 900


class TranscriptionError(RuntimeError):
    """Transcription failed. The job will be retried or dead-lettered."""


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcription:
    segments: tuple[Segment, ...]
    language: str
    backend: str
    model: str

    @property
    def text(self) -> str:
        return " ".join(segment.text.strip() for segment in self.segments).strip()


def format_timestamp(seconds: float) -> str:
    """'[00:04:12]' — coarse enough to be useful, fine enough to find a moment."""
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _load_local_model(settings: Settings) -> object:
    """Load and cache the whisper model. Cached because loading dominates cost."""
    key = f"{settings.whisper_model}:{settings.whisper_device}:{settings.whisper_compute_type}"
    if key not in _model_cache:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError(f"faster-whisper is not installed: {exc}") from exc
        try:
            _model_cache[key] = WhisperModel(
                settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            )
        except Exception as exc:  # noqa: BLE001 - surfaces as a retryable job failure
            raise TranscriptionError(
                f"could not load model {settings.whisper_model}: {exc}"
            ) from exc
    return _model_cache[key]


def transcribe_local(settings: Settings, audio_path: Path) -> Transcription:
    model = _load_local_model(settings)
    try:
        segments, info = model.transcribe(str(audio_path), vad_filter=True)  # type: ignore[attr-defined]
        collected = tuple(
            Segment(start=float(s.start), end=float(s.end), text=str(s.text).strip())
            for s in segments
        )
    except Exception as exc:  # noqa: BLE001 - any decode failure is retryable
        raise TranscriptionError(f"local transcription failed: {exc}") from exc
    return Transcription(
        segments=collected,
        language=str(getattr(info, "language", "") or ""),
        backend="local",
        model=settings.whisper_model,
    )


def transcribe_remote(settings: Settings, audio_path: Path) -> Transcription:
    if not settings.remote_base_url:
        raise TranscriptionError("VEILLEE_REMOTE_BASE_URL is not set")
    url = settings.remote_base_url.rstrip("/") + "/v1/audio/transcriptions"
    headers = (
        {"Authorization": f"Bearer {settings.remote_api_key}"} if settings.remote_api_key else {}
    )
    try:
        with audio_path.open("rb") as stream:
            response = httpx.post(
                url,
                headers=headers,
                files={"file": (audio_path.name, stream, "audio/flac")},
                data={"model": settings.remote_model, "response_format": "verbose_json"},
                timeout=REMOTE_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, OSError) as exc:
        raise TranscriptionError(f"remote transcription failed: {exc}") from exc

    raw_segments = payload.get("segments") or []
    if raw_segments:
        segments = tuple(
            Segment(
                start=float(item.get("start", 0.0)),
                end=float(item.get("end", 0.0)),
                text=str(item.get("text", "")).strip(),
            )
            for item in raw_segments
        )
    else:
        segments = (Segment(0.0, 0.0, str(payload.get("text", "")).strip()),)
    return Transcription(
        segments=segments,
        language=str(payload.get("language", "") or ""),
        backend="remote",
        model=settings.remote_model,
    )


def transcribe(settings: Settings, audio_path: Path) -> Transcription:
    """Run whichever backend is configured."""
    if not audio_path.exists():
        raise TranscriptionError(f"audio file is missing: {audio_path}")
    if settings.transcription_backend == "remote":
        return transcribe_remote(settings, audio_path)
    return transcribe_local(settings, audio_path)


def render_markdown(transcription: Transcription, *, recording_id: str, question_id: str,
                    created: str) -> str:
    """The transcript as it is stored: frontmatter, then timestamped segments."""
    metadata = {
        "recording_id": recording_id,
        "question_id": question_id,
        "created": created,
        "transcribed": utc_now_iso(),
        "backend": transcription.backend,
        "model": transcription.model,
        "language": transcription.language,
        "reviewed": False,
        "note": "Machine draft. Not shown to him. Correct it before trusting it.",
    }
    lines = [
        f"[{format_timestamp(segment.start)}] {segment.text}"
        for segment in transcription.segments
        if segment.text
    ]
    body = "\n\n".join(lines) if lines else "_(no speech detected)_"
    return dumps(metadata, body)


def write_transcript(
    settings: Settings,
    transcription: Transcription,
    *,
    recording_id: str,
    question_id: str,
    created: str,
    markdown_path: Path,
    json_path: Path,
) -> None:
    """Write both the markdown and the raw machine output."""
    atomic_write(
        markdown_path,
        render_markdown(
            transcription, recording_id=recording_id, question_id=question_id, created=created
        ),
    )
    raw = {
        "recording_id": recording_id,
        "question_id": question_id,
        "backend": transcription.backend,
        "model": transcription.model,
        "language": transcription.language,
        "transcribed": utc_now_iso(),
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text} for s in transcription.segments
        ],
        "text": transcription.text,
    }
    atomic_write(json_path, json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    _ = settings
