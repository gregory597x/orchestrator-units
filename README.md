# orchestrator-units

Private workers ("units") for the public
[orchestrator](https://github.com/gregory597x/orchestrator). Each unit talks
to it only through the job API, so domain logic and copyleft dependencies
(e.g. PyMuPDF, AGPL) stay out of the public repository.

| Unit | What |
|---|---|
| [`units/extract`](units/extract) | Tiered text extraction: pdftotext/pandoc → Apple Vision OCR → local vision model |
