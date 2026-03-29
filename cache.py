"""File-based caching with TTL for screenshot results."""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/screenshot-cache")
CACHE_TTL = int(os.environ.get("CACHE_TTL", "3600"))  # 1 hour default


class FileCache:
    """Simple file-based cache with TTL expiration."""

    def __init__(self, cache_dir: str = CACHE_DIR, ttl: int = CACHE_TTL):
        self.cache_dir = Path(cache_dir)
        self.ttl = ttl
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        logger.info("Cache initialized at %s with TTL=%ds", self.cache_dir, self.ttl)

    def _path_for_key(self, key: str, extension: str = "png") -> Path:
        # Organize into subdirectories using first 2 chars of hash
        subdir = self.cache_dir / key[:2]
        subdir.mkdir(exist_ok=True)
        return subdir / f"{key}.{extension}"

    async def get(self, key: str, extension: str = "png") -> Optional[bytes]:
        """Retrieve cached data if it exists and hasn't expired."""
        path = self._path_for_key(key, extension)
        if not path.exists():
            return None

        # Check TTL
        age = time.time() - path.stat().st_mtime
        if age > self.ttl:
            logger.debug("Cache expired for key %s (age=%.0fs)", key[:12], age)
            try:
                path.unlink()
            except OSError:
                pass
            return None

        try:
            data = await asyncio.to_thread(path.read_bytes)
            logger.debug("Cache hit for key %s", key[:12])
            return data
        except Exception as e:
            logger.warning("Cache read error for key %s: %s", key[:12], e)
            return None

    async def put(self, key: str, data: bytes, extension: str = "png") -> None:
        """Store data in the cache."""
        path = self._path_for_key(key, extension)
        try:
            await asyncio.to_thread(path.write_bytes, data)
            logger.debug("Cached key %s (%d bytes)", key[:12], len(data))
        except Exception as e:
            logger.warning("Cache write error for key %s: %s", key[:12], e)

    async def cleanup(self) -> int:
        """Remove expired entries. Returns count of removed files."""
        removed = 0
        now = time.time()

        def _do_cleanup():
            nonlocal removed
            for subdir in self.cache_dir.iterdir():
                if not subdir.is_dir():
                    continue
                for f in subdir.iterdir():
                    if f.is_file() and (now - f.stat().st_mtime) > self.ttl:
                        try:
                            f.unlink()
                            removed += 1
                        except OSError:
                            pass
                # Remove empty subdirectories
                try:
                    if subdir.is_dir() and not any(subdir.iterdir()):
                        subdir.rmdir()
                except OSError:
                    pass

        await asyncio.to_thread(_do_cleanup)
        if removed:
            logger.info("Cache cleanup removed %d expired entries", removed)
        return removed

    async def stats(self) -> dict:
        """Return cache statistics."""
        total_files = 0
        total_bytes = 0
        expired = 0
        now = time.time()

        def _calc():
            nonlocal total_files, total_bytes, expired
            for subdir in self.cache_dir.iterdir():
                if not subdir.is_dir():
                    continue
                for f in subdir.iterdir():
                    if f.is_file():
                        total_files += 1
                        total_bytes += f.stat().st_size
                        if (now - f.stat().st_mtime) > self.ttl:
                            expired += 1

        await asyncio.to_thread(_calc)
        return {
            "total_entries": total_files,
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / (1024 * 1024), 2),
            "expired_entries": expired,
            "cache_dir": str(self.cache_dir),
            "ttl_seconds": self.ttl,
        }


# Global cache instance
_cache: Optional[FileCache] = None


def get_cache() -> FileCache:
    global _cache
    if _cache is None:
        _cache = FileCache()
    return _cache
