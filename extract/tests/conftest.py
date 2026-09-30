from __future__ import annotations

from typing import Any

import pytest

from extract_worker.paths import PathMap
from extract_worker.store import ResultStore
from extract_worker.worker import Context, Settings


class FakeClient:
    """In-memory stand-in for OrchClient that records every call."""

    def __init__(self, jobs: list[dict[str, Any]] | None = None):
        self.queue = list(jobs or [])
        self.submitted: list[dict[str, Any]] = []
        self.completed: list[tuple[str, dict, bool]] = []
        self.failed: list[tuple[str, str, bool]] = []
        self.heartbeat_ok = True
        self._keys: set[str] = set()

    def submit(
        self,
        job_type,
        resource,
        payload,
        *,
        priority="normal",
        idempotency_key=None,
        max_attempts=None,
    ):
        created = idempotency_key not in self._keys
        if idempotency_key:
            self._keys.add(idempotency_key)
        job = {
            "job_type": job_type,
            "resource": resource,
            "payload": payload,
            "priority": priority,
            "key": idempotency_key,
        }
        if created:
            self.submitted.append(job)
        return job, created

    def lease(self, worker_id, job_types, resources):
        for i, job in enumerate(self.queue):
            if job["job_type"] in job_types:
                return self.queue.pop(i)
        return None

    def heartbeat(self, job_id, worker_id):
        return self.heartbeat_ok

    def complete(self, job_id, worker_id, result, review_required):
        self.completed.append((job_id, result, review_required))
        return True

    def fail(self, job_id, worker_id, error, retryable):
        self.failed.append((job_id, error, retryable))
        return True


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def ctx(tmp_path, client) -> Context:
    return Context(
        client=client,
        store=ResultStore(tmp_path / "store"),
        paths=PathMap(),
        worker_id="test-worker",
        settings=Settings(),
        job={"id": "job-1", "priority": "normal"},
    )
