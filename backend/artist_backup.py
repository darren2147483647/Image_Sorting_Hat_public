"""
圖像分類帽 — 作者分類的檔案系統層級備份

char_id 永遠由資料夾決定，重新掃描就能百分之百重建；artist_id 現在完全跟
資料夾位置脫鉤、只能手動指定，唯一的紀錄原本只存在 SQLite 裡——一旦 DB
遺失/損毀需要重建（見 database.py 對 .db 是可拋棄的設計說明），這些手動
分類就永久消失了。這個模組把「file_hash -> 作者的完整名稱路徑」存成一份
獨立的 JSON，讓重新掃描時可以把它們套用回去。

刻意跟 aiosqlite／FastAPI 完全解耦，只做純粹的 JSON 檔案讀寫，方便獨立測試，
也不會被拉進資料庫交易的生命週期裡。
"""
import json
import os
import tempfile
from pathlib import Path


def load_backup(path: Path) -> dict[str, list[str]]:
    """讀取備份檔，檔案不存在或內容壞掉都回傳空字典，不讓呼叫端（掃描流程）
    因為備份檔的問題而中斷。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_backup(path: Path, data: dict[str, list[str]]) -> None:
    """Atomic write：先寫到同目錄的暫存檔，再用 os.replace() 換過去——
    Windows 上只有 os.replace 是真正原子的（rename 在目標已存在時會失敗）。"""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_name, path)
    except BaseException:
        os.unlink(tmp_name)
        raise


def set_entry(path: Path, file_hash: str, ancestor_path: list[str]) -> None:
    """記錄（或覆蓋）一張影像的作者分類備份。"""
    data = load_backup(path)
    data[file_hash] = ancestor_path
    save_backup(path, data)


def remove_entry(path: Path, file_hash: str) -> None:
    """移除一張影像的作者分類備份；key 不存在也不報錯。"""
    data = load_backup(path)
    if file_hash in data:
        del data[file_hash]
        save_backup(path, data)


def append_conflict_log(path: Path, entry: dict) -> None:
    """附加寫入一筆掃描衝突紀錄（JSON Lines，一行一筆）。純附加、不讀取既有
    內容——這是只增不改的稽核紀錄，跟 save_backup 的整體覆寫語意不同，不需要
    atomic write 那一套（單行 append 本身已經是常見檔案系統上的安全操作，
    而且就算真的寫到一半中斷，最多只是最後一行不完整，不會波及先前已經
    寫入的紀錄）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
