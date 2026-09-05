"""
圖像分類帽 — 導入根目錄的持久化設定與路徑解析

見 docs/adr/0004-relative-image-paths.md。images.file_path 從絕對路徑改成
相對路徑後，需要一個持久化、DB 之外的設定去記錄「相對於哪裡」——DB 可拋棄
重建（見 database.py 的說明），但這個設定必須撐過重建，否則重建後所有相對
路徑會全部解析到錯的地方，這點動機跟 artist_backup.py 一樣，所以也用同樣的
JSON 檔 + atomic write 模式。但性質不同：這是機器/checkout 專屬的一個路徑
指標，不是標註紀錄，所以存在 config.LOCAL_DIR 底下，不跟 artist_tags_backup.json
放一起（見 docs/adr/0007-local-machine-config-directory.md、CONTEXT.md
「機器本地設定」）。

刻意跟 aiosqlite／FastAPI 完全解耦，只做純粹的檔案讀寫與路徑計算，方便獨立
測試。實際的 JSON 讀寫委派給 local_config.py（機器本地設定的共用工具，見
docs/adr/0007-local-machine-config-directory.md）。
"""
from pathlib import Path

import local_config
from config import DEFAULT_IMPORT_ROOT


def load_import_root(path: Path) -> str:
    """讀取目前設定的導入根目錄。檔案不存在、壞掉、或內容格式不對，都回傳
    內建預設值，不讓呼叫端（掃描流程、圖片讀取）因為設定檔的問題而中斷。"""
    value = local_config.load_value(path, "root_path", DEFAULT_IMPORT_ROOT)
    return value if isinstance(value, str) else DEFAULT_IMPORT_ROOT


def save_import_root(path: Path, root_path: str) -> None:
    local_config.save_value(path, "root_path", root_path)


def to_relative(file_path: str, root: str) -> str:
    """絕對路徑轉成相對於 root 的正斜線（POSIX 風格）相對路徑字串。"""
    return Path(file_path).relative_to(root).as_posix()


def resolve(stored_path: str, root: str) -> str:
    """讀取時的相容判斷：絕對路徑（尚未轉換的舊資料，或 migration 沒跑／
    跑到一半）直接使用；相對路徑（新資料）才 join root。"""
    path = Path(stored_path)
    if path.is_absolute():
        return stored_path
    return str(Path(root) / path)


def is_within(candidate_path: str, root: str) -> bool:
    """candidate_path 是否等於 root 本身，或是它的子路徑（任意深度）。用
    Path.relative_to 逐段比較，不是字串前綴比對，所以 "root2" 不會被誤判成
    "root" 的子路徑。"""
    try:
        Path(candidate_path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False
