"""
圖像分類帽 — SQLite 資料庫管理
"""
import aiosqlite

from config import DB_PATH, DATA_DIR
from tag_tree import has_children_predicate

# Schema version for migration tracking
SCHEMA_VERSION = 1

SCHEMA_SQL = """
-- 圖片主表
-- char_id/artist_id 恆為兩者皆有：不適用的那棵樹固定指向該樹的根節點（id=0），不是 NULL。
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    file_name TEXT NOT NULL,
    file_size INTEGER,
    file_format TEXT,
    image_width INTEGER,
    image_height INTEGER,
    file_hash TEXT,
    source_folder TEXT,
    char_id INTEGER NOT NULL DEFAULT 0,
    artist_id INTEGER NOT NULL DEFAULT 0,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (char_id) REFERENCES character_tag(id),
    FOREIGN KEY (artist_id) REFERENCES individual_tag(id)
);

-- 角色／系列 tag 樹（涵蓋 characters/ 容器：分類→系列鏈→角色，深度不限）
-- id=0 是根節點的哨兵列（parent_id 為 NULL 的唯一特例），其餘節點的 parent_id 一律指向真實 id，
-- 讓 UNIQUE(parent_id, name) 在任何深度（含頂層）都能正確擋下重複節點。
CREATE TABLE IF NOT EXISTS character_tag (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_id) REFERENCES character_tag(id),
    UNIQUE(parent_id, name)
);

-- 作者 tag 樹（涵蓋 individuals/ 容器：作者→巢狀結構，深度不限），與 character_tag 各自獨立
CREATE TABLE IF NOT EXISTS individual_tag (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_id) REFERENCES individual_tag(id),
    UNIQUE(parent_id, name)
);

INSERT OR IGNORE INTO character_tag (id, parent_id, name) VALUES (0, NULL, 'root');
INSERT OR IGNORE INTO individual_tag (id, parent_id, name) VALUES (0, NULL, 'root');

-- 資料夾層級結構表
CREATE TABLE IF NOT EXISTS folder_hierarchy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path TEXT UNIQUE NOT NULL,
    depth INTEGER NOT NULL,
    role TEXT,
    label TEXT,
    parent_id INTEGER,
    FOREIGN KEY (parent_id) REFERENCES folder_hierarchy(id)
);

-- 模型執行批次表 (Phase 3 預留)
CREATE TABLE IF NOT EXISTS model_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    model_version TEXT,
    parameters TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    total_images INTEGER,
    status TEXT DEFAULT 'pending'
);

-- 逐張影像的模型辨識結果 (骨架，這次不寫任何讀寫這張表的程式碼)
-- 角色/作者可以只預測其中一個，也可以兩個都預測，故皆為 nullable。
-- image_id 掛 ON DELETE CASCADE：影像被「移出追蹤」整列刪除時，殘留的舊預測
-- 結果沒有意義，應該一併消失，而不是擋住刪除或留下孤兒列。
CREATE TABLE IF NOT EXISTS image_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id INTEGER NOT NULL,
    model_run_id INTEGER NOT NULL,
    predicted_char_id INTEGER,
    predicted_artist_id INTEGER,
    confidence REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
    FOREIGN KEY (model_run_id) REFERENCES model_runs(id),
    FOREIGN KEY (predicted_char_id) REFERENCES character_tag(id),
    FOREIGN KEY (predicted_artist_id) REFERENCES individual_tag(id)
);

-- 掃描歷史表
-- char_policy/artist_policy 記錄該次掃描使用的分類策略（folder/fixed/none，見
-- ADR-0003），*_fixed_id 只有 policy=fixed 時有值。純歷史／稽核資訊，跟
-- images/character_tag/individual_tag 不同，不需要整批重建才能升級舊資料庫，
-- 見 database.py:init_db 的 ALTER TABLE 升級步驟。
CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_path TEXT NOT NULL,
    folders_scanned TEXT,
    total_files_found INTEGER DEFAULT 0,
    total_files_imported INTEGER DEFAULT 0,
    total_characters_found INTEGER DEFAULT 0,
    total_franchises_found INTEGER DEFAULT 0,
    total_artists_found INTEGER DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT DEFAULT 'running',
    char_policy TEXT DEFAULT 'folder',
    char_fixed_id INTEGER,
    artist_policy TEXT DEFAULT 'folder',
    artist_fixed_id INTEGER
);

-- Schema 版本追蹤
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_images_source ON images(source_folder);
CREATE INDEX IF NOT EXISTS idx_images_hash ON images(file_hash);
CREATE INDEX IF NOT EXISTS idx_images_format ON images(file_format);
CREATE INDEX IF NOT EXISTS idx_images_char ON images(char_id);
CREATE INDEX IF NOT EXISTS idx_images_artist ON images(artist_id);
CREATE INDEX IF NOT EXISTS idx_character_tag_parent ON character_tag(parent_id);
CREATE INDEX IF NOT EXISTS idx_individual_tag_parent ON individual_tag(parent_id);
CREATE INDEX IF NOT EXISTS idx_folder_hierarchy_parent ON folder_hierarchy(parent_id);
"""


