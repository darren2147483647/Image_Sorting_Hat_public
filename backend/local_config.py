"""
圖像分類帽 — 機器本地設定的共用 JSON 讀寫

見 CONTEXT.md「機器本地設定」、docs/adr/0007-local-machine-config-directory.md。
導入根目錄、紀錄目錄都是「機器/checkout 專屬、遺失了免費重建」的設定，各自
需要「讀一個 JSON 檔案裡的一個欄位，讀不到就用預設值」「atomic write（同目錄
暫存檔 + os.replace）」——這裡收斂成共用函式，避免每新增一個機器本地設定就
重寫一次一樣的檔案 I/O。

刻意不 import config：config.py 本身在算 DATA_DIR 時就需要呼叫這裡，若這裡
反過來 import config 會形成循環引用。
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load_value(path: Path, key: str, default: Any) -> Any:
    """讀 path 底下 JSON 物件裡的 key。檔案不存在、壞掉、內容不是物件、或
    key 不存在，一律回傳 default，不讓呼叫端因為設定檔的問題而中斷。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default
    if not isinstance(data, dict) or key not in data:
        return default
    return data[key]


def save_value(path: Path, key: str, value: Any) -> None:
    """Atomic write：先寫到同目錄的暫存檔，再用 os.replace() 換過去（Windows
    上只有 os.replace 才是真正原子的）。整份檔案只有這一個 key/value，不保留
    其他既有欄位——目前每個機器本地設定都各自一個檔案，沒有合併多欄位的需求。"""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({key: value}, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        os.unlink(tmp_name)
        raise
