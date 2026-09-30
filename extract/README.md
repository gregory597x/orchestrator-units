# extract-worker

Tiered text extraction, driven by the orchestrator's job API. Each tier is
the cheapest tool that can do the job; results are keyed by SHA-256, so
duplicate files are extracted once and every job is safe to re-run.

| Tier | Job type | Resource | Runs | Tool |
|---|---|---|---|---|
| 1 | `extract.file` | cpu | container | PyMuPDF routes each PDF page; `pdftotext -layout` for real text layers; `pandoc` for DOCX/ODT/EPUB/HTML/RTF/Markdown |
| 2 | `extract.ocr_page` | neural_engine | Mac host | Apple Vision OCR (`ocrmac`) for scans, images and junk text layers |
| 2 | `extract.textutil` | cpu | Mac host | macOS `textutil` for `.doc`, `.webarchive` |
| 3 | `extract.hard_page` | gpu (background) | Mac host | Local vision model (default `qwen3-vl:8b`) for pages OCR could not read |

Flow for a PDF: tier 1 hashes the file and checks every page. Pages with a
usable text layer are written immediately. Others are rendered to PNG and
queued for OCR. OCR results with a character-weighted confidence below
`EXTRACT_OCR_MIN_CONF` go to the vision model at background priority; blank
pages are recorded as blank, not escalated.

**Vision-model output is a draft.** It is stored as `pNNNN.vlm.txt` with
`"draft": true` in its metadata, and the job completes with
`review_required`. Nothing should treat it as verified text.

## Result store

```
<store>/<sha[:2]>/<sha>/manifest.json            source paths (all copies), kind, page count
<store>/<sha[:2]>/<sha>/pages/p0001.<tier>.txt   text from one tier
<store>/<sha[:2]>/<sha>/pages/p0001.<tier>.json  provenance: tool, confidence, draft
<store>/<sha[:2]>/<sha>/render/p0001.png         pages rendered for OCR
```

## Running it

Every role needs `ORCH_URL`, `ORCH_TOKEN` (or `ORCH_TOKEN_FILE`) and
`EXTRACT_STORE`. Job payloads carry **host** paths; container workers
translate them with `EXTRACT_PATH_MAP=HOST=LOCAL,...`.

```sh
# Tier 1, in containers (scale replicas as you like)
docker compose -f compose.example.yaml up -d --build

# Tiers 2 and 3, on the Mac
pip install -e '.[host]'
EXTRACT_STORE=~/extract-store extract-worker --role host
EXTRACT_STORE=~/extract-store OLLAMA_URL=http://127.0.0.1:11434 extract-worker --role gpu

# Queue files (background priority by default)
extract-submit -r /Volumes/SOURCE_DRIVE/some/folder
```

The orchestrator decides when each job may run: background work waits for
idle time, OCR is throttled while you use the Mac, and the vision model runs
only when its model mode allows.

## Development

```sh
pip install -e '.[dev]'
ruff format --check . && ruff check . && pytest
```

Tests use a fake orchestrator client and fake OCR/model engines; the PDF and
pandoc tests need `pdftotext` and `pandoc` installed.
