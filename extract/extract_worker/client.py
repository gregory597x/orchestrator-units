"""Minimal client for the orchestrator job API (docs/job-api.md in the
orchestrator repo). Standard library only."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

CPU = {"kind": "cpu"}
NEURAL_ENGINE = {"kind": "neural_engine"}


def gpu(model: str) -> dict[str, str]:
    return {"kind": "gpu", "model": model}


class OrchError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"orchestrator returned {status}: {message}")
        self.status = status


class OrchClient:
    def __init__(self, base_url: str, token: str | None, timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                message = json.loads(raw).get("error", "")
            except (ValueError, AttributeError):
                message = raw.decode(errors="replace")
            return e.code, {"error": message}

    def _ok(self, status: int, body: Any, *allowed: int) -> Any:
        if status not in allowed:
            raise OrchError(status, (body or {}).get("error", ""))
        return body

    def submit(
        self,
        job_type: str,
        resource: dict,
        payload: dict,
        *,
        priority: str = "normal",
        idempotency_key: str | None = None,
        max_attempts: int | None = None,
    ) -> tuple[dict, bool]:
        """Returns (job, created). `created` is False when the idempotency key
        matched an existing job."""
        body: dict[str, Any] = {
            "job_type": job_type,
            "priority": priority,
            "resource": resource,
            "payload": payload,
        }
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        if max_attempts:
            body["max_attempts"] = max_attempts
        status, resp = self._request("POST", "/v1/jobs", body)
        return self._ok(status, resp, 200, 201), status == 201

    def lease(self, worker_id: str, job_types: list[str], resources: list[str]) -> dict | None:
        status, body = self._request(
            "POST",
            "/v1/leases",
            {"worker_id": worker_id, "job_types": job_types, "resources": resources},
        )
        if status == 204:
            return None
        return self._ok(status, body, 200)["job"]

    def _lease_op(self, job_id: str, op: str, body: dict) -> bool:
        """True on success, False when the lease was lost (409)."""
        status, resp = self._request("POST", f"/v1/jobs/{job_id}/{op}", body)
        if status == 409:
            return False
        self._ok(status, resp, 200)
        return True

    def heartbeat(self, job_id: str, worker_id: str) -> bool:
        return self._lease_op(job_id, "heartbeat", {"worker_id": worker_id})

    def complete(self, job_id: str, worker_id: str, result: dict, review_required: bool) -> bool:
        return self._lease_op(
            job_id,
            "complete",
            {"worker_id": worker_id, "result": result, "review_required": review_required},
        )

    def fail(self, job_id: str, worker_id: str, error: str, retryable: bool) -> bool:
        return self._lease_op(
            job_id, "fail", {"worker_id": worker_id, "error": error, "retryable": retryable}
        )
