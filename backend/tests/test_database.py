import sqlite3

import pytest

import database


async def test_init_db_refuses_to_run_against_old_schema(tmp_path, monkeypatch):
    """A pre-existing old-schema images table (no char_id/artist_id) must
    fail loudly at startup instead of leaving every route to crash with a
    cryptic 'no such column' error."""
    db_path = tmp_path / "old_schema.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE NOT NULL,
            file_name TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(database, "DB_PATH", db_path)

    with pytest.raises(RuntimeError, match="舊版"):
        await database.init_db()


async def test_init_db_succeeds_on_a_fresh_database(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)

    await database.init_db()

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("PRAGMA table_info(images)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    assert "char_id" in columns
    assert "artist_id" in columns


async def test_image_predictions_schema(db):
    """`image_predictions` is schema-only for now (no read/write routes yet)
    -- this just locks in the shape future model-integration work builds on:
    a model run's per-image guesses, either axis optional, both nullable so a
    run can predict just a character, just an artist, or both."""
    cursor = await db.execute("PRAGMA table_info(image_predictions)")
    columns = {row["name"]: row for row in await cursor.fetchall()}

    assert set(columns) == {
        "id", "image_id", "model_run_id",
        "predicted_char_id", "predicted_artist_id",
        "confidence", "created_at",
    }
    # predicted_char_id/predicted_artist_id/confidence must be nullable
    assert columns["predicted_char_id"]["notnull"] == 0
    assert columns["predicted_artist_id"]["notnull"] == 0
    assert columns["confidence"]["notnull"] == 0

    cursor = await db.execute("PRAGMA foreign_key_list(image_predictions)")
    fks = {row["table"]: row["from"] for row in await cursor.fetchall()}
    assert fks["images"] == "image_id"
    assert fks["model_runs"] == "model_run_id"
    assert fks["character_tag"] == "predicted_char_id"
    assert fks["individual_tag"] == "predicted_artist_id"
