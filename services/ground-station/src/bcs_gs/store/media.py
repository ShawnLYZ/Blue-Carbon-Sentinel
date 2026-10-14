"""Local media files plus the media_objects upload queue (H3, H5)."""

from __future__ import annotations

from pathlib import Path

from bcs_gs.store.db import Database
from bcs_gs.store.repo import Repo

BUCKETS = frozenset({"captures", "futures", "evidence-packs", "sim-sessions"})


class MediaStore:
    """``root`` is the data root; objects live at ``<root>/var/media/<bucket>/<key>``."""

    def __init__(self, root: Path, db: Database) -> None:
        self.root = Path(root)
        self.db = db
        self._repo = Repo(db)

    @staticmethod
    def _check(bucket: str, key: str) -> None:
        if bucket not in BUCKETS:
            raise ValueError(f"unknown media bucket: {bucket!r}")
        if not key or key.startswith("/") or ":" in key or "\\" in key or "\x00" in key:
            raise ValueError(f"invalid media key: {key!r}")
        if any(seg in ("", ".", "..") for seg in key.split("/")):
            raise ValueError(f"invalid media key: {key!r}")

    def path(self, bucket: str, key: str) -> Path:
        self._check(bucket, key)
        media_root = self.root / "var" / "media"
        dest = media_root / bucket / Path(*key.split("/"))
        if not dest.resolve().is_relative_to((media_root / bucket).resolve()):
            raise ValueError(f"media path escapes root: {key!r}")
        return dest

    def put(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str,
        *,
        protected: bool = False,
        cloud: bool,
    ) -> Path:
        return self.put_staged(
            bucket, key, self.stage(bucket, key, data), content_type, protected=protected, cloud=cloud
        )

    def stage(self, bucket: str, key: str, data: bytes) -> Path:
        """Write ``data`` next to its destination as ``<name>.tmp`` and return that path. Nothing
        visible changes until ``put_staged`` (after the caller's database change has committed);
        on failure call ``discard``."""
        dest = self.path(bucket, key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(data)
        return tmp

    @staticmethod
    def discard(staged: Path) -> None:
        staged.unlink(missing_ok=True)

    def put_staged(
        self,
        bucket: str,
        key: str,
        staged: Path,
        content_type: str,
        *,
        protected: bool = False,
        cloud: bool,
    ) -> Path:
        """Move a staged file into place, then record its media_objects row."""
        dest = self.path(bucket, key)
        size = staged.stat().st_size
        staged.replace(dest)
        self._repo.upsert(
            "media_objects",
            {
                "bucket": bucket,
                "key": key,
                "local_path": f"var/media/{bucket}/{key}",
                "content_type": content_type,
                "bytes": size,
                "protected": protected,
                "state": "pending" if cloud else "local_only",
                "uploaded_at": None,
                "attempts": 0,
                "last_error": None,
            },
            sync=False,
        )
        return dest

    def promote(self, bucket: str, keys: list[str]) -> None:
        if not keys:
            return
        with self.db.tx() as conn:
            conn.executemany(
                "UPDATE media_objects SET state = 'pending' WHERE bucket = ? AND key = ? AND state = 'local_only'",
                [(bucket, k) for k in keys],
            )

    def set_protected(self, bucket: str, keys: list[str], protected: bool) -> None:
        """Mark objects protected (kept by the cloud media budget, A2) or release them."""
        if not keys:
            return
        with self.db.tx() as conn:
            conn.executemany(
                "UPDATE media_objects SET protected = ? WHERE bucket = ? AND key = ?",
                [(1 if protected else 0, bucket, k) for k in keys],
            )
