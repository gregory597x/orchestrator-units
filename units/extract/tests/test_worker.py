from __future__ import annotations

import time

from extract_worker.worker import PermanentError, run_one


def job(job_type="t.ok", id="j1"):
    return {"id": id, "job_type": job_type, "priority": "normal", "payload": {}}


def test_success_completes_with_review_flag(ctx, client):
    client.queue = [job()]
    handlers = {"t.ok": ("cpu", lambda p, c: ({"n": 1}, True))}
    assert run_one(ctx, handlers)
    assert client.completed == [("j1", {"n": 1}, True)]
    assert not run_one(ctx, handlers), "queue empty"


def test_errors_map_to_retryable_or_permanent(ctx, client):
    def boom(p, c):
        raise RuntimeError("transient")

    def bad(p, c):
        raise PermanentError("unsupported")

    client.queue = [job("t.boom", "a"), job("t.bad", "b")]
    handlers = {"t.boom": ("cpu", boom), "t.bad": ("cpu", bad)}
    run_one(ctx, handlers)
    run_one(ctx, handlers)
    assert client.failed == [("a", "RuntimeError: transient", True), ("b", "unsupported", False)]


def test_lost_lease_abandons_without_completing(ctx, client):
    client.queue = [job()]
    client.heartbeat_ok = False

    def slow(p, c):
        time.sleep(0.3)
        c.check()
        return {}, False

    run_one(ctx, {"t.ok": ("cpu", slow)}, heartbeat_every=0.05)
    assert client.completed == [] and client.failed == []
