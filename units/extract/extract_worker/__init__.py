"""Tiered text extraction for the orchestrator job API.

Tier 1 (cpu, container): born-digital PDFs via pdftotext, routed per page by
    PyMuPDF; office/markup formats via pandoc.
Tier 2 (neural_engine, macOS host): Apple Vision OCR for scans and images;
    legacy formats via textutil.
Tier 3 (gpu, background): a local vision model transcribes pages OCR could
    not read. Its output is a draft and always flagged for review.
"""

JOB_FILE = "extract.file"
JOB_OCR_PAGE = "extract.ocr_page"
JOB_TEXTUTIL = "extract.textutil"
JOB_HARD_PAGE = "extract.hard_page"

TIER_PDFTOTEXT = "pdftotext"
TIER_PANDOC = "pandoc"
TIER_TEXTUTIL = "textutil"
TIER_VISION = "vision"
TIER_VLM = "vlm"
