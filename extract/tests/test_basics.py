from __future__ import annotations

import pytest

from extract_worker.paths import PathMap
from extract_worker.quality import is_usable, text_score
from extract_worker.store import ResultStore


def test_quality_accepts_prose_and_rejects_junk_layers():
    prose = "The quick brown fox jumps over the lazy dog. Invoice #1234, total $56.78."
    assert is_usable(prose)
    assert not is_usable("")
    assert not is_usable("   \n  ")
    assert not is_usable("(cid:12)(cid:40)(cid:3)(cid:88)(cid:14)(cid:9)(cid:7) abc")
    assert not is_usable("�" * 50 + "abc")
    assert text_score("abc") == 1.0


def test_path_map_longest_prefix_and_round_trip():
    pm = PathMap.parse("/Volumes/Drive=/data/drive, /Volumes/Drive/Photos=/data/photos")
    assert pm.to_local("/Volumes/Drive/a/b.pdf") == "/data/drive/a/b.pdf"
    assert pm.to_local("/Volumes/Drive/Photos/x.jpg") == "/data/photos/x.jpg"
    assert pm.to_local("/elsewhere/x") == "/elsewhere/x"
    assert pm.to_host("/data/photos/x.jpg") == "/Volumes/Drive/Photos/x.jpg"
    assert pm.to_local("/Volumes/DriveOther/x") == "/Volumes/DriveOther/x", "no partial-name match"
    with pytest.raises(ValueError):
        PathMap.parse("no-equals-sign")


def test_store_pages_and_manifest_merge(tmp_path):
    store = ResultStore(tmp_path)
    sha = "ab" * 32
    assert not store.has_page(sha, 1)
    store.write_page(sha, 1, "vision", "hello", {"confidence": 0.9})
    assert store.has_page(sha, 1)
    assert store.has_page(sha, 1, ["vision"])
    assert not store.has_page(sha, 1, ["vlm"])
    store.update_manifest(sha, "/a/x.pdf", kind="pdf")
    m = store.update_manifest(sha, "/b/copy-of-x.pdf", kind="pdf")
    assert m["source_paths"] == ["/a/x.pdf", "/b/copy-of-x.pdf"]
    with pytest.raises(ValueError):
        store.doc_dir("../../etc")
