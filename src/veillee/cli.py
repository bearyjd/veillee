"""`veillee` — the command line. Everything the son needs, nothing he does."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_settings

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format=LOG_FORMAT)


def cmd_reindex(_: argparse.Namespace) -> int:
    """Rebuild the SQLite index from data/ alone."""
    from .index import reindex

    settings = load_settings()
    report = reindex(settings)
    print(f"Indexed {report.answers} answers and {report.recordings} recordings.")
    if report.queued:
        print(f"Queued {report.queued} recording(s) for transcription.")
    for problem in report.problems:
        print(f"  problem: {problem}", file=sys.stderr)
    return 0 if report.ok else 1


def cmd_export(args: argparse.Namespace) -> int:
    """Write a dated export folder and verify its own manifest."""
    from .export import export, verify_manifest

    settings = load_settings()
    result = export(settings, Path(args.into) if args.into else None)
    problems = verify_manifest(result.directory)
    print(f"Exported to {result.directory}")
    print(f"  {result.answers} answers, {result.recordings} recordings, {result.files} files")
    if problems:
        for problem in problems:
            print(f"  problem: {problem}", file=sys.stderr)
        return 1
    print("  manifest verified")
    return 0


def cmd_verify(_: argparse.Namespace) -> int:
    """Re-checksum every recording against its sidecar."""
    from .storage import audio as audio_storage

    settings = load_settings()
    problems: list[str] = []
    checked = 0
    for sidecar in audio_storage.iter_sidecars(settings):
        try:
            recording = audio_storage.read_sidecar(sidecar)
        except (OSError, ValueError, KeyError) as exc:
            problems.append(f"{sidecar}: {exc}")
            continue
        problems.extend(audio_storage.verify_recording(recording))
        checked += 1
    print(f"Checked {checked} recording(s).")
    for problem in problems:
        print(f"  problem: {problem}", file=sys.stderr)
    return 1 if problems else 0


def cmd_worker(_: argparse.Namespace) -> int:
    from .worker import main as worker_main

    return worker_main()


def cmd_serve(args: argparse.Namespace) -> int:
    """Bind 127.0.0.1 only. Reached through `tailscale serve`, never Funnel."""
    import uvicorn

    uvicorn.run(
        "veillee.web.app:get_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="debug" if args.verbose else "info",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="veillee", description="A private oral history site.")
    parser.add_argument("-v", "--verbose", action="store_true", help="more logging")
    subcommands = parser.add_subparsers(dest="command", required=True)

    serve = subcommands.add_parser("serve", help="run the web site")
    serve.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1; do not change")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="reload on code changes")
    serve.set_defaults(handler=cmd_serve)

    reindex = subcommands.add_parser("reindex", help="rebuild the index from data/")
    reindex.set_defaults(handler=cmd_reindex)

    export = subcommands.add_parser("export", help="write a dated export folder")
    export.add_argument("--into", default=None, help="destination root (default: exports/)")
    export.set_defaults(handler=cmd_export)

    verify = subcommands.add_parser("verify", help="re-checksum every recording")
    verify.set_defaults(handler=cmd_verify)

    worker = subcommands.add_parser("worker", help="drain the transcription queue")
    worker.set_defaults(handler=cmd_worker)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    handler = args.handler
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
