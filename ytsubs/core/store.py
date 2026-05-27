from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from .models import ChannelCandidate, Video, parse_datetime, utcnow


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Auto-backup on startup: keep up to 5 rotating backups (.bak.1 to .bak.5)
        if self.path.exists() and self.path.stat().st_size > 0:
            try:
                import shutil
                for i in range(4, 0, -1):
                    old_bak = self.path.with_name(self.path.name + f".bak.{i}")
                    new_bak = self.path.with_name(self.path.name + f".bak.{i+1}")
                    if old_bak.exists():
                        shutil.copy2(old_bak, new_bak)
                shutil.copy2(self.path, self.path.with_name(self.path.name + ".bak.1"))
            except Exception:
                pass

        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    def migrate(self) -> None:
        cursor = self.conn.execute("PRAGMA user_version")
        version = cursor.fetchone()[0]

        if version == 0:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    channel_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    handle TEXT,
                    url TEXT,
                    added_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS watched (
                    video_id TEXT PRIMARY KEY,
                    watched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    channel_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    FOREIGN KEY(channel_id) REFERENCES subscriptions(channel_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS addon_state (
                    name TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS addon_config (
                    addon_name TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(addon_name, key)
                );

                CREATE TABLE IF NOT EXISTS addon_cache (
                    addon_name TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(addon_name, key)
                );

                CREATE TABLE IF NOT EXISTS channel_search_results (
                    position INTEGER PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    handle TEXT,
                    url TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS channel_categories (
                    channel_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY(channel_id, category),
                    FOREIGN KEY(channel_id) REFERENCES subscriptions(channel_id) ON DELETE CASCADE
                );
                """
            )
            self.conn.execute("PRAGMA user_version = 1")
            self.conn.commit()
            version = 1

        if version < 2:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS video_metadata (
                    video_id TEXT PRIMARY KEY,
                    duration_seconds INTEGER,
                    duration_checked_at TEXT NOT NULL,
                    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
                );
                """
            )
            self.conn.execute("PRAGMA user_version = 2")
            self.conn.commit()
            version = 2

    # Subscriptions
    def add_subscription(self, candidate: ChannelCandidate) -> bool:
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO subscriptions(channel_id, display_name, handle, url, added_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                candidate.channel_id,
                candidate.title,
                candidate.handle,
                candidate.url,
                utcnow().isoformat(),
            ),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def remove_subscription(self, channel_id: str) -> None:
        self.conn.execute("DELETE FROM subscriptions WHERE channel_id = ?", (channel_id,))
        self.conn.commit()

    def list_subscriptions(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT channel_id, display_name, handle, url, added_at FROM subscriptions ORDER BY lower(display_name)"
            )
        )

    def find_subscription(self, spec: str) -> sqlite3.Row | None:
        spec_l = spec.strip().lower().lstrip("@")
        rows = self.list_subscriptions()
        exact: list[sqlite3.Row] = []
        fuzzy: list[sqlite3.Row] = []
        for row in rows:
            values = [
                row["channel_id"].lower(),
                (row["display_name"] or "").lower(),
                (row["handle"] or "").lower().lstrip("@"),
            ]
            if spec_l in values:
                exact.append(row)
            elif any(spec_l in v for v in values if v):
                fuzzy.append(row)
        if exact:
            return exact[0]
        if len(fuzzy) == 1:
            return fuzzy[0]
        return None

    # Categories
    def add_channel_category(self, channel_id: str, category: str) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO channel_categories(channel_id, category, added_at)
            VALUES (?, ?, ?)
            """,
            (channel_id, category.strip(), utcnow().isoformat()),
        )
        self.conn.commit()

    def remove_channel_category(self, channel_id: str, category: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM channel_categories WHERE channel_id = ? AND category = ?",
            (channel_id, category.strip()),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_channel_categories(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT cc.channel_id, cc.category, s.display_name, s.handle
                FROM channel_categories cc
                JOIN subscriptions s ON cc.channel_id = s.channel_id
                ORDER BY cc.category, lower(s.display_name)
                """
            )
        )

    def get_channel_categories(self, channel_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT category FROM channel_categories WHERE channel_id = ? ORDER BY category",
            (channel_id,),
        ).fetchall()
        return [row["category"] for row in rows]

    # Search result persistence
    def save_channel_search_results(self, candidates: list[ChannelCandidate]) -> None:
        now = utcnow().isoformat()
        with self.conn:
            self.conn.execute("DELETE FROM channel_search_results")
            for position, candidate in enumerate(candidates, 1):
                self.conn.execute(
                    """
                    INSERT INTO channel_search_results(position, channel_id, title, handle, url, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (position, candidate.channel_id, candidate.title, candidate.handle, candidate.url, now),
                )

    def get_channel_search_result(self, position: int) -> ChannelCandidate | None:
        row = self.conn.execute(
            """
            SELECT channel_id, title, handle, url
            FROM channel_search_results
            WHERE position = ?
            """,
            (position,),
        ).fetchone()
        if not row:
            return None
        return ChannelCandidate(row["channel_id"], row["title"], row["handle"], row["url"])

    # Videos
    def upsert_videos(self, videos: Iterable[Video]) -> int:
        count = 0
        now = utcnow().isoformat()
        for v in videos:
            self.conn.execute(
                """
                INSERT INTO videos(video_id, channel_id, channel_name, title, url, published_at, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    channel_id=excluded.channel_id,
                    channel_name=excluded.channel_name,
                    title=excluded.title,
                    url=excluded.url,
                    published_at=excluded.published_at,
                    fetched_at=excluded.fetched_at
                """,
                (
                    v.video_id,
                    v.channel_id,
                    v.channel_name,
                    v.title,
                    v.url,
                    v.published_at.isoformat(),
                    now,
                ),
            )
            if v.duration_seconds is not None:
                self._set_video_duration(v.video_id, v.duration_seconds, now)
            count += 1
        self.conn.commit()
        return count

    def latest_videos(
        self,
        *,
        limit: int | None = None,
        days: int | None = None,
        channel_id: str | None = None,
        unwatched_only: bool = False,
        category: str | None = None,
    ) -> list[Video]:
        clauses: list[str] = []
        args: list[object] = []
        if days is not None:
            cutoff = utcnow() - timedelta(days=days)
            clauses.append("v.published_at >= ?")
            args.append(cutoff.isoformat())
        if channel_id:
            clauses.append("v.channel_id = ?")
            args.append(channel_id)
        if category:
            clauses.append("v.channel_id IN (SELECT channel_id FROM channel_categories WHERE lower(category) = ?)")
            args.append(category.lower().strip())
        if unwatched_only:
            clauses.append("v.video_id NOT IN (SELECT video_id FROM watched)")

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        sql = f"""
            SELECT v.video_id, v.channel_id, v.channel_name, v.title, v.url, v.published_at,
                   vm.duration_seconds
            FROM videos v
            LEFT JOIN video_metadata vm ON vm.video_id = v.video_id
            {where}
            ORDER BY v.published_at DESC, v.fetched_at DESC
        """
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)

        return [
            Video(
                video_id=row["video_id"],
                channel_id=row["channel_id"],
                channel_name=row["channel_name"],
                title=row["title"],
                url=row["url"],
                published_at=parse_datetime(row["published_at"]),
                duration_seconds=row["duration_seconds"],
            )
            for row in self.conn.execute(sql, args)
        ]


    def get_video(self, video_id: str) -> Video | None:
        row = self.conn.execute(
            """
            SELECT v.video_id, v.channel_id, v.channel_name, v.title, v.url, v.published_at,
                   vm.duration_seconds
            FROM videos v
            LEFT JOIN video_metadata vm ON vm.video_id = v.video_id
            WHERE v.video_id = ?
            """,
            (video_id,),
        ).fetchone()
        if not row:
            return None
        return Video(
            video_id=row["video_id"],
            channel_id=row["channel_id"],
            channel_name=row["channel_name"],
            title=row["title"],
            url=row["url"],
            published_at=parse_datetime(row["published_at"]),
            duration_seconds=row["duration_seconds"],
        )

    def needs_video_duration_fetch(self, video_id: str, retry_after: timedelta) -> bool:
        row = self.conn.execute(
            "SELECT duration_seconds, duration_checked_at FROM video_metadata WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        if row is None:
            return True
        if row["duration_seconds"] is not None:
            return False
        try:
            return parse_datetime(row["duration_checked_at"]) <= utcnow() - retry_after
        except ValueError:
            return True

    def set_video_duration(self, video_id: str, seconds: int | None) -> None:
        self._set_video_duration(video_id, seconds, utcnow().isoformat())
        self.conn.commit()

    def _set_video_duration(self, video_id: str, seconds: int | None, checked_at: str) -> None:
        if seconds is not None:
            seconds = max(0, int(seconds))
        self.conn.execute(
            """
            INSERT INTO video_metadata(video_id, duration_seconds, duration_checked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                duration_seconds=excluded.duration_seconds,
                duration_checked_at=excluded.duration_checked_at
            """,
            (video_id, seconds, checked_at),
        )

    def mark_watched(self, video_ids: Iterable[str]) -> int:
        count = 0
        now = utcnow().isoformat()
        for video_id in video_ids:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO watched(video_id, watched_at) VALUES (?, ?)",
                (video_id, now),
            )
            count += cur.rowcount
        self.conn.commit()
        return count

    def mark_watched_before(self, cutoff: datetime) -> int:
        now = utcnow().isoformat()
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO watched(video_id, watched_at)
            SELECT video_id, ? FROM videos WHERE published_at < ?
            """,
            (now, cutoff.isoformat()),
        )
        self.conn.commit()
        return cur.rowcount

    # Addon state/config/cache
    def is_addon_enabled(self, name: str, default: bool = False) -> bool:
        row = self.conn.execute("SELECT enabled FROM addon_state WHERE name = ?", (name,)).fetchone()
        if row is None:
            return default
        return bool(row["enabled"])

    def set_addon_enabled(self, name: str, enabled: bool) -> None:
        self.conn.execute(
            """
            INSERT INTO addon_state(name, enabled, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at
            """,
            (name, 1 if enabled else 0, utcnow().isoformat()),
        )
        self.conn.commit()

    def get_config(self, addon_name: str, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM addon_config WHERE addon_name = ? AND key = ?",
            (addon_name, key),
        ).fetchone()
        return row["value"] if row else default

    def set_config(self, addon_name: str, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO addon_config(addon_name, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(addon_name, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (addon_name, key, value, utcnow().isoformat()),
        )
        self.conn.commit()

    def get_cache(self, addon_name: str, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM addon_cache WHERE addon_name = ? AND key = ?",
            (addon_name, key),
        ).fetchone()
        return row["value"] if row else None

    def set_cache(self, addon_name: str, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO addon_cache(addon_name, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(addon_name, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (addon_name, key, value, utcnow().isoformat()),
        )
        self.conn.commit()


    def delete_cache_prefix(self, addon_name: str, prefix: str) -> int:
        cur = self.conn.execute(
            "DELETE FROM addon_cache WHERE addon_name = ? AND key LIKE ?",
            (addon_name, prefix + "%"),
        )
        self.conn.commit()
        return cur.rowcount

    def purge_old_data(self, days: int) -> tuple[int, int]:
        cutoff = utcnow() - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        cur_v = self.conn.execute("DELETE FROM videos WHERE published_at < ?", (cutoff_str,))
        cur_w = self.conn.execute("DELETE FROM watched WHERE watched_at < ?", (cutoff_str,))
        self.conn.commit()
        return cur_v.rowcount, cur_w.rowcount
