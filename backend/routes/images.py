"""
圖像分類帽 — 圖片相關 API
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
import aiosqlite

import artist_backup
import character_reassignment
import config
import import_root
from database import get_db
from config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from tag_tree import ROOT_TAG_ID, ancestor_path_names, combined_descendants_cte

router = APIRouter(prefix="/api/images", tags=["images"])

# Explicit overrides for formats where the OS's mimetypes registry either
# doesn't know the extension (.avif) or where we'd rather not depend on it
# being installed correctly at all.
_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".jfif": "image/jpeg",
    ".avif": "image/avif",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}


@router.get("")
async def list_images(
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    character: Optional[str] = None,
    char_id: Optional[int] = None,
    artist: Optional[str] = None,
    artist_id: Optional[int] = None,
    include_descendants: bool = Query(
        False, description="char_id/artist_id 是否展開到所有子孫節點"
    ),
    file_name: Optional[str] = None,
    source_folder: Optional[str] = None,
    file_format: Optional[str] = None,
    min_width: Optional[int] = None,
    max_width: Optional[int] = None,
    min_height: Optional[int] = None,
    max_height: Optional[int] = None,
    sort_by: str = Query("imported_at", pattern="^(imported_at|file_name|file_size|image_width)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db: aiosqlite.Connection = Depends(get_db),
):
    """List images with pagination and filtering."""
    conditions = []
    params = []

    if source_folder:
        conditions.append("i.source_folder = ?")
        params.append(source_folder)
    if file_format:
        conditions.append("i.file_format = ?")
        params.append(file_format.lower() if not file_format.startswith(".") else file_format)
    if file_name:
        conditions.append("i.file_name LIKE ?")
        params.append(f"%{file_name}%")
    if min_width:
        conditions.append("i.image_width >= ?")
        params.append(min_width)
    if max_width:
        conditions.append("i.image_width <= ?")
        params.append(max_width)
    if min_height:
        conditions.append("i.image_height >= ?")
        params.append(min_height)
    if max_height:
        conditions.append("i.image_height <= ?")
        params.append(max_height)

    joins = []
    cte_specs = []
    cte_params = []

    if char_id is not None:
        # 0 is a meaningful value here (root = "no character"), not "absent".
        if include_descendants:
            # Walk character_tag itself (not images) so intermediate nodes
            # with no direct image of their own still pull in their descendants.
            cte_specs.append(("character_tag", "char_descendants"))
            cte_params.append(char_id)
            conditions.append("i.char_id IN (SELECT id FROM char_descendants)")
        else:
            conditions.append("i.char_id = ?")
            params.append(char_id)
    if character:
        joins.append("JOIN character_tag c_filter ON i.char_id = c_filter.id")
        conditions.append("c_filter.name LIKE ?")
        params.append(f"%{character}%")

    if artist_id is not None:
        if include_descendants:
            cte_specs.append(("individual_tag", "artist_descendants"))
            cte_params.append(artist_id)
            conditions.append("i.artist_id IN (SELECT id FROM artist_descendants)")
        else:
            conditions.append("i.artist_id = ?")
            params.append(artist_id)
    if artist:
        joins.append("JOIN individual_tag a_filter ON i.artist_id = a_filter.id")
        conditions.append("a_filter.name LIKE ?")
        params.append(f"%{artist}%")

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    join_clause = " ".join(joins)
    cte_prefix = combined_descendants_cte(cte_specs)

    # Count total
    count_sql = f"{cte_prefix} SELECT COUNT(DISTINCT i.id) FROM images i {join_clause} WHERE {where_clause}"
    cursor = await db.execute(count_sql, cte_params + params)
    total = (await cursor.fetchone())[0]

    # Fetch page
    offset = (page - 1) * per_page
    query_sql = f"""
        {cte_prefix}
        SELECT DISTINCT i.id, i.file_path, i.file_name, i.file_size, i.file_format,
               i.image_width, i.image_height, i.source_folder, i.imported_at,
               i.char_id, i.artist_id
        FROM images i {join_clause}
        WHERE {where_clause}
        ORDER BY i.{sort_by} {sort_order}
        LIMIT ? OFFSET ?
    """
    cursor = await db.execute(query_sql, cte_params + params + [per_page, offset])
    rows = await cursor.fetchall()

    images = [dict(row) for row in rows]
    await _attach_tags(db, images)

    return {
        "images": images,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


async def _attach_tags(db: aiosqlite.Connection, images: list[dict]) -> None:
    """Attach `character_tags`/`artist_tags` as 0-or-1-element lists (kept as
    lists, not a single object, so existing frontend rendering built around
    the old many-to-many shape keeps working)."""
    for img in images:
        char_id = img.get("char_id", 0)
        if char_id and char_id != ROOT_TAG_ID:
            cursor = await db.execute(
                """SELECT t.id, t.name, p.name as franchise_name
                   FROM character_tag t
                   LEFT JOIN character_tag p ON t.parent_id = p.id
                   WHERE t.id = ?""",
                (char_id,),
            )
            row = await cursor.fetchone()
            img["character_tags"] = [dict(row)] if row else []
        else:
            img["character_tags"] = []

        artist_id = img.get("artist_id", 0)
        if artist_id and artist_id != ROOT_TAG_ID:
            cursor = await db.execute(
                "SELECT id, name FROM individual_tag WHERE id = ?", (artist_id,)
            )
            row = await cursor.fetchone()
            img["artist_tags"] = [dict(row)] if row else []
        else:
            img["artist_tags"] = []


@router.get("/formats")
async def list_image_formats(db: aiosqlite.Connection = Depends(get_db)):
    """Every distinct file_format actually present in the database, so the
    frontend filter can render options dynamically instead of hardcoding a
    list that goes stale every time a new format is supported."""
    cursor = await db.execute(
        "SELECT DISTINCT file_format FROM images WHERE file_format IS NOT NULL ORDER BY file_format"
    )
    rows = await cursor.fetchall()
    return {"formats": [row[0] for row in rows]}


@router.get("/{image_id}")
async def get_image(image_id: int, db: aiosqlite.Connection = Depends(get_db)):
    """Get single image details with all tags."""
    cursor = await db.execute("SELECT * FROM images WHERE id = ?", (image_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="圖片不存在")

    img = dict(row)
    await _attach_tags(db, [img])
    return img


@router.get("/{image_id}/file")
async def get_image_file(image_id: int, db: aiosqlite.Connection = Depends(get_db)):
    """Serve the actual image file."""
    cursor = await db.execute("SELECT file_path FROM images WHERE id = ?", (image_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="圖片不存在")

    root = import_root.load_import_root(config.IMPORT_ROOT_PATH)
    file_path = import_root.resolve(row[0], root)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="圖片檔案不存在")

    media_type = _MEDIA_TYPES.get(Path(file_path).suffix.lower())
    return FileResponse(file_path, media_type=media_type)


@router.delete("/{image_id}")
async def delete_image(image_id: int, db: aiosqlite.Connection = Depends(get_db)):
    """Remove an image's row from `images` entirely (the file on disk is
    untouched) -- distinct from delete_tag below, which only resets
    char_id/artist_id back to 0. Once this row is gone, the next rescan's
    insert-only logic treats the file at its (now-corrected) path as new and
    reimports it with a fresh classification, so "move the file to the right
    folder, remove it from tracking, rescan" reclassifies an image without
    ever needing to update an existing row."""
    cursor = await db.execute("DELETE FROM images WHERE id = ?", (image_id,))
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="圖片不存在")
    return {"message": "已移出追蹤"}


@router.post("/{image_id}/tags/character")
async def set_character_tag(
    image_id: int,
    character_id: int = Query(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Set an image's char_id AND move its file to match (see ADR-0006).
    There is only ever one character per image, so this replaces whatever
    was set before rather than adding a row. Unlike set_artist_tag
    (folder-independent by design), char_id's whole premise is that it
    always corresponds to the image's real folder location (see
    CONTEXT.md), so this can't be a DB-only write -- it delegates the
    actual file move to character_reassignment, kept as a separate module
    since it's the riskiest part of this app (real writes to the user's
    disk)."""
    cursor = await db.execute("SELECT id, file_path FROM images WHERE id = ?", (image_id,))
    image_row = await cursor.fetchone()
    if not image_row:
        raise HTTPException(status_code=404, detail="圖片不存在")

    if character_id == ROOT_TAG_ID:
        raise HTTPException(status_code=400, detail="不能指定為根節點")

    cursor = await db.execute("SELECT id FROM character_tag WHERE id = ?", (character_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="角色不存在")

    import_root_dir = import_root.load_import_root(config.IMPORT_ROOT_PATH)
    current_path = import_root.resolve(image_row["file_path"], import_root_dir)
    target_chain = await ancestor_path_names(db, "character_tag", character_id)

    try:
        new_path = character_reassignment.move_to_character_folder(
            current_path, import_root_dir, target_chain
        )
    except character_reassignment.DestinationExistsError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # to_relative() runs inside this try too, not just the DB write -- it's
    # a step that happens after the file has already physically moved, so
    # any failure here needs the same rollback as a failed DB write, not
    # just the ones that happen to come after it.
    try:
        new_relative_path = import_root.to_relative(new_path, import_root_dir)
        await db.execute(
            "UPDATE images SET char_id = ?, file_path = ? WHERE id = ?",
            (character_id, new_relative_path, image_id),
        )
        await db.commit()
    except Exception:
        # The file move already succeeded at this point -- undo it so the
        # file's real location and the DB's file_path never drift out of
        # sync, then let the original failure propagate.
        character_reassignment.move_back(current_path, new_path)
        raise

    return {"message": "標註已新增"}


@router.post("/{image_id}/tags/artist")
async def set_artist_tag(
    image_id: int,
    artist_id: int = Query(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Set an image's artist_id (same single-value semantics as character).

    artist_id is decoupled from folder position (unlike char_id), so it's the
    one classification that only lives in the DB -- also record it in the
    filesystem-level backup (keyed by file_hash, immune to file moves) so a
    rescan can restore it even if the DB itself is ever wiped and rebuilt.
    """
    cursor = await db.execute("SELECT id, file_hash FROM images WHERE id = ?", (image_id,))
    image_row = await cursor.fetchone()
    if not image_row:
        raise HTTPException(status_code=404, detail="圖片不存在")

    cursor = await db.execute("SELECT id FROM individual_tag WHERE id = ?", (artist_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="作者不存在")

    await db.execute("UPDATE images SET artist_id = ? WHERE id = ?", (artist_id, image_id))
    await db.commit()

    # The DB write above already succeeded and is what the running app
    # actually uses -- a failure writing the disaster-recovery backup (full
    # disk, locked file, ...) shouldn't turn an otherwise-successful request
    # into a 500. It's recoverable: re-touching the same tag retries it.
    if image_row["file_hash"]:
        try:
            if artist_id == ROOT_TAG_ID:
                artist_backup.remove_entry(config.ARTIST_TAGS_BACKUP_PATH, image_row["file_hash"])
            else:
                path = await ancestor_path_names(db, "individual_tag", artist_id)
                artist_backup.set_entry(config.ARTIST_TAGS_BACKUP_PATH, image_row["file_hash"], path)
        except OSError as e:
            print(f"⚠️ 作者分類備份寫入失敗（不影響本次標註結果）: {e}")

    return {"message": "標註已新增"}


@router.delete("/{image_id}/tags/{tag_id}")
async def delete_tag(
    image_id: int,
    tag_id: int,
    tag_type: str = Query("character", pattern="^(character|artist)$"),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Reset char_id/artist_id back to 0 (root = no tag), only if it
    currently matches `tag_id` — there is no separate join-row id anymore."""
    column = "char_id" if tag_type == "character" else "artist_id"
    cursor = await db.execute(
        f"UPDATE images SET {column} = 0 WHERE id = ? AND {column} = ?",
        (image_id, tag_id),
    )
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="標註不存在")

    # An explicit clear should stick -- without this, the next rescan (after
    # a 移出追蹤 delete+reimport) would silently resurrect the classification
    # the user just removed. char_id has no backup at all, so this only
    # applies to the artist_id axis.
    if tag_type == "artist":
        cursor = await db.execute("SELECT file_hash FROM images WHERE id = ?", (image_id,))
        row = await cursor.fetchone()
        if row and row["file_hash"]:
            try:
                artist_backup.remove_entry(config.ARTIST_TAGS_BACKUP_PATH, row["file_hash"])
            except OSError as e:
                print(f"⚠️ 作者分類備份移除失敗（不影響本次清除結果）: {e}")

    return {"message": "標註已刪除"}
