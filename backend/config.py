"""
圖像分類帽 — 應用程式設定
"""
from pathlib import Path

import local_config

# === 路徑設定 ===
BASE_DIR = Path(__file__).resolve().parent.parent
# 機器本地設定專用目錄，跟 DATA_DIR 分開存放（見 CONTEXT.md「機器本地設定」、
# docs/adr/0007-local-machine-config-directory.md）：DATA_DIR 只放影像的標註
# 紀錄（DB、artist 備份）——遺失了代表累積的人工標註跟著不見；LOCAL_DIR 放的
# 東西則是機器/checkout 專屬、免費重建，不該隨標註紀錄一起複製到別台機器。
LOCAL_DIR = BASE_DIR / "local"
# 紀錄目錄（DATA_DIR）本身也是一個機器本地設定，可透過 /api/scan/records-dir
# 切換（見 docs/adr/0008-switchable-records-directory.md）——但只在下次啟動
# 時讀取一次，不是每次請求都重新解析：切換後需要重啟後端才會生效。
RECORDS_DIR_SETTING_PATH = LOCAL_DIR / "records_dir.json"


def _resolve_data_dir(setting_path: Path, base_dir: Path) -> Path:
    """DATA_DIR 的計算方式：讀取 setting_path 裡持久化的紀錄目錄，讀不到
    （檔案不存在、壞掉、或第一次啟動）就 fallback 回 base_dir/data。抽成獨立
    函式，接受明確參數而不是直接讀模組全域變數，方便不用整個重新 import
    config 模組就能測試。

    設定的目錄若不存在（外接硬碟還沒接上、或路徑打錯字），一律 fallback 回
    base_dir/data，絕不讓 database.py 對著一個可能不存在的外接裝置路徑
    嘗試建立資料夾或連線（見 docs/adr/0008-switchable-records-directory.md）
    ——只印警告，不修改 setting_path 本身：這次啟動先用預設頂著，等使用者
    把硬碟接上或修正設定後，下次重啟會自動改用原本設定的路徑，不用重新輸入。

    這個檢查只在「真的有一個持久化設定」時才做：從未設定過（sentinel 用
    None 判斷，不是 default）就直接用預設值，不對預設路徑本身做存在檢查、
    也不印警告——預設路徑本來就是 database.py 自己會視需要建立的本地資料夾，
    不是使用者需要被提醒的「外接裝置可能不存在」情境。
    """
    default = base_dir / "data"
    configured_str = local_config.load_value(setting_path, "records_dir", None)
    if configured_str is None:
        return default

    configured = Path(configured_str)
    if not configured.is_dir():
        print(
            f"⚠️ 設定的紀錄目錄不存在：{configured}（可能是外接硬碟還沒接上，或路徑打錯字）"
            f"，這次先使用預設位置 {default}。請確認後到掃描頁面重新指定紀錄目錄。"
        )
        return default
    return configured


DATA_DIR = _resolve_data_dir(RECORDS_DIR_SETTING_PATH, BASE_DIR)
DB_PATH = DATA_DIR / "image_manager.db"
# Filesystem-level backup of manually-assigned artist_id classifications,
# keyed by file_hash (survives file moves/renames unlike file_path) --
# char_id needs no equivalent since it's always reconstructible by
# rescanning folder structure, but artist_id is now assigned independently
# of folder position and would otherwise live only in the (disposable) DB.
ARTIST_TAGS_BACKUP_PATH = DATA_DIR / "artist_tags_backup.json"
# Append-only audit trail (JSON Lines, one record per line) of scan-time
# artist-classification conflicts -- a file's hash already has a backup
# entry, but this scan's own policy computed a different one for it. The
# existing entry always wins (see ARTIST_TAGS_BACKUP_PATH's priority rule);
# this log exists purely so a real, unexpected disagreement isn't silently
# swallowed.
SCAN_CONFLICTS_LOG_PATH = DATA_DIR / "scan_conflicts.log"
# Persisted, DB-independent setting import_root.py resolves images.file_path
# against (see docs/adr/0004-relative-image-paths.md) -- survives a DB wipe
# for the same reason ARTIST_TAGS_BACKUP_PATH does. Lives under LOCAL_DIR, not
# DATA_DIR: unlike the DB/artist-backup, this is a machine-specific pointer
# (see docs/adr/0007-local-machine-config-directory.md) -- copying it to a
# different machine's checkout would point at the wrong drive/mount entirely.
IMPORT_ROOT_PATH = LOCAL_DIR / "import_root.json"
# Built-in fallback used by import_root.load_import_root when the file above
# doesn't exist yet (e.g. first run, or a fresh clone) -- a real folder inside
# the repo itself, so a fresh checkout works out of the box without exposing
# any one machine's actual absolute path as the default.
DEFAULT_IMPORT_ROOT = str((BASE_DIR / "images").resolve())

# === 伺服器設定 ===
API_HOST = "127.0.0.1"
API_PORT = 8000
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# === 圖片設定 ===
SUPPORTED_IMAGE_FORMATS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".jfif", ".avif",
    ".mp4", ".mov",
}

# === 掃描設定 ===
# sort 根目錄底下固定兩個容器：characters/、individuals/。兩者底下的子資料夾
# 都是動態列舉的，不是寫死清單（見 scanner.CONTAINERS）。
SCAN_BATCH_SIZE = 100  # 每批次寫入資料庫的數量
HASH_CHUNK_SIZE = 8192  # MD5 計算時的讀取區塊大小

# === 分頁設定 ===
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
