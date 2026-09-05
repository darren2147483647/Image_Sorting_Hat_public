"""
圖像分類帽 — 統一的 character_tag 節點 API

取代舊的 /api/characters + /api/franchises：character_tag 只有一張表，
「系列」跟「角色」是各自獨立、可能重疊的屬性（has_children／is_referenced），
不是兩種互斥的資源類型，所以只用一個端點回傳所有非根節點。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
import aiosqlite

from database import get_db
from config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from tag_tree import (
    descendants_cte,
    find_nodes_by_normalized_name,
    find_sibling_case_insensitive,
    get_or_create_tag,
    get_or_create_tag_path,
    get_tag_node,
    list_tag_nodes,
    validate_tag_name,
)

router = APIRouter(prefix="/api/character-tags", tags=["character-tags"])

TABLE = "character_tag"
FK_COLUMN = "char_id"


@router.get("")
async def list_character_tags(
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    search: Optional[str] = None,
    parent_id: Optional[int] = None,
    has_children: Optional[bool] = Query(None, description="只看系列瀏覽用：有子節點的節點"),
    is_referenced: Optional[bool] = Query(None, description="只看角色瀏覽用：被影像直接引用的節點"),
    sort_by: str = Query("name", pattern="^(name|image_count)$"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    db: aiosqlite.Connection = Depends(get_db),
):
    """List every non-root character_tag node with has_children/is_referenced/
    direct_image_count/total_image_count. No hardcoded series-vs-character
    resource split: callers narrow the listing itself via has_children/
    is_referenced when they need a "series browser" or "character browser" view."""
    return await list_tag_nodes(
        db, TABLE, FK_COLUMN, page=page, per_page=per_page, search=search,
        parent_id=parent_id, has_children=has_children, is_referenced=is_referenced,
        sort_by=sort_by, sort_order=sort_order,
    )


@router.get("/{node_id}")
async def get_character_tag(node_id: int, db: aiosqlite.Connection = Depends(get_db)):
    """Get a single node's stats, breadcrumb, and direct children."""
    node = await get_tag_node(db, TABLE, FK_COLUMN, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="節點不存在")
    return node


