"""
圖像分類帽 — 資料夾掃描與解析引擎

核心邏輯：
- sort 根目錄底下固定兩個容器：characters/、individuals/
- 兩者都以自身為起點跑同一套遞迴解析：每一層資料夾（含起點本身）都是一個 tag 節點，
  資料夾裡直接放的檔案就標記為該節點的 id；有子資料夾的就繼續往下遞迴，不假設固定深度。
- characters/ 寫入 character_tag，該容器下所有影像的 artist_id 固定為 0。
- individuals/ 寫入 individual_tag，該容器下所有影像的 char_id 固定為 0。
- 新匯入影像的 artist_id 如果在 data/artist_tags_backup.json 裡有依 file_hash
  記錄的備份，會覆蓋掉上面容器推導出的預設值——作者分類跟資料夾位置脫鉤，
  備份檔才是它唯一的硬碟紀錄，套用優先權比容器推導高，不分檔案在哪個容器下。
- include_other=True（預設）時，根目錄底下 characters/、individuals/ 之外的影像
  （任意深度）也會被找到並匯入，source_folder="other"，不建立任何 tag 節點——
  純粹的檔案探索（見 walk_other_locations），跟兩個固定容器各自的樹狀建立無關。
- char_policy／artist_policy（ClassificationPolicy，預設都是 "folder"）決定該次
  掃描新匯入的所有影像要記錄什麼 char_id／artist_id：folder＝沿用上面的資料夾
  推導；fixed＝整批套用同一個指定節點；none＝整批不分類。套用範圍不限容器，
  角色與作者兩個維度各自獨立（見 ADR-0003）。fixed／none 時對應容器的資料夾
  結構不會被拿來建 tag 節點——結構本身用不到，只做純檔案探索。
- 重新掃描是新增-only：`file_path` 已存在的影像完全不會被觸碰（不論人工修正過或機器判定）。
- `images.file_path` 存的是相對於「導入根目錄」的正斜線相對路徑（見
  docs/adr/0004-relative-image-paths.md），不是絕對路徑——即使這次掃描的
  `root_path` 只是導入根目錄底下的子資料夾，存進去的相對路徑仍然相對於導入
  根目錄本身，不是相對於這次掃描用的子路徑。
"""
import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import aiosqlite
from PIL import Image

import artist_backup
import config
import import_root
from config import HASH_CHUNK_SIZE, SCAN_BATCH_SIZE, SUPPORTED_IMAGE_FORMATS
from tag_tree import (
    ROOT_TAG_ID,
    ancestor_path_names,
    get_or_create_tag,
    get_or_create_tag_path,
    has_children_predicate,
)

# sort 根目錄底下固定的兩個容器；底下的子資料夾不是寫死清單，掃描時動態列舉。
CONTAINERS = {
    "characters": {
        "label": "角色／系列",
        "description": "依角色/系列分類的二創作品",
        "table": "character_tag",
    },
    "individuals": {
        "label": "個人作者",
        "description": "依作者分類的作品",
        "table": "individual_tag",
    },
}


@dataclass
class ClassificationPolicy:
    """How one axis (character or artist) decides the tag id for every
    newly-imported image this scan, per ADR-0003:
    - "folder": derive from the file's position under its container (the
      pre-existing, and still default, behaviour)
    - "fixed": every new image on this axis gets `fixed_id`, uniformly,
      regardless of which container (or "other") it was found under
    - "none": every new image on this axis gets 0 (unclassified)
    fixed_id is only meaningful (and required) when mode == "fixed"."""

    mode: Literal["folder", "fixed", "none"]
    fixed_id: Optional[int] = None


def _resolve_axis(policy: "ClassificationPolicy", folder_derived_id: Optional[int]) -> int:
    if policy.mode == "fixed":
        return policy.fixed_id
    if policy.mode == "none":
        return 0
    return folder_derived_id if folder_derived_id is not None else 0


