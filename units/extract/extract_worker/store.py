"""Result store keyed by content hash.

Layout (under EXTRACT_STORE):

    <sha[:2]>/<sha>/manifest.json          source paths, kind, page count
    <sha[:2]>/<sha>/pages/p0001.<tier>.txt page text from one tier
    <sha[:2]>/<sha>/pages/p0001.<tier>.json provenance (tool, confidence, draft)
    <sha[:2]>/<sha>/render/p0001.png       page images queued for OCR

Keying by SHA-256 means duplicate files are extracted once, and every write
is atomic and idempotent, so a job that runs twice (expired lease) is safe.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def sha256_file(path: str | os.PathLike, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class ResultStore:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)

    def doc_dir(self, sha: str) -> Path:
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError(f"not a sha256 hex digest: {sha!r}")
        return self.root / sha[:2] / sha

    def _page_base(self, sha: str, page: int, tier: str) -> Path:
        return self.doc_dir(sha) / "pages" / f"p{page:04d}.{tier}"

    def render_path(self, sha: str, page: int) -> Path:
        return self.doc_dir(sha) / "render" / f"p{page:04d}.png"

    def has_page(self, sha: str, page: int, tiers: list[str] | None = None) -> bool:
        pages = self.doc_dir(sha) / "pages"
        if not pages.is_dir():
            return False
        prefix = f"p{page:04d}."
        for f in pages.glob(prefix + "*.txt"):
            if tiers is None or f.name[len(prefix) : -len(".txt")] in tiers:
                return True
        return False

    def write_page(self, sha: str, page: int, tier: str, text: str, meta: dict[str, Any]) -> Path:
        base = self._page_base(sha, page, tier)
        _atomic_write(base.with_suffix(base.suffix + ".json"), json.dumps(meta, indent=2).encode())
        txt = base.with_suffix(base.suffix + ".txt")
        _atomic_write(txt, text.encode())
        return txt

    def read_manifest(self, sha: str) -> dict[str, Any] | None:
        path = self.doc_dir(sha) / "manifest.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def update_manifest(self, sha: str, source_path: str, **fields: Any) -> dict[str, Any]:
        """Merge fields into the manifest; the same content found at several
        paths accumulates all of them in `source_paths`."""
        manifest = self.read_manifest(sha) or {"sha256": sha, "source_paths": []}
        if source_path not in manifest["source_paths"]:
            manifest["source_paths"].append(source_path)
        manifest.update(fields)
        _atomic_write(self.doc_dir(sha) / "manifest.json", json.dumps(manifest, indent=2).encode())
        return manifest