async def get_db() -> aiosqlite.Connection:
    """Get a database connection. Used as a FastAPI dependency."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        await db.close()


async def create_db_connection() -> aiosqlite.Connection:
    """Create a standalone database connection for background tasks.

    Unlike get_db(), this is NOT a generator — the caller is responsible
    for closing the connection when done.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    """Initialize the database schema."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        # This schema replaces the old franchises/characters/artists tables
        # wholesale rather than migrating them (per the user's own plan: old
        # .db is disposable, rebuild via rescan). `CREATE TABLE IF NOT EXISTS`
        # would otherwise silently leave a pre-existing old-schema `images`
        # table without char_id/artist_id, making every route crash with
        # cryptic "no such column" errors instead of a clear message.
        cursor = await db.execute("PRAGMA table_info(images)")
        existing_columns = {row[1] for row in await cursor.fetchall()}
        if existing_columns and "char_id" not in existing_columns:
            raise RuntimeError(
                f"偵測到舊版 schema 的資料庫（{DB_PATH}）：images 表沒有 char_id 欄位。"
                "這個版本改用全新的 tag 樹結構，不會自動遷移舊資料。"
                "請先刪除或搬移這個 .db 檔案，再重新啟動並重新掃描。"
            )

        await db.executescript(SCHEMA_SQL)

        # scan_history is pure historical/audit data (unlike images/character_tag/
        # individual_tag, nothing else references it), so a new nullable column
        # here doesn't need the "wholesale rebuild required" treatment above --
        # CREATE TABLE IF NOT EXISTS is a no-op against an existing table, so an
        # already-existing database needs these added explicitly and idempotently.
        cursor = await db.execute("PRAGMA table_info(scan_history)")
        scan_history_columns = {row[1] for row in await cursor.fetchall()}
        for column, col_type in (
            ("char_policy", "TEXT DEFAULT 'folder'"),
            ("char_fixed_id", "INTEGER"),
            ("artist_policy", "TEXT DEFAULT 'folder'"),
            ("artist_fixed_id", "INTEGER"),
        ):
            if column not in scan_history_columns:
                await db.execute(f"ALTER TABLE scan_history ADD COLUMN {column} {col_type}")

        # Set schema version
        await db.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        await db.commit()
    print(f"✅ 資料庫初始化完成: {DB_PATH}")


async def get_db_stats(db: aiosqlite.Connection) -> dict:
    """Get database statistics.

    "characters"/"artists" are tag nodes actually referenced by at least one
    image (leaf-by-usage, not by depth). "franchises" are character_tag nodes
    with children, excluding the sentinel root.
    """
    stats = {}

    cursor = await db.execute("SELECT COUNT(*) FROM images")
    stats["images"] = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(DISTINCT char_id) FROM images WHERE char_id != 0")
    stats["characters"] = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(DISTINCT artist_id) FROM images WHERE artist_id != 0")
    stats["artists"] = (await cursor.fetchone())[0]

    cursor = await db.execute(
        f"SELECT COUNT(*) FROM character_tag t WHERE {has_children_predicate('character_tag')}"
    )
    stats["franchises"] = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM images WHERE char_id != 0")
    stats["images_with_character"] = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM images WHERE artist_id != 0")
    stats["images_with_artist"] = (await cursor.fetchone())[0]

    return stats
