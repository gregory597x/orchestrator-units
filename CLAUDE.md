# CLAUDE.md

Private modules for the orchestrator (github.com/gregory597x/orchestrator).
This repository holds work that is not published: MRI-related work, and
modules built on copyleft or otherwise incompatibly licensed software (e.g.
`extract/`, which uses AGPL PyMuPDF). Code that is Apache-2.0-compatible and
fine to publish belongs in the public orchestrator repository instead.

Each module lives in its own top-level directory (`<name>/`) as its own
package and talks to the orchestrator only through its HTTP job API
(`docs/job-api.md` there). Nothing here is imported by the orchestrator, and
nothing here imports it.

## Rules

- Units never import orchestrator internals; the HTTP job API is the only contract.
- Deterministic work (hashing, parsing, text layers, format conversion,
  verification) is plain code. Local models only draft; their results are
  marked `draft` and completed with `review_required`.
- Never delete or move user files. Workers read sources read-only and write
  only to their own result store.
- Handlers must be idempotent: a lease can expire mid-job and the job re-run.
  Key outputs by content hash; write atomically.
- No real paths, drive names or usernames in committed examples; use
  placeholders like `/Volumes/SOURCE_DRIVE`.

## Checks (per unit; CI runs the same)

```sh
cd extract && pip install -e '.[dev]' && ruff format --check . && ruff check . && pytest
```
