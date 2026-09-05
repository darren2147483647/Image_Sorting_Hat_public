"""
圖像分類帽 — Tag 樹共用工具

character_tag／individual_tag 兩張表 schema 相同、彼此獨立，都遵守同一個規則：
根節點是真實存在的哨兵列（id=0），其餘節點的 parent_id 一律指向某個真實 id，
讓 UNIQUE(parent_id, name) 在任何深度都能正確擋下重複節點。
"""
from typing import Optional

import aiosqlite

TAG_TABLES = ("character_tag", "individual_tag")

ROOT_TAG_ID = 0

_ILLEGAL_NAME_CHARS = set('<>:"/\\|?*')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}
# Windows silently strips these off the end of a real folder name -- shared
# by validate_tag_name (rejects a name ending in one of these) and
# find_sibling_case_insensitive (strips them before comparing two names, so
# "Foo" and "Foo." resolve to the same node). One constant so the two stay
# in sync if the rule ever changes.
_TRAILING_ILLEGAL_CHARS = ". "


def validate_tag_name(name: str) -> Optional[str]:
    """A tag node's name doubles as a real Windows folder-name component
    (see ADR-0005) -- this rejects anything that wouldn't be a legal one:
    empty, the illegal characters, control characters, reserved device
    names (case-insensitive, exact match only -- "CONTEST" is fine), and a
    trailing dot/space (Windows silently strips these, so a stored name
    ending in one would silently drift from the real folder it names).

    Returns None when `name` is valid, otherwise a message describing which
    rule it broke. This is also this app's XSS defense for tag names: every
    current frontend render site breaks out via `<` or `"`, both already
    illegal here, so there's no separate escaping rule to maintain."""
    if not name:
        return "名稱不能是空白"
    illegal = _ILLEGAL_NAME_CHARS & set(name)
    if illegal:
        return f"名稱不能包含以下字元：{' '.join(sorted(illegal))}"
    if any(ord(c) < 0x20 for c in name):
        return "名稱不能包含控制字元"
    if name.upper() in _RESERVED_NAMES:
        return f"「{name}」是 Windows 保留字，不能使用"
    if name != name.rstrip(_TRAILING_ILLEGAL_CHARS):
        return "名稱結尾不能是點或空白"
    return None


def _recursive_descendants_term(table: str, cte_name: str, anchor_expr: str) -> str:
    """The recursive term shared by every "walk down to every descendant"
    query in this module: reachable ids starting at `anchor_expr` and
    following parent->child downward. `anchor_expr` is inlined as SQL text,
    not bound -- it's normally a `?` placeholder (descendants_cte,
    combined_descendants_cte), but _node_stats_columns's total_image_count
    needs a correlated column reference (e.g. `t.id`) instead, since that
    one recomputes per output row and can't bind a single shared parameter
    for all of them. One shared body means the join condition (and any
    future rule change, e.g. excluding a subtree) only has one place to
    edit; each caller still controls its own wrapping."""
    return f"""{cte_name}(id) AS (
            SELECT id FROM {table} WHERE id = {anchor_expr}
            UNION ALL
            SELECT c.id FROM {table} c JOIN {cte_name} d ON c.parent_id = d.id
        )"""


def descendants_cte(table: str, cte_name: str = "descendants") -> str:
    """A recursive CTE selecting a node's own id plus every descendant's id.
    Expects the anchor node's id as the first (or only) `?` parameter."""
    if table not in TAG_TABLES:
        raise ValueError(f"unknown tag table: {table}")
    return f"WITH RECURSIVE {_recursive_descendants_term(table, cte_name, '?')}"


def combined_descendants_cte(specs: list[tuple[str, str]]) -> str:
    """Build one WITH RECURSIVE clause covering several descendant sets at
    once (e.g. both a character_tag and an individual_tag expansion in the
    same query). SQLite only allows a single WITH keyword per statement, so
    concatenating multiple standalone `descendants_cte()` outputs is invalid
    SQL -- this combines them into one comma-separated WITH RECURSIVE.

    `specs` is a list of (table, cte_name) pairs. Each resulting CTE expects
    its anchor node id as one `?` parameter, in the same order as `specs`.
    Returns "" for an empty list (nothing to prefix).
    """
    if not specs:
        return ""
    parts = []
    for table, cte_name in specs:
        if table not in TAG_TABLES:
            raise ValueError(f"unknown tag table: {table}")
        parts.append(_recursive_descendants_term(table, cte_name, "?"))
    return "WITH RECURSIVE " + ", ".join(parts)


def has_children_predicate(table: str, alias: str = "t") -> str:
    """True iff the node has at least one child. This is the "container/
    grouping node" concept (a distinct search bucket, a progress-counter
    label, etc.) -- NOT the same as CONTEXT.md's "系列", which (being just
    "any non-root node") isn't a useful SQL filter on its own, since it's
    trivially `id != 0`."""
    if table not in TAG_TABLES:
        raise ValueError(f"unknown tag table: {table}")
    return f"{alias}.id != 0 AND EXISTS (SELECT 1 FROM {table} c WHERE c.parent_id = {alias}.id)"


