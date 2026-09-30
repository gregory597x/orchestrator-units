"""Command-line entry points.

    extract-worker --role container|host|gpu
    extract-submit [--priority background] [--recursive] PATH...

Configuration comes from the environment:

    ORCH_URL             orchestrator base URL (default http://127.0.0.1:8780)
    ORCH_TOKEN / ORCH_TOKEN_FILE
    EXTRACT_STORE        result store root, as this worker sees it (required for workers)
    EXTRACT_PATH_MAP     HOST=LOCAL[,HOST=LOCAL...] for container workers
    OLLAMA_URL           default http://127.0.0.1:11434
    EXTRACT_VLM_MODEL    default qwen3-vl:8b
    EXTRACT_OCR_MIN_CONF default 0.5
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
from pathlib import Path

from . import JOB_FILE
from .client import CPU, OrchClient
from .handlers import for_role
from .paths import PathMap
from .store import ResultStore
from .worker import Context, Settings, run_forever


def _token() -> str | None:
    if tok := os.environ.get("ORCH_TOKEN"):
        return tok.strip()
    if path := os.environ.get("ORCH_TOKEN_FILE"):
        return Path(path).read_text().strip()
    return None


def _client() -> OrchClient:
    return OrchClient(os.environ.get("ORCH_URL", "http://127.0.0.1:8780"), _token())


def worker_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="extract-worker")
    ap.add_argument("--role", required=True, choices=["container", "host", "gpu"])
    ap.add_argument("--worker-id", default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    store_root = os.environ.get("EXTRACT_STORE")
    if not store_root:
        sys.exit("EXTRACT_STORE is required")
    settings = Settings(
        ollama_url=os.environ.get("OLLAMA_URL", Settings.ollama_url),
        vlm_model=os.environ.get("EXTRACT_VLM_MODEL", Settings.vlm_model),
        ocr_min_confidence=float(
            os.environ.get("EXTRACT_OCR_MIN_CONF", Settings.ocr_min_confidence)
        ),
    )
    ctx = Context(
        client=_client(),
        store=ResultStore(store_root),
        paths=PathMap.parse(os.environ.get("EXTRACT_PATH_MAP")),
        worker_id=args.worker_id or f"extract-{args.role}-{socket.gethostname()}-{os.getpid()}",
        settings=settings,
    )
    logging.getLogger(__name__).info("starting %s as %s", args.role, ctx.worker_id)
    run_forever(ctx, for_role(args.role))


def _walk(paths: list[str], recursive: bool):
    for p in map(Path, paths):
        if p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            yield from (f for f in it if f.is_file() and not f.name.startswith("."))
        elif p.is_file():
            yield p


def submit_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="extract-submit", description="Queue files for extraction.")
    ap.add_argument("paths", nargs="+", help="host paths of files or directories")
    ap.add_argument(
        "--priority", default="background", choices=["background", "normal", "interactive"]
    )
    ap.add_argument("--recursive", "-r", action="store_true")
    args = ap.parse_args(argv)

    client = _client()
    new = existing = 0
    for f in _walk(args.paths, args.recursive):
        st = f.stat()
        host = str(f.resolve())
        # Cheap key: resubmitting an unchanged file is a no-op. The worker
        # still dedupes by content hash, so copies are extracted once.
        key = f"{JOB_FILE}:{host}:{st.st_size}:{int(st.st_mtime)}"
        _, created = client.submit(
            JOB_FILE, CPU, {"path": host}, priority=args.priority, idempotency_key=key
        )
        new, existing = new + created, existing + (not created)
    print(f"queued {new} new, {existing} already known")
