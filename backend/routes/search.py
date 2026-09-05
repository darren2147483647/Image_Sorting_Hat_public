"""
圖像分類帽 — 搜尋 API
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
import aiosqlite

from database import get_db
from tag_tree import has_children_predicate, is_referenced_predicate

router = APIRouter(prefix="/api/search", tags=["search"])

# The "franchise" search bucket means a container/grouping node, i.e. one
# with children. CONTEXT.md's "系列" is satisfied by every non-root node, so
# it's not what this bucket wants -- using it here would duplicate every
# referenced leaf into both the character and franchise buckets.
_HAS_CHILDREN = has_children_predicate("character_tag")
_IS_REFERENCED_CHARACTER = is_referenced_predicate("char_id")


@router.get("")
async def global_search(
    q: str = Query(..., min_length=1, description="搜尋關鍵字"),
    type: Optional[str] = Query(None, pattern="^(character|franchise|artist|all)$"),
    limit: int = Query(20, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Global search across characters, franchises, and artists.
    Returns grouped results.
    """
    search_term = f"%{q}%"
    results = {"query": q, "characters": [], "franchises": [], "artists": []}

    if type in (None, "all", "character"):
        cursor = await db.execute(
            f"""SELECT t.id, t.name, p.name as franchise_name,
                       COUNT(i.id) as image_count
                FROM character_tag t
                LEFT JOIN character_tag p ON t.parent_id = p.id
                LEFT JOIN images i ON i.char_id = t.id
                WHERE t.name LIKE ? AND {_IS_REFERENCED_CHARACTER}
                GROUP BY t.id
                ORDER BY image_count DESC
                LIMIT ?""",
            (search_term, limit),
        )
        results["characters"] = [dict(r) for r in await cursor.fetchall()]

    if type in (None, "all", "franchise"):
        cursor = await db.execute(
            f"""SELECT t.id, t.name,
                       (SELECT COUNT(*) FROM character_tag c WHERE c.parent_id = t.id) as sub_count
                FROM character_tag t
                WHERE t.name LIKE ? AND {_HAS_CHILDREN}
                ORDER BY sub_count DESC
                LIMIT ?""",
            (search_term, limit),
        )
        results["franchises"] = [dict(r) for r in await cursor.fetchall()]

    if type in (None, "all", "artist"):
        cursor = await db.execute(
            """SELECT t.id, t.name, COUNT(i.id) as image_count
               FROM individual_tag t
               LEFT JOIN images i ON i.artist_id = t.id
               WHERE t.name LIKE ? AND t.id != 0
               GROUP BY t.id
               ORDER BY image_count DESC
               LIMIT ?""",
            (search_term, limit),
        )
        results["artists"] = [dict(r) for r in await cursor.fetchall()]

    results["total"] = (
        len(results["characters"])
        + len(results["franchises"])
        + len(results["artists"])
    )

    return results


@router.get("/suggest")
async def search_suggest(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Quick search suggestions for autocomplete."""
    search_term = f"%{q}%"
    suggestions = []

    cursor = await db.execute(
        f"SELECT t.id, t.name FROM character_tag t WHERE t.name LIKE ? AND {_IS_REFERENCED_CHARACTER} LIMIT ?",
        (search_term, limit),
    )
    for r in await cursor.fetchall():
        suggestions.append({"type": "character", "id": r[0], "name": r[1], "label": f"👤 {r[1]}"})

    cursor = await db.execute(
        f"SELECT t.id, t.name FROM character_tag t WHERE t.name LIKE ? AND {_HAS_CHILDREN} LIMIT ?",
        (search_term, limit),
    )
    for r in await cursor.fetchall():
        suggestions.append({"type": "franchise", "id": r[0], "name": r[1], "label": f"🎮 {r[1]}"})

    cursor = await db.execute(
        "SELECT id, name FROM individual_tag WHERE name LIKE ? AND id != 0 LIMIT ?",
        (search_term, limit),
    )
    for r in await cursor.fetchall():
        suggestions.append({"type": "artist", "id": r[0], "name": r[1], "label": f"🎨 {r[1]}"})

    return {"suggestions": suggestions[:limit]}
