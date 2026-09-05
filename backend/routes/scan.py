"""
圖像分類帽 — 掃描相關 API
"""
import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
import aiosqlite

import config
import import_root
import local_config
from database import get_db
from scanner import (
    ClassificationPolicy,
    count_loose_individuals_files,
    start_scan_task,
    scan_progress,
    CONTAINERS,
)

router = APIRouter(prefix="/api/scan", tags=["scan"])

# Track background scan task
_scan_task: asyncio.Task | None = None


@router.get("/folders")
async def get_available_folders():
    """Get the list of scannable containers (characters/, individuals/)."""
    return {
        name: {"label": config["label"], "description": config["description"]}
        for name, config in CONTAINERS.items()
    }


@router.get("/import-root")
async def get_import_root():
    """Get the currently persisted import root (see ADR-0004)."""
    return {"root_path": import_root.load_import_root(config.IMPORT_ROOT_PATH)}


@router.post("/import-root")
async def set_import_root(root_path: str = Query(...)):
    """Save a new import root. The path-exists check is informational only
    (e.g. an external drive that isn't plugged in yet) -- it never blocks
    the save itself."""
    import_root.save_import_root(config.IMPORT_ROOT_PATH, root_path)
    return {"root_path": root_path, "exists": os.path.isdir(root_path)}


@router.get("/records-dir")
async def get_records_dir():
    """Get the records directory (DB + artist backup) THIS running process
    is currently using, i.e. config.DATA_DIR as already resolved at startup
    (see ADR-0008) -- not necessarily what's persisted in the setting file,
    since a save below never changes it until a restart."""
    return {"records_dir": str(config.DATA_DIR)}


@router.post("/records-dir")
async def set_records_dir(records_dir: str = Query(...)):
    """Persist a new records directory. Unlike import root, this does NOT
    take effect for the currently running process -- config.DATA_DIR (and
    everything database.py already resolved from it) was fixed at process
    startup, and only re-reads this setting on the next start (see
    ADR-0008). The path-exists check is informational only, same as import
    root -- it never blocks the save."""
    local_config.save_value(config.RECORDS_DIR_SETTING_PATH, "records_dir", records_dir)
    return {
        "records_dir": records_dir,
        "exists": os.path.isdir(records_dir),
        "restart_required": True,
    }


@router.post("/start")
async def start_scan(
    root_path: str = Query(..., description="sort 資料夾的絕對路徑"),
    folders: str = Query(..., description="要掃描的容器，逗號分隔（characters,individuals）"),
    include_other: bool = Query(True, description="是否掃描 characters／individuals 之外的其他位置"),
    char_policy: str = Query("folder", pattern="^(folder|fixed|none)$"),
    char_fixed_id: Optional[int] = Query(None, description="char_policy=fixed 時必填"),
    artist_policy: str = Query("folder", pattern="^(folder|fixed|none)$"),
    artist_fixed_id: Optional[int] = Query(None, description="artist_policy=fixed 時必填"),
):
    """Start a folder scan as a background task. Returns immediately.

    loose_individuals_count is computed synchronously here, before the
    background task launches -- cheap (a single non-recursive iterdir), so
    the frontend gets it in the same response it already awaits, with no
    separate pre-check endpoint or extra round-trip needed."""
    global _scan_task

    container_list = [f.strip() for f in folders.split(",") if f.strip()]

    if not container_list and not include_other:
        return {"error": "請至少選擇一個資料夾"}
    if char_policy == "fixed" and char_fixed_id is None:
        return {"error": "選擇「整批分類為指定角色」時，必須選擇一個角色"}
    if artist_policy == "fixed" and artist_fixed_id is None:
        return {"error": "選擇「整批分類為指定作者」時，必須選擇一個作者"}

    # Every images.file_path must stay resolvable through the persisted
    # import root (see ADR-0004) -- a scan path outside it would store rows
    # that can never be read back, so this is enforced, not just suggested.
    current_import_root = import_root.load_import_root(config.IMPORT_ROOT_PATH)
    if not import_root.is_within(root_path, current_import_root):
        return {
            "error": f"掃描路徑必須是導入根目錄本身或其子路徑（目前導入根目錄：{current_import_root}）",
        }

    # Prevent concurrent scans
    if _scan_task is not None and not _scan_task.done():
        return {
            "error": "已有掃描正在進行中",
            "progress": scan_progress.to_dict(),
        }

    loose_individuals_count = count_loose_individuals_files(Path(root_path) / "individuals")

    # Launch scan as a background asyncio task
    _scan_task = asyncio.create_task(
        start_scan_task(
            root_path, container_list, include_other=include_other,
            char_policy=ClassificationPolicy(char_policy, char_fixed_id),
            artist_policy=ClassificationPolicy(artist_policy, artist_fixed_id),
            import_root_dir=current_import_root,
        )
    )

    return {
        "message": "掃描已啟動",
        "progress": scan_progress.to_dict(),
        "loose_individuals_count": loose_individuals_count,
    }


@router.get("/status")
async def get_scan_status():
    """Get current scan progress as SSE stream."""

    async def event_stream():
        while True:
            data = json.dumps(scan_progress.to_dict(), ensure_ascii=False)
            yield f"data: {data}\n\n"

            if scan_progress.status in ("completed", "failed", "idle"):
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/progress")
async def get_current_progress():
    """Get current scan progress (polling endpoint)."""
    return scan_progress.to_dict()


@router.get("/history")
async def get_scan_history(
    limit: int = Query(20, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Get scan history."""
    cursor = await db.execute(
        """SELECT * FROM scan_history
           ORDER BY started_at DESC
           LIMIT ?""",
        (limit,),
    )
    rows = await cursor.fetchall()
    return {"history": [dict(row) for row in rows]}