@router.post("")
async def create_character_tag(
    name: str = Query(..., min_length=1),
    parent_id: Optional[int] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Create a new character/series node, for the lightbox "指定角色" flow
    (see ADR-0006). Unlike individual_tag (fixed two levels), character_tag
    has arbitrary depth, so a parent must be specified -- with exactly one
    exception: parent_id=None defaults to the `characters` node itself,
    found-or-created (it may genuinely not exist yet, even on an otherwise
    populated DB -- a fixed/none-policy scan, per ADR-0003, never runs
    walk_into_tag_tree and so never creates it). Any other parent_id must
    already reference a real node; this never auto-creates a missing
    ancestor chain beyond that one exception.

    If a character with this (normalized) name already exists ANYWHERE in
    the tree, this resolves to that existing node and its real parent --
    ignoring whatever parent_id was requested -- rather than creating a
    confusing near-duplicate under a different branch. A name matching more
    than one existing node (this app already has real cases of two
    different parents sharing a leaf name) is genuinely ambiguous and gets
    rejected rather than guessed at."""
    name = name.strip()

    # Checked unconditionally, before any resolution -- "characters" is
    # reserved regardless of whether it already exists as a node somewhere
    # in the tree.
    if name.upper() == "CHARACTERS":
        raise HTTPException(status_code=400, detail="不能使用「characters」作為角色名稱，避免跟這個特殊節點本身混淆")

    matches = await find_nodes_by_normalized_name(db, TABLE, name)
    if len(matches) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"「{name}」在樹裡有多個同名節點，無法自動判斷要指定哪一個，請改用既有節點的清單直接選取",
        )

    if matches:
        node_id = matches[0]
    else:
        if parent_id is None:
            # Not committed here -- deferred to the single commit point
            # below, so a subsequent validation failure can roll this
            # uncommitted `characters` node creation back too, rather than
            # leaving a stray node behind as a side effect of a request
            # that otherwise failed.
            resolved_parent_id = await get_or_create_tag_path(db, TABLE, ["characters"])
        else:
            cursor = await db.execute(f"SELECT id FROM {TABLE} WHERE id = ?", (parent_id,))
            if not await cursor.fetchone():
                raise HTTPException(status_code=404, detail="父節點不存在")
            resolved_parent_id = parent_id

        error = validate_tag_name(name)
        if error:
            await db.rollback()
            raise HTTPException(status_code=400, detail=error)
        node_id = await get_or_create_tag(db, TABLE, resolved_parent_id, name)

    await db.commit()

    cursor = await db.execute(f"SELECT id, name FROM {TABLE} WHERE id = ?", (node_id,))
    row = await cursor.fetchone()
    return {"id": row["id"], "name": row["name"]}


@router.put("/{node_id}")
async def update_character_tag(
    node_id: int,
    name: Optional[str] = None,
    parent_id: Optional[int] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Rename a node and/or move it under a different parent node."""
    if node_id == 0:
        raise HTTPException(status_code=400, detail="不能修改根節點")

    cursor = await db.execute(f"SELECT id, parent_id FROM {TABLE} WHERE id = ?", (node_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="節點不存在")

    updates = []
    params = []
    if parent_id is not None:
        if parent_id == node_id:
            raise HTTPException(status_code=400, detail="不能將節點設為自己的父節點")
        cursor = await db.execute(f"SELECT id FROM {TABLE} WHERE id = ?", (parent_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="目標父節點不存在")
        cursor = await db.execute(
            f"""{descendants_cte(TABLE)}
                SELECT 1 FROM descendants WHERE id = ?""",
            (node_id, parent_id),
        )
        if await cursor.fetchone():
            raise HTTPException(status_code=400, detail="不能把節點移到自己的子節點底下")
        updates.append("parent_id = ?")
        params.append(parent_id)

    if name is not None:
        name = name.strip()
        # Collision check uses whichever parent the node ends up under after
        # this request (the new parent_id if also being moved, else its
        # current one) -- parent_id has already been validated above by this
        # point, so target_parent_id is never a dangling/nonexistent id here.
        # A match against a DIFFERENT existing sibling is a real conflict
        # (this app has no merge tooling, see individual_tags.py) -- but a
        # match against the node ITSELF just means the new name is a
        # normalized-equivalent variant of its own current name. That's only
        # actually allowed through when the variant is itself still a legal
        # name (e.g. fixing casing: "char" -> "CHAR"); a trailing-dot/space
        # variant of your own name (e.g. "char" -> "char.") still gets
        # rejected by validate_tag_name below, same as it would for a brand
        # new name -- a self-match only means "don't treat this as a
        # conflict with a different node", not "skip validating the literal
        # string that's about to be stored" (see ADR-0005).
        target_parent_id = parent_id if parent_id is not None else row["parent_id"]
        existing_id = await find_sibling_case_insensitive(db, TABLE, target_parent_id, name)
        if existing_id is not None and existing_id != node_id:
            cursor = await db.execute(f"SELECT name FROM {TABLE} WHERE id = ?", (existing_id,))
            existing_name = (await cursor.fetchone())["name"]
            raise HTTPException(
                status_code=400,
                detail=f"這個名稱在資料夾層級會跟既有的「{existing_name}」衝突，無法使用",
            )
        error = validate_tag_name(name)
        if error:
            raise HTTPException(status_code=400, detail=error)
        updates.append("name = ?")
        params.append(name)

    if not updates:
        return {"message": "沒有需要更新的欄位"}

    params.append(node_id)
    await db.execute(f"UPDATE {TABLE} SET {', '.join(updates)} WHERE id = ?", params)
    await db.commit()
    return {"message": "節點已更新"}