class ScanProgress:
    """Tracks scanning progress for real-time reporting."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.status = "idle"  # idle / scanning / importing / completed / failed
        self.current_folder = ""
        self.current_file = ""
        self.total_files = 0
        self.processed_files = 0
        self.total_characters = 0
        self.total_franchises = 0
        self.total_artists = 0
        self.errors: list[str] = []
        # Separate from errors: a conflict doesn't mean the image failed to
        # import (it did, using the existing/winning backup entry) -- it's
        # informational, non-blocking, surfaced independently per ADR-0003.
        self.conflicts: list[str] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def to_dict(self) -> dict:
        elapsed = 0
        if self.start_time:
            elapsed = (self.end_time or time.time()) - self.start_time
        return {
            "status": self.status,
            "current_folder": self.current_folder,
            "current_file": self.current_file,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "total_characters": self.total_characters,
            "total_franchises": self.total_franchises,
            "total_artists": self.total_artists,
            "errors": self.errors[-20:],  # 只回傳最近 20 個錯誤
            "conflicts": self.conflicts[-20:],
            "elapsed_seconds": round(elapsed, 1),
            "progress_percent": (
                round(self.processed_files / self.total_files * 100, 1)
                if self.total_files > 0
                else 0
            ),
        }


# Global progress tracker
scan_progress = ScanProgress()


def compute_file_hash(file_path: str) -> str:
    """Compute MD5 hash of a file."""
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE):
            md5.update(chunk)
    return md5.hexdigest()


def get_image_dimensions(file_path: str) -> tuple[Optional[int], Optional[int]]:
    """Get image width and height using Pillow."""
    try:
        with Image.open(file_path) as img:
            return img.size  # (width, height)
    except Exception:
        return None, None


def _is_supported_image(entry: Path) -> bool:
    return entry.is_file() and entry.suffix.lower() in SUPPORTED_IMAGE_FORMATS


async def walk_into_tag_tree(
    db: aiosqlite.Connection,
    table: str,
    folder: Path,
    parent_id: int,
) -> list[tuple[str, int]]:
    """
    Recursively walk `folder`, turning every folder visited — including
    `folder` itself — into a tag node in `table`. Files placed directly in a
    folder are tagged with that folder's own node id, regardless of whether
    the folder also has subdirectories. Depth is unlimited.

    Returns a flat list of (file_path, tag_id) for every image file found at
    any depth.
    """
    if not folder.exists():
        return []

    node_id = await get_or_create_tag(db, table, parent_id, folder.name)

    try:
        entries = list(folder.iterdir())
    except PermissionError:
        return []

    results = [
        (str(entry), node_id) for entry in entries if _is_supported_image(entry)
    ]

    for sub_dir in sorted(e for e in entries if e.is_dir()):
        results.extend(await walk_into_tag_tree(db, table, sub_dir, node_id))

    return results


def _walk_files_only(folder: Path) -> list[str]:
    """Every supported image file under `folder`, at any depth -- no
    tag_tree nodes, no `table`/parent_id bookkeeping. Shared by
    walk_other_locations (for locations outside both fixed containers) and
    by _run_scan_worker itself when a fixed/none classification policy makes
    a container's own folder structure irrelevant (see ADR-0003) -- the
    files still need discovering even though their positions won't be used."""
    try:
        entries = list(folder.iterdir())
    except PermissionError:
        return []
    results: list[str] = []
    for entry in entries:
        if entry.is_dir():
            results.extend(_walk_files_only(entry))
        elif _is_supported_image(entry):
            results.append(str(entry))
    return results


def walk_other_locations(root: Path) -> list[str]:
    """Every supported image file under `root`, excluding the two fixed
    top-level containers (root/characters, root/individuals) entirely --
    pure file discovery, no tag_tree nodes are ever created from this walk.
    Only an exact top-level path match is excluded -- a nested folder that
    happens to share a container's name is not one of the two fixed
    containers and is included normally."""
    if not root.exists():
        return []

    excluded = {root / name for name in CONTAINERS}
    try:
        entries = list(root.iterdir())
    except PermissionError:
        return []

    results: list[str] = []
    for entry in entries:
        if entry in excluded:
            continue
        if entry.is_dir():
            results.extend(_walk_files_only(entry))
        elif _is_supported_image(entry):
            results.append(str(entry))
    return results


def count_loose_individuals_files(individuals_root: Path) -> int:
    """How many supported image files sit directly in `individuals_root`
    itself, outside any artist subfolder -- these are the ones that, under
    the folder-derived artist policy, get no artist_id at all. Non-recursive
    (only direct children) and cheap enough to run synchronously in
    POST /scan/start before the background scan task launches."""
    if not individuals_root.exists():
        return 0
    try:
        entries = list(individuals_root.iterdir())
    except PermissionError:
        return 0
    return sum(1 for e in entries if _is_supported_image(e))


