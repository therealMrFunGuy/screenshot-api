"""API key authentication and rate limiting using SQLite."""

import logging
import os
import sqlite3
import time
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("AUTH_DB_PATH", "/tmp/screenshot-api/auth.db")
MAX_FREE_DAILY = int(os.environ.get("MAX_FREE_DAILY", "100"))

# Tier limits (screenshots per day)
TIER_LIMITS = {
    "free": MAX_FREE_DAILY,       # 100/day per IP, no key needed
    "basic": 1000,                # 1,000/day
    "pro": 10000,                 # 10,000/day
    "enterprise": 100000,         # 100,000/day
}


class AuthDB:
    """SQLite-backed API key validation and rate limiting."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    key TEXT PRIMARY KEY,
                    tier TEXT NOT NULL DEFAULT 'basic',
                    owner TEXT,
                    created_at REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage (
                    key_or_ip TEXT NOT NULL,
                    date TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (key_or_ip, date)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_date ON usage(date)
            """)
            conn.commit()
        logger.info("Auth DB initialized at %s", self.db_path)

    def validate_key(self, api_key: str) -> Optional[dict]:
        """Validate an API key. Returns key info or None if invalid."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT key, tier, owner, active FROM api_keys WHERE key = ?",
                (api_key,),
            ).fetchone()
            if row and row["active"]:
                return dict(row)
        return None

    def create_key(self, api_key: str, tier: str = "basic", owner: str = "") -> bool:
        """Create a new API key."""
        if tier not in TIER_LIMITS:
            return False
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "INSERT INTO api_keys (key, tier, owner, created_at) VALUES (?, ?, ?, ?)",
                    (api_key, tier, owner, time.time()),
                )
                conn.commit()
            logger.info("Created API key for owner=%s tier=%s", owner, tier)
            return True
        except sqlite3.IntegrityError:
            return False

    def deactivate_key(self, api_key: str) -> bool:
        """Deactivate an API key."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "UPDATE api_keys SET active = 0 WHERE key = ?", (api_key,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def check_rate_limit(self, key_or_ip: str, tier: str = "free") -> dict:
        """Check if the given key/IP has exceeded its rate limit.

        Returns dict with: allowed (bool), used (int), limit (int), remaining (int)
        """
        today = date.today().isoformat()
        limit = TIER_LIMITS.get(tier, MAX_FREE_DAILY)

        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT count FROM usage WHERE key_or_ip = ? AND date = ?",
                (key_or_ip, today),
            ).fetchone()
            used = row[0] if row else 0

        remaining = max(0, limit - used)
        return {
            "allowed": used < limit,
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "tier": tier,
        }

    def increment_usage(self, key_or_ip: str) -> int:
        """Increment the usage counter. Returns the new count."""
        today = date.today().isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """INSERT INTO usage (key_or_ip, date, count) VALUES (?, ?, 1)
                   ON CONFLICT(key_or_ip, date) DO UPDATE SET count = count + 1""",
                (key_or_ip, today),
            )
            conn.commit()
            row = conn.execute(
                "SELECT count FROM usage WHERE key_or_ip = ? AND date = ?",
                (key_or_ip, today),
            ).fetchone()
            return row[0]

    def cleanup_old_usage(self, days_to_keep: int = 30) -> int:
        """Remove usage records older than N days."""
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute("DELETE FROM usage WHERE date < ?", (cutoff,))
            conn.commit()
            return cursor.rowcount

    def get_usage_stats(self) -> dict:
        """Return overall usage statistics."""
        today = date.today().isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            total_today = conn.execute(
                "SELECT COALESCE(SUM(count), 0) FROM usage WHERE date = ?", (today,)
            ).fetchone()[0]
            unique_users = conn.execute(
                "SELECT COUNT(DISTINCT key_or_ip) FROM usage WHERE date = ?", (today,)
            ).fetchone()[0]
            total_keys = conn.execute(
                "SELECT COUNT(*) FROM api_keys WHERE active = 1"
            ).fetchone()[0]
        return {
            "today_total_screenshots": total_today,
            "today_unique_users": unique_users,
            "active_api_keys": total_keys,
        }


# Global instance
_auth_db: Optional[AuthDB] = None


def get_auth_db() -> AuthDB:
    global _auth_db
    if _auth_db is None:
        _auth_db = AuthDB()
    return _auth_db
