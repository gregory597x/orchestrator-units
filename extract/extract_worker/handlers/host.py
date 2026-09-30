"""Handlers that run on the macOS host, outside any container.

extract.ocr_page (neural_engine): Apple Vision OCR via ocrmac. Pages whose
    OCR confidence is too low are queued for the vision model.
extract.textutil (cpu): legacy formats via the built-in `textutil`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import JOB_HARD_PAGE, TIER_TEXTUTIL, TIER_VISION
from ..client import gpu
from ..worker import Context, PermanentError

# (text, confidence 0..1) per recognized line, in reading order.
OcrEngine = Callable[[str], list[tuple[str, float]]]


def vision_ocr(image_path: str) -> list[tuple[str, float]]:
    from ocrmac import ocrmac  # macOS only; imported lazily

    results = ocrmac.OCR(image_path, recognition_level="accurate").recognize()
    return [(text, float(conf)) for text, conf, _bbox in results]


def page_image(payload: dict[str, Any], ctx: Context) -> str:
    """Local path of the image to read: a rendered PDF page or the source image."""
    if payload.get("image") == "source":
        path = ctx.paths.to_local(payload["path"])
    else:
        path = str(ctx.store.render_path(payload["sha256"], int(payload["page"])))
    if not Path(path).is_file():
        raise PermanentError(f"page image not found: {path}")
    return path


def handle_ocr(
    payload: dict[str, Any], ctx: Context, engine: OcrEngine | None = None
) -> tuple[dict[str, Any], bool]:
    sha, page = payload["sha256"], int(payload["page"])
    image = page_image(payload, ctx)
    lines = (engine or vision_ocr)(image)
    text = "\n".join(t for t, _ in lines)
    chars = sum(len(t) for t, _ in lines)
    # Character-weighted mean, so one confident word can't mask a garbled page.
    confidence = sum(len(t) * c for t, c in lines) / chars if chars else 0.0

    if not chars:
        # Blank page (e.g. the back of a scanned sheet): record it, don't
        # spend GPU time on it.
        ctx.store.write_page(
            sha, page, TIER_VISION, "", {"tool": "apple-vision", "blank": True, "draft": False}
        )
        return {"sha256": sha, "page": page, "blank": True, "escalated": False}, False

    if confidence >= ctx.settings.ocr_min_confidence:
        ctx.store.write_page(
            sha,
            page,
            TIER_VISION,
            text,
            {"tool": "apple-vision", "confidence": round(confidence, 4), "draft": False},
        )
        return {"sha256": sha, "page": page, "confidence": confidence, "escalated": False}, False

    # Hard page: the vision model is background-only and its output a draft.
    ctx.submit(
        JOB_HARD_PAGE,
        gpu(ctx.settings.vlm_model),
        {**payload, "ocr_confidence": confidence},
        key=f"{JOB_HARD_PAGE}:{sha}:{page}",
        priority="background",
    )
    return {"sha256": sha, "page": page, "confidence": confidence, "escalated": True}, False


def handle_textutil(payload: dict[str, Any], ctx: Context) -> tuple[dict[str, Any], bool]:
    sha = payload["sha256"]
    local = ctx.paths.to_local(payload["path"])
    if not Path(local).is_file():
        raise PermanentError(f"file not found: {local}")
    out = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", local],
        capture_output=True,
        check=False,
        timeout=300,
    )
    if out.returncode != 0:
        raise PermanentError(f"textutil failed: {out.stderr.decode(errors='replace')[:500]}")
    ctx.store.write_page(
        sha,
        1,
        TIER_TEXTUTIL,
        out.stdout.decode("utf-8", errors="replace"),
        {"tool": "textutil", "draft": False},
    )
    return {"sha256": sha, "text_pages": 1}, False