def is_referenced_predicate(fk_column: str, alias: str = "t") -> str:
    """A tag node is "referenced" (a real character/artist, not just a path
    node) iff some image points at it via `fk_column`. Excludes the root:
    the other tree's images use fk_column=0 to mean "not applicable", which
    would otherwise make the root look referenced."""
    return f"{alias}.id != 0 AND EXISTS (SELECT 1 FROM images i WHERE i.{fk_column} = {alias}.id)"


def _node_stats_columns(table: str, fk_column: str, alias: str = "t") -> str:
    """SQL fragment computing has_children/is_referenced/direct_image_count/
    total_image_count for each row of `table` aliased as `alias`, meant to be
    interpolated into a SELECT list. Correlated (references `{alias}.id`
    directly) since these are per-row computed columns, not standalone
    parameterized queries."""
    if table not in TAG_TABLES:
        raise ValueError(f"unknown tag table: {table}")
    return f"""
        EXISTS (SELECT 1 FROM {table} c WHERE c.parent_id = {alias}.id) as has_children,
        EXISTS (SELECT 1 FROM images i WHERE i.{fk_column} = {alias}.id) as is_referenced,
        (SELECT COUNT(*) FROM images i WHERE i.{fk_column} = {alias}.id) as direct_image_count,
        (WITH RECURSIVE {_recursive_descendants_term(table, "node_descendants", f"{alias}.id")}
        SELECT COUNT(*) FROM images i
        WHERE i.{fk_column} IN (SELECT id FROM node_descendants)) as total_image_count
    """


def _coerce_node_row(row: dict) -> dict:
    row = dict(row)
    row["has_children"] = bool(row["has_children"])
    row["is_referenced"] = bool(row["is_referenced"])
    return row


_SORT_COLUMNS = {
    "name": "t.name",
    "image_count": "total_image_count",
}


