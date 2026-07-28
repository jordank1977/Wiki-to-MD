import os
from typing import List, Dict, Any, Optional
import aiosqlite

DB_PATH = "/app/data/database.db"

# Ensure the parent directory exists
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Converts a sqlite Row to a dict and casts types."""
    d = dict(row)
    d["has_pending_changes"] = bool(d.get("has_pending_changes", False))
    return d


async def init_db() -> None:
    """Initializes the database schema."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wikis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                name TEXT NOT NULL,
                last_sync_timestamp TEXT,
                status TEXT NOT NULL DEFAULT 'Idle',
                total_pages INTEGER NOT NULL DEFAULT 0,
                has_pending_changes BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        await db.commit()

        # Safely migrate existing databases if column doesn't exist
        try:
            await db.execute("ALTER TABLE wikis ADD COLUMN has_pending_changes BOOLEAN NOT NULL DEFAULT 0")
            await db.commit()
        except aiosqlite.OperationalError:
            # Column already exists
            pass


async def add_wiki(url: str, name: str) -> Dict[str, Any]:
    """Adds a new wiki to tracking database."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "INSERT INTO wikis (url, name, status, total_pages) VALUES (?, ?, ?, ?)",
            (url, name, "Idle", 0)
        )
        await db.commit()
        inserted_id = cursor.lastrowid

        async with db.execute("SELECT * FROM wikis WHERE id = ?", (inserted_id,)) as cur:
            row = await cur.fetchone()
            return _row_to_dict(row) if row else {}


async def get_all_wikis() -> List[Dict[str, Any]]:
    """Returns all tracked wikis."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM wikis ORDER BY id DESC") as cur:
            rows = await cur.fetchall()
            return [_row_to_dict(row) for row in rows]


async def get_wiki(wiki_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a single wiki by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM wikis WHERE id = ?", (wiki_id,)) as cur:
            row = await cur.fetchone()
            return _row_to_dict(row) if row else None


async def update_wiki_pending_changes(wiki_id: int, has_pending_changes: bool) -> None:
    """Updates the has_pending_changes column for a wiki."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE wikis SET has_pending_changes = ? WHERE id = ?",
            (1 if has_pending_changes else 0, wiki_id)
        )
        await db.commit()


async def update_wiki_status(wiki_id: int, status: str) -> None:
    """Updates the status of a wiki."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE wikis SET status = ? WHERE id = ?",
            (status, wiki_id)
        )
        await db.commit()


async def update_wiki_total_pages(wiki_id: int, total_pages: int) -> None:
    """Updates the total_pages column for a wiki."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE wikis SET total_pages = ? WHERE id = ?",
            (total_pages, wiki_id)
        )
        await db.commit()


async def update_wiki_sync_details(
    wiki_id: int, last_sync_timestamp: str, total_pages: int, status: str = "Idle"
) -> None:
    """Updates last sync timestamp, total page count, status, and resets pending changes."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE wikis SET last_sync_timestamp = ?, total_pages = ?, status = ?, has_pending_changes = 0 WHERE id = ?",
            (last_sync_timestamp, total_pages, status, wiki_id)
        )
        await db.commit()


async def delete_wiki(wiki_id: int) -> bool:
    """Deletes a wiki from the database. Returns True if deleted."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM wikis WHERE id = ?", (wiki_id,)) as cur:
            exists = await cur.fetchone()
        if not exists:
            return False
        await db.execute("DELETE FROM wikis WHERE id = ?", (wiki_id,))
        await db.commit()
        return True
