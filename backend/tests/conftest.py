import sys
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import import_root  # noqa: E402
from database import SCHEMA_SQL  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_artist_backup_files(tmp_path, monkeypatch):
    """Every test gets its own isolated artist-backup JSON, scan-conflict
    log, import-root setting, and records-dir setting by default. Without this, any test that
    scans an individuals/ file and doesn't explicitly monkeypatch these paths
    itself would read from -- and, since scanner.import_tagged_files now
    writes back to the backup on new classifications -- WRITE INTO the real
    data/artist_tags_backup.json and data/scan_conflicts.log the actual
    running app uses. (Found the hard way: every test image from
    make_image() is byte-identical, so they all share one file_hash, and an
    unisolated test run really did leak one entry into the real backup
    file.) A test that explicitly monkeypatches these paths itself afterward
    simply overrides this default -- no conflict, last monkeypatch call for a
    given attribute wins for that test.

    The *default* import root (used by load_import_root whenever no
    import_root.json exists yet, which is every test unless it explicitly
    calls save_import_root itself) is repointed at this test's own tmp_path
    -- otherwise every existing test that scans tmp_path (virtually all of
    them) would fail the "scan path must be within the import root" check
    added for ADR-0004, since tmp_path has nothing to do with the real
    default import root. This patches import_root.DEFAULT_IMPORT_ROOT
    (not config.DEFAULT_IMPORT_ROOT -- import_root already copied the name
    via `from config import DEFAULT_IMPORT_ROOT` at import time, so patching
    config's copy wouldn't be seen) and deliberately avoids writing an actual
    import_root.json into tmp_path, since several tests assert tmp_path's
    directory listing is exactly what they put there themselves."""
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", tmp_path / "_autouse_artist_backup.json")
    monkeypatch.setattr(config, "SCAN_CONFLICTS_LOG_PATH", tmp_path / "_autouse_scan_conflicts.log")
    monkeypatch.setattr(config, "IMPORT_ROOT_PATH", tmp_path / "_autouse_import_root.json")
    monkeypatch.setattr(config, "RECORDS_DIR_SETTING_PATH", tmp_path / "_autouse_records_dir.json")
    monkeypatch.setattr(import_root, "DEFAULT_IMPORT_ROOT", str(tmp_path))


@pytest.fixture
async def db():
    """A fresh in-memory SQLite connection with the real schema applied."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.executescript(SCHEMA_SQL)
    await conn.commit()
    yield conn
    await conn.close()