async def import_tagged_files(
    db: aiosqlite.Connection,
    tagged_files: list[tuple[str, int, int, str]],
    scan_id: int,
    backup_path: Path,
    conflicts_log_path: Path,
    import_root_path: str,
) -> None:
    """Insert-only import: files whose `file_path` already exists in `images`
    are skipped entirely (no UPDATE, ever) so rescans never clobber manual
    corrections or duplicate rows.

    backup_path/conflicts_log_path/import_root_path are required, explicit
    parameters rather than reaching into config.* internally -- this function
    reads AND writes real files on disk, and an implicit dependency on
    module-level config is exactly the shape that let an early version of
    this code silently write test data into the real
    data/artist_tags_backup.json (every test image is byte-identical, so
    every test shares one file_hash). Explicit parameters make that
    dependency visible in the signature and force every caller, test or
    otherwise, to decide the path on purpose.

    Per ADR-0004, the value actually written to `images.file_path` is a
    POSIX-relative path against import_root_path, not the absolute path
    tagged_files carries -- the dedup check below matches against both forms
    so a file already imported under the old absolute-path scheme (before
    the one-time migration script runs) isn't re-imported as a duplicate."""
    scan_progress.status = "importing"
    scan_progress.total_files = len(tagged_files)
    scan_progress.processed_files = 0

    # Loaded once per scan run, not per file -- read the whole backup dict
    # up front rather than hitting the JSON file for every single import.
    # Mutated in place as this loop writes new entries, so a later file in
    # THIS SAME scan sharing a file_hash with an earlier one correctly sees
    # it as "already has a backup entry" too, not just entries that existed
    # before this scan started.
    artist_backup_data = artist_backup.load_backup(backup_path)
    backup_dirty = False

    imported = 0
    for i, (file_path, char_id, artist_id, container_name) in enumerate(tagged_files):
        scan_progress.current_file = os.path.basename(file_path)

        try:
            relative_path = import_root.to_relative(file_path, import_root_path)
            cursor = await db.execute(
                "SELECT 1 FROM images WHERE file_path = ? OR file_path = ?",
                (relative_path, file_path),
            )
            if not await cursor.fetchone():
                p = Path(file_path)
                file_size = p.stat().st_size
                file_format = p.suffix.lower()
                width, height = get_image_dimensions(file_path)
                file_hash = compute_file_hash(file_path)

                resolved_artist_id = artist_id
                backed_up_path = artist_backup_data.get(file_hash)
                if backed_up_path:
                    # An existing entry (from before this scan, or written
                    # moments ago by an earlier file in this same scan)
                    # always wins over whatever this file's own policy
                    # computed -- see ADR-0003.
                    resolved_artist_id = await get_or_create_tag_path(
                        db, "individual_tag", backed_up_path
                    )
                    if artist_id != 0:
                        this_path = await ancestor_path_names(db, "individual_tag", artist_id)
                        if this_path != backed_up_path:
                            conflict = {
                                "file_path": file_path,
                                "file_hash": file_hash,
                                "existing": backed_up_path,
                                "discarded": this_path,
                            }
                            artist_backup.append_conflict_log(conflicts_log_path, conflict)
                            scan_progress.conflicts.append(
                                f"{file_path}: 已有作者分類「{'/'.join(backed_up_path)}」，"
                                f"這次算出的「{'/'.join(this_path)}」被放棄"
                            )
                elif artist_id != 0:
                    # No existing entry at all -- this scan's own
                    # classification becomes the new backup entry.
                    new_path = await ancestor_path_names(db, "individual_tag", artist_id)
                    artist_backup_data[file_hash] = new_path
                    backup_dirty = True

                await db.execute(
                    """INSERT INTO images
                       (file_path, file_name, file_size, file_format,
                        image_width, image_height, file_hash, source_folder,
                        char_id, artist_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        relative_path,
                        p.name,
                        file_size,
                        file_format,
                        width,
                        height,
                        file_hash,
                        container_name,
                        char_id,
                        resolved_artist_id,
                    ),
                )
                imported += 1
        except Exception as e:
            scan_progress.errors.append(f"{file_path}: {str(e)}")

        scan_progress.processed_files += 1
        if (i + 1) % SCAN_BATCH_SIZE == 0:
            await db.commit()

    await db.commit()

    if backup_dirty:
        # One write for the whole scan, not per file -- matches
        # backfill_artist_backup.py's existing "load once, save once" idiom.
        artist_backup.save_backup(backup_path, artist_backup_data)

    cursor = await db.execute(
        "SELECT COUNT(DISTINCT char_id) FROM images WHERE char_id != 0"
    )
    total_characters = (await cursor.fetchone())[0]
    cursor = await db.execute(
        f"SELECT COUNT(*) FROM character_tag t WHERE {has_children_predicate('character_tag')}"
    )
    total_franchises = (await cursor.fetchone())[0]
    cursor = await db.execute(
        "SELECT COUNT(DISTINCT artist_id) FROM images WHERE artist_id != 0"
    )
    total_artists = (await cursor.fetchone())[0]

    await db.execute(
        """UPDATE scan_history SET
           total_files_found = ?, total_files_imported = ?,
           total_characters_found = ?, total_franchises_found = ?,
           total_artists_found = ?,
           completed_at = CURRENT_TIMESTAMP, status = 'completed'
           WHERE id = ?""",
        (
            len(tagged_files),
            imported,
            total_characters,
            total_franchises,
            total_artists,
            scan_id,
        ),
    )
    await db.commit()

    scan_progress.total_characters = total_characters
    scan_progress.total_franchises = total_franchises
    scan_progress.total_artists = total_artists
    scan_progress.status = "completed"
    scan_progress.end_time = time.time()


async def start_scan_task(
    root_path: str,
    containers: list[str],
    include_other: bool = True,
    char_policy: Optional[ClassificationPolicy] = None,
    artist_policy: Optional[ClassificationPolicy] = None,
    import_root_dir: Optional[str] = None,
) -> None:
    """
    Fire-and-forget scan launcher.
    Creates its own DB connection so it's safe to run as an asyncio.Task.
    """
    from database import create_db_connection

    scan_progress.reset()
    scan_progress.status = "scanning"
    scan_progress.start_time = time.time()

    db = await create_db_connection()
    try:
        await _run_scan_worker(
            db, root_path, containers, include_other=include_other,
            char_policy=char_policy, artist_policy=artist_policy,
            import_root_dir=import_root_dir,
        )
    finally:
        await db.close()


async def _run_scan_worker(
    db: aiosqlite.Connection,
    root_path: str,
    containers: list[str],
    include_other: bool = True,
    char_policy: Optional[ClassificationPolicy] = None,
    artist_policy: Optional[ClassificationPolicy] = None,
    import_root_dir: Optional[str] = None,
) -> None:
    """Actual scan worker — runs inside a background task."""
    root = Path(root_path)
    char_policy = char_policy or ClassificationPolicy("folder")
    artist_policy = artist_policy or ClassificationPolicy("folder")
    # Callers outside routes/scan.py (most existing tests, and any direct
    # worker invocation) don't necessarily care about the import-root feature
    # at all -- defaulting to root_path itself means file_path ends up
    # relative to exactly the folder that was scanned, which is what anyone
    # not passing this explicitly would expect. routes/scan.py always passes
    # the real persisted import root explicitly (see ADR-0004).
    import_root_dir = import_root_dir or root_path

    cursor = await db.execute(
        """INSERT INTO scan_history
           (root_path, folders_scanned, char_policy, char_fixed_id, artist_policy, artist_fixed_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            root_path,
            ",".join(containers),
            char_policy.mode,
            char_policy.fixed_id,
            artist_policy.mode,
            artist_policy.fixed_id,
        ),
    )
    scan_id = cursor.lastrowid
    await db.commit()

    try:
        # (file_path, folder_derived_char_id, folder_derived_artist_id, container_name)
        # -- folder_derived_* stays None whenever that axis's own policy isn't
        # "folder" (or the file isn't from that axis's container at all), and
        # _resolve_axis turns each into the actual char_id/artist_id to store.
        discovered: list[tuple[str, Optional[int], Optional[int], str]] = []

        for container_name in containers:
            if container_name not in CONTAINERS:
                scan_progress.errors.append(f"未知的分類容器: {container_name}")
                continue

            container_path = root / container_name
            if not container_path.exists():
                scan_progress.errors.append(f"資料夾不存在: {container_path}")
                continue

            scan_progress.current_folder = container_name
            is_characters = container_name == "characters"
            axis_policy = char_policy if is_characters else artist_policy

            if axis_policy.mode == "folder":
                table = CONTAINERS[container_name]["table"]
                pairs = await walk_into_tag_tree(db, table, container_path, ROOT_TAG_ID)
                await db.commit()
            else:
                # fixed/none: the folder structure won't be referenced by
                # anything, so skip tag node creation entirely -- discovery
                # only.
                pairs = [(path, None) for path in _walk_files_only(container_path)]

            if is_characters:
                discovered.extend((path, tag_id, None, container_name) for path, tag_id in pairs)
            else:
                discovered.extend((path, None, tag_id, container_name) for path, tag_id in pairs)

        if include_other:
            scan_progress.current_folder = "other"
            other_paths = walk_other_locations(root)
            discovered.extend((path, None, None, "other") for path in other_paths)

        tagged_files: list[tuple[str, int, int, str]] = [
            (
                path,
                _resolve_axis(char_policy, char_folder_id),
                _resolve_axis(artist_policy, artist_folder_id),
                container_name,
            )
            for path, char_folder_id, artist_folder_id, container_name in discovered
        ]

        await import_tagged_files(
            db, tagged_files, scan_id,
            backup_path=config.ARTIST_TAGS_BACKUP_PATH,
            conflicts_log_path=config.SCAN_CONFLICTS_LOG_PATH,
            import_root_path=import_root_dir,
        )

    except Exception as e:
        scan_progress.status = "failed"
        scan_progress.end_time = time.time()
        scan_progress.errors.append(f"掃描失敗: {str(e)}")
        await db.execute(
            "UPDATE scan_history SET status = 'failed', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (scan_id,),
        )
        await db.commit()
