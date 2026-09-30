"""extract.file (cpu, container): hash the file, then extract what can be
extracted deterministically and queue OCR for the rest."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pymupdf

from .. import JOB_OCR_PAGE, JOB_TEXTUTIL, TIER_PANDOC, TIER_PDFTOTEXT
from ..client import CPU, NEURAL_ENGINE
from ..quality import is_usable
from ..store import sha256_file
from ..worker import Context, PermanentError

PANDOC_SUFFIXES = {".docx", ".odt", ".epub", ".html", ".htm", ".rtf", ".md", ".rst", ".tex", ".org"}
# Formats pandoc cannot read; macOS textutil on the host can.
TEXTUTIL_SUFFIXES = {".doc", ".webarchive", ".wordml"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".bmp", ".gif", ".webp"}
TEXT_SUFFIXES = {".txt", ".csv", ".json", ".xml", ".log"}


def _pdftotext_pages(path: str) -> list[str]:
    """Whole document in one call; pages are separated by form feeds."""
    out = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
        capture_output=True,
        check=False,
        timeout=600,
    )
    if out.returncode != 0:
        return []
    pages = out.stdout.decode("utf-8", errors="replace").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()  # trailing form feed
    return pages


def _extract_pdf(local: str, host: str, sha: str, ctx: Context) -> dict[str, Any]:
    try:
        doc = pymupdf.open(local)
    except Exception as e:  # corrupt or not really a PDF
        raise PermanentError(f"cannot open PDF: {e}") from e
    with doc:
        if doc.needs_pass:
            raise PermanentError("PDF is password-protected")
        count = doc.page_count
        ctx.store.update_manifest(sha, host, kind="pdf", page_count=count)
        native = _pdftotext_pages(local)
        written, queued, skipped = 0, 0, 0
        for i in range(count):
            ctx.check()
            page_no = i + 1
            if ctx.store.has_page(sha, page_no):
                skipped += 1
                continue
            text = native[i] if i < len(native) else ""
            if not is_usable(text):
                # PyMuPDF's own text layer sometimes succeeds where pdftotext doesn't.
                alt = doc[i].get_text(sort=True)
                if is_usable(alt):
                    text = alt
            if is_usable(text):
                ctx.store.write_page(
                    sha,
                    page_no,
                    TIER_PDFTOTEXT,
                    text,
                    {"tool": "pdftotext -layout", "draft": False},
                )
                written += 1
                continue
            image = ctx.store.render_path(sha, page_no)
            if not image.exists():
                image.parent.mkdir(parents=True, exist_ok=True)
                doc[i].get_pixmap(dpi=ctx.settings.render_dpi).save(str(image))
            ctx.submit(
                JOB_OCR_PAGE,
                NEURAL_ENGINE,
                {"sha256": sha, "page": page_no, "image": "render"},
                key=f"{JOB_OCR_PAGE}:{sha}:{page_no}",
            )
            queued += 1
    return {
        "kind": "pdf",
        "pages": count,
        "text_pages": written,
        "ocr_queued": queued,
        "already_done": skipped,
    }


def _extract_pandoc(local: str, host: str, sha: str, suffix: str, ctx: Context) -> dict[str, Any]:
    ctx.store.update_manifest(sha, host, kind=suffix.lstrip("."), page_count=1)
    if ctx.store.has_page(sha, 1):
        return {"kind": suffix.lstrip("."), "already_done": 1}
    out = subprocess.run(
        ["pandoc", "--to", "plain", "--wrap", "none", local],
        capture_output=True,
        check=False,
        timeout=300,
    )
    if out.returncode != 0:
        raise PermanentError(f"pandoc failed: {out.stderr.decode(errors='replace')[:500]}")
    ctx.store.write_page(
        sha,
        1,
        TIER_PANDOC,
        out.stdout.decode("utf-8", errors="replace"),
        {"tool": "pandoc", "draft": False},
    )
    return {"kind": suffix.lstrip("."), "text_pages": 1}


def handle(payload: dict[str, Any], ctx: Context) -> tuple[dict[str, Any], bool]:
    host = payload.get("path")
    if not host:
        raise PermanentError("payload.path is required")
    local = ctx.paths.to_local(host)
    if not Path(local).is_file():
        raise PermanentError(f"file not found: {local}")
    sha = sha256_file(local)
    if payload.get("sha256") and payload["sha256"] != sha:
        raise PermanentError("file changed since it was queued (sha256 mismatch)")
    suffix = Path(local).suffix.lower()

    if suffix == ".pdf":
        result = _extract_pdf(local, host, sha, ctx)
    elif suffix in PANDOC_SUFFIXES:
        result = _extract_pandoc(local, host, sha, suffix, ctx)
    elif suffix in TEXT_SUFFIXES:
        ctx.store.update_manifest(sha, host, kind="text", page_count=1)
        text = Path(local).read_bytes().decode("utf-8", errors="replace")
        ctx.store.write_page(sha, 1, TIER_PANDOC, text, {"tool": "read", "draft": False})
        result = {"kind": "text", "text_pages": 1}
    elif suffix in IMAGE_SUFFIXES:
        ctx.store.update_manifest(sha, host, kind="image", page_count=1)
        queued = 0
        if not ctx.store.has_page(sha, 1):
            ctx.submit(
                JOB_OCR_PAGE,
                NEURAL_ENGINE,
                {"sha256": sha, "page": 1, "image": "source", "path": host},
                key=f"{JOB_OCR_PAGE}:{sha}:1",
            )
            queued = 1
        result = {"kind": "image", "ocr_queued": queued}
    elif suffix in TEXTUTIL_SUFFIXES:
        ctx.store.update_manifest(sha, host, kind=suffix.lstrip("."), page_count=1)
        queued = 0
        if not ctx.store.has_page(sha, 1):
            ctx.submit(
                JOB_TEXTUTIL, CPU, {"sha256": sha, "path": host}, key=f"{JOB_TEXTUTIL}:{sha}"
            )
            queued = 1
        result = {"kind": suffix.lstrip("."), "textutil_queued": queued}
    else:
        raise PermanentError(f"unsupported file type {suffix or '(none)'}")

    return {"sha256": sha, **result}, False
