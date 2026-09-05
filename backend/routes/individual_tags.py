"""
圖像分類帽 — individual_tag 節點 API

列表／詳情形狀跟 character_tags.py 相同，只是查 individual_tag 表，供作者管理頁面使用。
不含 character_tags.py 的 PUT 重新命名／搬移端點（作者節點目前沒有這個需求，跟舊版
artists 表一樣沒有編輯功能）。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
import aiosqlite

from database import get_db
from config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from tag_tree import (
    find_sibling_case_insensitive,
    get_or_create_tag,
    get_or_create_tag_path,
    get_tag_node,
    list_tag_nodes,
    validate_tag_name,
)

router = APIRouter(prefix="/api/individual-tags", tags=["individual-tags"])

TABLE = "individual_tag"
FK_COLUMN = "artist_id"


@router.get("")
async def list_individual_tags(
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    search: Optional[str] = None,
    parent_id: Optional[int] = None,
    has_children: Optional[bool] = None,
    is_referenced: Optional[bool] = None,
    sort_by: str = Query("name", pattern="^(name|image_count)$"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    db: aiosqlite.Connection = Depends(get_db),
):
    """List every non-root individual_tag node with has_children/is_referenced/
    direct_image_count/total_image_count."""
    return await list_tag_nodes(
        db, TABLE, FK_COLUMN, page=page, per_page=per_page, search=search,
        parent_id=parent_id, has_children=has_children, is_referenced=is_referenced,
        sort_by=sort_by, sort_order=sort_order,
    )


@router.get("/{node_id}")
async def get_individual_tag(node_id: int, db: aiosqlite.Connection = Depends(get_db)):
    """Get a single node's stats, breadcrumb, and direct children."""
    node = await get_tag_node(db, TABLE, FK_COLUMN, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="節點不存在")
    return node


@router.post("")
async def create_individual_tag(
    name: str = Query(..., min_length=1),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Create a new artist node under the individuals container, for the
    lightbox "+新增作者" flow. Case-insensitive find-or-create: a name that
    already exists (in any casing) resolves to the existing node instead of
    creating a near-duplicate -- individual_tag has no rename/merge tooling,
    so two nodes for the same real artist would be a permanent, unfixable
    fork."""
    name = name.strip()

    # Same find-or-create mechanism as everywhere else this tree is walked
    # (scanner.walk_into_tag_tree, the artist-backup reapplication path) --
    # the container always exists post-flattening (ADR-0002), so this is
    # effectively find-only, but reusing the shared helper keeps "individuals"
    # as a literal in one idiom instead of a bespoke SELECT.
    individuals_id = await get_or_create_tag_path(db, TABLE, ["individuals"])
    await db.commit()

    # Check for an existing (normalized-equivalent) sibling BEFORE validating
    # -- e.g. "Ooguni." is itself an illegal name (trailing dot, see
    # ADR-0005), but if "Ooguni" already exists, this must resolve to that
    # existing node rather than being rejected: we're not creating anything
    # new, just reusing an already-valid stored name.
    existing_id = await find_sibling_case_insensitive(db, TABLE, individuals_id, name)
    node_id = existing_id
    if node_id is None:
        error = validate_tag_name(name)
        if error:
            raise HTTPException(status_code=400, detail=error)
        node_id = await get_or_create_tag(db, TABLE, individuals_id, name)
        await db.commit()

    cursor = await db.execute("SELECT id, name FROM individual_tag WHERE id = ?", (node_id,))
    row = await cursor.fetchone()
    return {"id": row["id"], "name": row["name"]}
