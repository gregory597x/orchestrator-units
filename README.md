# orchestrator-units

Workers ("units") for the public
[orchestrator](https://github.com/gregory597x/orchestrator) whose licensing
keeps them out of it: they depend on copyleft or otherwise incompatibly
licensed software (e.g. PyMuPDF, AGPL), or are not meant to be published.
Each unit talks to the orchestrator only through its job API, so none of this
code is linked into the Apache-2.0 orchestrator and none of it has to be
published with it.

| Unit | What |
|---|---|
| [`extract`](extract) | Tiered text extraction: pdftotext/pandoc → Apple Vision OCR → local vision model |
