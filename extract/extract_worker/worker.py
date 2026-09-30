"""Generic lease loop: lease a job, heartbeat while the handler runs, then
complete or fail it."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .client import OrchClient
from .paths import PathMap
from .store import ResultStore

log = logging.getLogger(__name__)


class PermanentError(Exception):
    """The job can never succeed (unsupported file, missing file, ...):
    fail it without retrying."""


class LeaseLost(Exception):
    """The orchestrator took the lease back (expired or cancelled)."""


@dataclass
class Settings:
    ollama_url: str = "http://127.0.0.1:11434"
    vlm_model: str = "qwen3-vl:8b"
    ocr_min_confidence: float = 0.5
    render_dpi: int = 300


@dataclass
class Context:
    client: OrchClient
    store: ResultStore
    paths: PathMap
    worker_id: str
    settings: Settings = field(default_factory=Settings)
    job: dict[str, Any] = field(default_factory=dict)
    lost: threading.Event = field(default_factory=threading.Event)

    def check(self) -> None:
        """Handlers call this between units of work to stop early."""
        if self.lost.is_set():
            raise LeaseLost(self.job.get("id"))

    def submit(
        self, job_type: str, resource: dict, payload: dict, key: str, **kw: Any
    ) -> tuple[dict, bool]:
        """Queue a follow-up job at this job's priority unless overridden."""
        kw.setdefault("priority", self.job.get("priority", "normal"))
        return self.client.submit(job_type, resource, payload, idempotency_key=key, **kw)


# (resource kind, handler). The handler returns (result, review_required).
Handler = Callable[[dict[str, Any], Context], tuple[dict[str, Any], bool]]


def _heartbeat(ctx: Context, job_id: str, stop: threading.Event, every: float) -> None:
    while not stop.wait(every):
        try:
            if not ctx.client.heartbeat(job_id, ctx.worker_id):
                log.warning("lease lost for %s", job_id)
                ctx.lost.set()
                return
        except Exception:  # transient; the lease TTL covers a missed beat
            log.exception("heartbeat failed for %s", job_id)


def run_one(
    ctx: Context, handlers: dict[str, tuple[str, Handler]], heartbeat_every: float = 30.0
) -> bool:
    """Lease and process at most one job. Returns False when nothing was runnable."""
    job_types = sorted(handlers)
    resources = sorted({kind for kind, _ in handlers.values()})
    job = ctx.client.lease(ctx.worker_id, job_types, resources)
    if job is None:
        return False

    ctx.job, ctx.lost = job, threading.Event()
    stop = threading.Event()
    beat = threading.Thread(
        target=_heartbeat, args=(ctx, job["id"], stop, heartbeat_every), daemon=True
    )
    beat.start()
    try:
        _, handler = handlers[job["job_type"]]
        result, review = handler(job["payload"], ctx)
        ctx.check()
        ctx.client.complete(job["id"], ctx.worker_id, result, review)
    except LeaseLost:
        log.warning("abandoned %s: lease lost", job["id"])
    except PermanentError as e:
        ctx.client.fail(job["id"], ctx.worker_id, str(e), retryable=False)
    except Exception as e:
        log.exception("job %s failed", job["id"])
        ctx.client.fail(job["id"], ctx.worker_id, f"{type(e).__name__}: {e}", retryable=True)
    finally:
        stop.set()
        beat.join(timeout=1)
    return True


def run_forever(
    ctx: Context, handlers: dict[str, tuple[str, Handler]], idle_sleep: float = 5.0
) -> None:
    backoff = idle_sleep
    while True:
        try:
            if run_one(ctx, handlers):
                backoff = idle_sleep
                continue
        except Exception:
            log.exception("lease request failed")
        time.sleep(backoff)
        backoff = min(backoff * 2, 60.0)
