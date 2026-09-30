from __future__ import annotations

import shutil

import pymupdf
import pytest

from extract_worker import JOB_HARD_PAGE, JOB_OCR_PAGE, JOB_TEXTUTIL
from extract_worker.handlers import file, host, vlm
from extract_worker.store import sha256_file
from extract_worker.worker import PermanentError

needs_tools = pytest.mark.skipif(
    not (shutil.which("pdftotext") and shutil.which("pandoc")),
    reason="pdftotext/pandoc not installed",
)

TEXT = "This page has a real text layer with plenty of ordinary words in it."


def make_pdf(path):
    """Page 1: real text. Page 2: an image only, like a scan."""
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), TEXT)
    scan = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
    pix.clear_with(200)
    scan.insert_image(scan.rect, pixmap=pix)
    doc.save(str(path))


@needs_tools
def test_pdf_native_page_extracted_scanned_page_queued_for_ocr(tmp_path, ctx, client):
    pdf = tmp_path / "mixed.pdf"
    make_pdf(pdf)
    result, review = file.handle({"path": str(pdf)}, ctx)
    sha = result["sha256"]
    assert (result["text_pages"], result["ocr_queued"], review) == (1, 1, False)
    assert (
        "real text layer" in (ctx.store.doc_dir(sha) / "pages" / "p0001.pdftotext.txt").read_text()
    )
    assert ctx.store.render_path(sha, 2).exists()
    (ocr,) = client.submitted
    assert ocr["job_type"] == JOB_OCR_PAGE
    assert ocr["resource"] == {"kind": "neural_engine"}
    assert ocr["payload"] == {"sha256": sha, "page": 2, "image": "render"}
    assert ocr["priority"] == "normal", "follow-ups inherit the job's priority"

    again, _ = file.handle({"path": str(pdf)}, ctx)
    assert again["already_done"] == 1 and len(client.submitted) == 1, "rerun is idempotent"


@needs_tools
def test_html_via_pandoc(tmp_path, ctx):
    page = tmp_path / "note.html"
    page.write_text("<html><body><h1>Title</h1><p>Some body text.</p></body></html>")
    result, _ = file.handle({"path": str(page)}, ctx)
    text = (ctx.store.doc_dir(result["sha256"]) / "pages" / "p0001.pandoc.txt").read_text()
    assert "Some body text." in text


def test_images_and_legacy_formats_are_routed_to_host(tmp_path, ctx, client):
    img = tmp_path / "scan.png"
    img.write_bytes(b"\x89PNG fake")
    doc = tmp_path / "old.doc"
    doc.write_bytes(b"legacy")
    file.handle({"path": str(img)}, ctx)
    file.handle({"path": str(doc)}, ctx)
    assert [j["job_type"] for j in client.submitted] == [JOB_OCR_PAGE, JOB_TEXTUTIL]
    assert client.submitted[0]["payload"]["image"] == "source"


def test_permanent_errors(tmp_path, ctx):
    with pytest.raises(PermanentError, match="not found"):
        file.handle({"path": str(tmp_path / "missing.pdf")}, ctx)
    odd = tmp_path / "data.xyz"
    odd.write_text("x")
    with pytest.raises(PermanentError, match="unsupported"):
        file.handle({"path": str(odd)}, ctx)
    with pytest.raises(PermanentError, match="changed"):
        file.handle({"path": str(odd), "sha256": "0" * 64}, ctx)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf at all")
    with pytest.raises(PermanentError, match="cannot open"):
        file.handle({"path": str(broken)}, ctx)


def _ocr_setup(tmp_path, ctx):
    img = tmp_path / "page.png"
    img.write_bytes(b"png")
    sha = sha256_file(img)
    return {"sha256": sha, "page": 1, "image": "source", "path": str(img)}, sha


def test_confident_ocr_is_stored(tmp_path, ctx, client):
    payload, sha = _ocr_setup(tmp_path, ctx)
    result, review = host.handle_ocr(
        payload, ctx, engine=lambda _: [("Hello world", 0.98), ("Line two", 0.9)]
    )
    assert not result["escalated"] and not review
    assert (
        ctx.store.doc_dir(sha) / "pages" / "p0001.vision.txt"
    ).read_text() == "Hello world\nLine two"
    assert client.submitted == []


def test_low_confidence_ocr_escalates_to_background_vlm(tmp_path, ctx, client):
    payload, sha = _ocr_setup(tmp_path, ctx)
    result, _ = host.handle_ocr(payload, ctx, engine=lambda _: [("H3ll0 w0r1d", 0.2)])
    assert result["escalated"]
    assert not ctx.store.has_page(sha, 1)
    (job,) = client.submitted
    assert job["job_type"] == JOB_HARD_PAGE
    assert job["resource"] == {"kind": "gpu", "model": "qwen3-vl:8b"}
    assert job["priority"] == "background"


def test_blank_page_is_recorded_not_escalated(tmp_path, ctx, client):
    payload, sha = _ocr_setup(tmp_path, ctx)
    result, _ = host.handle_ocr(payload, ctx, engine=lambda _: [])
    assert result["blank"] and client.submitted == []
    assert ctx.store.has_page(sha, 1, ["vision"])


def test_vlm_output_is_a_draft_that_requires_review(tmp_path, ctx):
    payload, sha = _ocr_setup(tmp_path, ctx)
    ctx.job = {"id": "j", "resource": {"kind": "gpu", "model": "qwen3-vl-32b-8k"}}
    seen = {}

    def fake_generate(url, model, prompt, image):
        seen["model"] = model
        return "Transcribed text"

    result, review = vlm.handle(payload, ctx, generate=fake_generate)
    assert review is True and result["draft"] is True
    assert seen["model"] == "qwen3-vl-32b-8k", "uses the model the job was leased for"
    meta = (ctx.store.doc_dir(sha) / "pages" / "p0001.vlm.json").read_text()
    assert '"draft": true' in meta