async def list_tag_nodes(
    db: aiosqlite.Connection,
    table: str,
    fk_column: str,
    *,
    page: int,
    per_page: int,
    search: Optional[str] = None,
    parent_id: Optional[int] = None,
    has_children: Optional[bool] = None,
    is_referenced: Optional[bool] = None,
    sort_by: str = "name",
    sort_order: str = "asc",
) -> dict:
    """List every non-root node of `table`, each annotated with
    has_children/is_referenced/direct_image_count/total_image_count.
    Series and character are independent properties here, not two separate
    resource types -- callers decide how to group/display, or narrow the
    listing itself with `has_children`/`is_referenced` (e.g. a "series
    browser" view wants has_children=True, a "character browser" view wants
    is_referenced=True) so pagination counts stay correct for that view.

    `sort_by` is "name" or "image_count" (sorts by total_image_count, i.e.
    including descendants -- a container node's direct_image_count is
    usually 0, so sorting by that would rarely be meaningful)."""
    if sort_by not in _SORT_COLUMNS:
        raise ValueError(f"unknown sort_by: {sort_by}")
    if sort_order not in ("asc", "desc"):
        raise ValueError(f"unknown sort_order: {sort_order}")

    conditions = ["t.id != 0"]
    params: list = []

    if search:
        conditions.append("t.name LIKE ?")
        params.append(f"%{search}%")
    if parent_id is not None:
        conditions.append("t.parent_id = ?")
        params.append(parent_id)
    if has_children is not None:
        exists_children = f"EXISTS (SELECT 1 FROM {table} c WHERE c.parent_id = t.id)"
        conditions.append(exists_children if has_children else f"NOT {exists_children}")
    if is_referenced is not None:
        exists_ref = f"EXISTS (SELECT 1 FROM images i WHERE i.{fk_column} = t.id)"
        conditions.append(exists_ref if is_referenced else f"NOT {exists_ref}")

    where_clause = " AND ".join(conditions)

    cursor = await db.execute(f"SELECT COUNT(*) FROM {table} t WHERE {where_clause}", params)
    total = (await cursor.fetchone())[0]

    offset = (page - 1) * per_page
    stats_cols = _node_stats_columns(table, fk_column)
    order_col = _SORT_COLUMNS[sort_by]
    cursor = await db.execute(
        f"""SELECT t.id, t.name, t.parent_id, p.name as parent_name, t.created_at, {stats_cols}
            FROM {table} t
            LEFT JOIN {table} p ON t.parent_id = p.id
            WHERE {where_clause}
            ORDER BY {order_col} {sort_order}, t.id ASC
            LIMIT ? OFFSET ?""",
        params + [per_page, offset],
    )
    rows = await cursor.fetchall()

    return {
        "nodes": [_coerce_node_row(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


async def get_tag_node(
    db: aiosqlite.Connection, table: str, fk_column: str, node_id: int
) -> Optional[dict]:
    """A single non-root node with the same four stats plus its breadcrumb
    (ancestor chain, root excluded) and direct children."""
    stats_cols = _node_stats_columns(table, fk_column)
    cursor = await db.execute(
        f"""SELECT t.id, t.name, t.parent_id, p.name as parent_name, t.created_at, {stats_cols}
            FROM {table} t
            LEFT JOIN {table} p ON t.parent_id = p.id
            WHERE t.id = ? AND t.id != 0""",
        (node_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None

    data = _coerce_node_row(row)

    cursor = await db.execute(
        f"SELECT id, name FROM {table} WHERE parent_id = ? ORDER BY name", (node_id,)
    )
    data["children"] = [dict(r) for r in await cursor.fetchall()]

    data["breadcrumb"] = await ancestor_path_names(db, table, data["parent_id"])

    return data


async def get_or_create_tag(
    db: aiosqlite.Connection, table: str, parent_id: int, name: str
) -> int:
    """Find the tag node at (parent_id, name) in `table`, creating it if absent.

    Uses cursor.rowcount (not lastrowid) to detect whether the INSERT actually
    happened, since lastrowid can retain a stale value from a previous insert
    on the same connection when this one is ignored.
    """
    if table not in TAG_TABLES:
        raise ValueError(f"unknown tag table: {table}")

    cursor = await db.execute(
        f"INSERT OR IGNORE INTO {table} (parent_id, name) VALUES (?, ?)",
        (parent_id, name),
    )
    if cursor.rowcount == 1:
        return cursor.lastrowid

    cursor = await db.execute(
        f"SELECT id FROM {table} WHERE parent_id = ? AND name = ?",
        (parent_id, name),
    )
    row = await cursor.fetchone()
    return row[0]


async def ancestor_path_names(db: aiosqlite.Connection, table: str, node_id: int) -> list[str]:
    """Root-to-leaf names for node_id, including node_id itself, excluding
    the id=0 sentinel. Same shape as artist_backup's stored paths -- this is
    what turns a resolved tag id back into something durable to persist."""
    if table not in TAG_TABLES:
        raise ValueError(f"unknown tag table: {table}")

    names: list[str] = []
    current_id = node_id
    while current_id != ROOT_TAG_ID:
        cursor = await db.execute(
            f"SELECT name, parent_id FROM {table} WHERE id = ?", (current_id,)
        )
        row = await cursor.fetchone()
        if not row:
            break
        names.insert(0, row["name"])
        current_id = row["parent_id"]
    return names


async def find_sibling_case_insensitive(
    db: aiosqlite.Connection, table: str, parent_id: int, name: str
) -> Optional[int]:
    """Case-insensitive, trailing-dot/space-insensitive lookup among
    parent_id's direct children, for the lightbox "create artist" flow and
    tag-name validation (see ADR-0005) -- UNIQUE(parent_id, name) itself is
    exact-match (correctly so for scanner.walk_into_tag_tree, which must
    preserve real folder-name casing), so this is a separate, additive check
    used only where this looser equivalence is explicitly wanted. COLLATE
    NOCASE only folds ASCII letters, which is exactly right here: CJK names
    have no case to fold, so they're unaffected. RTRIM(x, _TRAILING_ILLEGAL_CHARS)
    strips any trailing dots/spaces from both sides before comparing, matching
    what Windows itself silently strips from a real folder name -- "Foo" and
    "Foo." are the same real folder, so they resolve to the same node here
    too."""
    if table not in TAG_TABLES:
        raise ValueError(f"unknown tag table: {table}")

    cursor = await db.execute(
        f"""SELECT id FROM {table}
            WHERE parent_id = ? AND RTRIM(name, '{_TRAILING_ILLEGAL_CHARS}') = RTRIM(?, '{_TRAILING_ILLEGAL_CHARS}') COLLATE NOCASE""",
        (parent_id, name),
    )
    row = await cursor.fetchone()
    return row["id"] if row else None


async def find_nodes_by_normalized_name(db: aiosqlite.Connection, table: str, name: str) -> list[int]:
    """Every node in `table` (any parent, any depth -- unlike
    find_sibling_case_insensitive, NOT scoped to one parent) whose name
    matches `name` after the same case/trailing-dot-space normalization.
    Used by "指定角色" (see ADR-0006) to detect whether a character with this
    name already exists anywhere in the tree, so creating one under a
    different parent than where it already lives doesn't produce a
    confusing near-duplicate. Root (id=0) is never a candidate -- its name
    is a sentinel, not a real classification, even if it happens to match."""
    if table not in TAG_TABLES:
        raise ValueError(f"unknown tag table: {table}")

    cursor = await db.execute(
        f"""SELECT id FROM {table}
            WHERE id != 0 AND RTRIM(name, '{_TRAILING_ILLEGAL_CHARS}') = RTRIM(?, '{_TRAILING_ILLEGAL_CHARS}') COLLATE NOCASE""",
        (name,),
    )
    rows = await cursor.fetchall()
    return [row["id"] for row in rows]


async def get_or_create_tag_path(db: aiosqlite.Connection, table: str, path: list[str]) -> int:
    """Inverse of ancestor_path_names: walk/create each level from the root,
    returning the resolved leaf id. Empty path resolves to ROOT_TAG_ID (0).
    Driven by a stored name path rather than real folders -- otherwise the
    same "find or create each level" logic scanner.walk_into_tag_tree uses."""
    parent_id = ROOT_TAG_ID
    for name in path:
        parent_id = await get_or_create_tag(db, table, parent_id, name)
    return parent_id
