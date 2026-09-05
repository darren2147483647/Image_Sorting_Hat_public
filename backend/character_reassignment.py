"""
圖像分類帽 — 指定角色時，同步搬移影像檔案

見 docs/adr/0006-direct-character-assignment.md、
.scratch/direct-character-assignment/spec.md。「指定角色」是這個 app 裡少數會
直接寫入使用者硬碟的操作——這裡的邏輯獨立成一個模組，是因為這是整個功能裡
風險最高的部分，需要能被獨立、直接測試，不必每次都透過完整的 HTTP／路由層
才能驗證正確性。

刻意不依賴 FastAPI／aiosqlite：呼叫端（routes/images.py）負責查出影像目前的
路徑、解析目標角色的祖先鏈，這個模組只處理「給定來源路徑跟目標祖先鏈，把
檔案搬過去（或搬回來）」這件事本身。
"""
import shutil
from pathlib import Path


class DestinationExistsError(Exception):
    """目標資料夾已經有同名檔案。這個 app 沒有任何合併/覆蓋工具，遇到這種
    情況一律整個操作直接擋下，不自動改檔名、不覆蓋既有檔案。"""

    def __init__(self, destination: Path):
        self.destination = destination
        super().__init__(f"目標位置已經有同名檔案：{destination}")


def move_to_character_folder(
    current_path: str, import_root_dir: str, ancestor_path_names: list[str]
) -> str:
    """把 `current_path` 的檔案搬到 `ancestor_path_names` 指定的資料夾（這個
    路徑已經包含 "characters" 這一層，見 tag_tree.ancestor_path_names），檔名
    不變。回傳搬移後的新絕對路徑字串。

    目標位置已經有同名檔案時，拋出 DestinationExistsError，完全不動任何檔案
    （檢查在搬移之前，不是靠捕捉搬移失敗的例外）。目標資料夾（含任意層級的
    祖先鏈）不存在時會自動建立——新建立的角色節點通常還沒有對應的實體資料夾。
    """
    source = Path(current_path)
    destination = Path(import_root_dir).joinpath(*ancestor_path_names) / source.name

    if destination.exists():
        raise DestinationExistsError(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return str(destination)


def move_back(original_path: str, current_path: str) -> None:
    """撤銷 move_to_character_folder 造成的搬移——用於檔案搬移成功、但緊接著
    的 DB 寫入失敗時，避免留下「檔案實際位置」跟「DB 記錄的位置」不一致的
    悄悄損壞狀態。"""
    shutil.move(current_path, original_path)
