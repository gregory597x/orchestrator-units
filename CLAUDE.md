# CLAUDE.md

Private workers for the orchestrator (github.com/gregory597x/orchestrator).
Each unit lives in `units/<name>/` as its own package and talks to the
orchestrator only through its job API (`docs/job-api.md` there).

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
cd units/extract && pip install -e '.[dev]' && ruff format --check . && ruff check . && pytest
```
