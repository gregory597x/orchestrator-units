"""Job handlers, grouped by where the worker runs."""

from __future__ import annotations

from .. import JOB_FILE, JOB_HARD_PAGE, JOB_OCR_PAGE, JOB_TEXTUTIL
from ..worker import Handler


def for_role(role: str) -> dict[str, tuple[str, Handler]]:
    """Handlers a worker of the given role serves: job type -> (resource kind, fn).

    container: tier 1, deterministic extraction (PyMuPDF, pdftotext, pandoc)
    host:      tier 2 on the Mac (Apple Vision OCR, textutil)
    gpu:       tier 3, vision-model transcription of hard pages
    """
    if role == "container":
        from . import file

        return {JOB_FILE: ("cpu", file.handle)}
    if role == "host":
        from . import host

        return {
            JOB_OCR_PAGE: ("neural_engine", host.handle_ocr),
            JOB_TEXTUTIL: ("cpu", host.handle_textutil),
        }
    if role == "gpu":
        from . import vlm

        return {JOB_HARD_PAGE: ("gpu", vlm.handle)}
    raise ValueError(f"unknown role {role!r}; expected container, host or gpu")
