"""extract.hard_page (gpu, background): a local vision model transcribes a
page that OCR could not read. The result is stored as a draft and the job is
completed with review_required=True; nothing downstream may treat it as
verified text."""

from __future__ import annotations

import base64
import json
import urllib.request
from collections.abc import Callable
from typing import Any

from .. import TIER_VLM
from ..worker import Context
from .host import page_image

PROMPT = (
    "Transcribe all text on this page exactly as written, in reading order. "
    "Keep line breaks. Do not summarize, translate, correct or add anything. "
    "Write [illegible] for text you cannot read. If there is no text, reply with nothing."
)

Generate = Callable[[str, str, str, bytes], str]


def ollama_generate(base_url: str, model: str, prompt: str, image: bytes) -> str:
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "images": [base64.b64encode(image).decode()],
            "stream": False,
            "options": {"temperature": 0},
        }
    ).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/generate",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=900) as resp:
        return json.loads(resp.read())["response"]


def handle(
    payload: dict[str, Any], ctx: Context, generate: Generate | None = None
) -> tuple[dict[str, Any], bool]:
    sha, page = payload["sha256"], int(payload["page"])
    # The orchestrator leased this job for a specific model; use exactly that.
    model = ctx.job.get("resource", {}).get("model") or ctx.settings.vlm_model
    image = open(page_image(payload, ctx), "rb").read()
    text = (generate or ollama_generate)(ctx.settings.ollama_url, model, PROMPT, image)
    ctx.check()
    ctx.store.write_page(
        sha,
        page,
        TIER_VLM,
        text,
        {
            "tool": f"ollama:{model}",
            "draft": True,
            "ocr_confidence": payload.get("ocr_confidence"),
        },
    )
    return {"sha256": sha, "page": page, "model": model, "draft": True}, True
