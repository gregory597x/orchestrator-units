"""Host <-> worker path translation.

Job payloads always carry *host* paths (what the Mac sees). A worker in a
container sees the same files under its bind-mount points, configured as
EXTRACT_PATH_MAP="/Volumes/Drive=/data/drive,/Users/me/Docs=/data/docs".
Host-side workers use an empty map.
"""

from __future__ import annotations

from pathlib import PurePosixPath


class PathMap:
    def __init__(self, pairs: list[tuple[str, str]] | None = None):
        # Longest prefix first so nested mounts win.
        self.pairs = sorted(
            ((h.rstrip("/"), w.rstrip("/")) for h, w in (pairs or [])),
            key=lambda p: len(p[0]),
            reverse=True,
        )

    @classmethod
    def parse(cls, spec: str | None) -> PathMap:
        pairs = []
        for item in (spec or "").split(","):
            item = item.strip()
            if not item:
                continue
            host, sep, local = item.partition("=")
            if not sep or not host or not local:
                raise ValueError(f"bad path map entry {item!r}; expected HOST=LOCAL")
            pairs.append((host, local))
        return cls(pairs)

    @staticmethod
    def _swap(path: str, pairs: list[tuple[str, str]]) -> str:
        p = PurePosixPath(path)
        for src, dst in pairs:
            try:
                rel = p.relative_to(src)
            except ValueError:
                continue
            return str(PurePosixPath(dst) / rel)
        return path

    def to_local(self, host_path: str) -> str:
        return self._swap(host_path, self.pairs)

    def to_host(self, local_path: str) -> str:
        reverse = sorted(((w, h) for h, w in self.pairs), key=lambda p: len(p[0]), reverse=True)
        return self._swap(local_path, reverse)
