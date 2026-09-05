from pathlib import Path

import pytest
from fastapi import HTTPException

from routes import character_tags
from tests.test_scanner import make_image, get_image
from tests.test_tag_node_listing import seed_overlap_tree


async def run_scan(db, root: Path, containers: list[str]):
    import scanner
    scanner.scan_progress.reset()
    await scanner._run_scan_worker(db, str(root), containers)


async def test_list_endpoint_matches_shared_helper(db, tmp_path):
    await seed_overlap_tree(db, tmp_path)

    result = await character_tags.list_character_tags(
        page=1, per_page=50, search=None, parent_id=None,
        has_children=None, is_referenced=None,
        sort_by="name", sort_order="asc", db=db,
    )
    names = {n["name"] for n in result["nodes"]}
    assert "root" not in names
    assert "game" in names


async def test_list_endpoint_exposes_sort_params(db, tmp_path):
    a = tmp_path / "characters" / "aaa" / "char" / "1.jpg"
    z = tmp_path / "characters" / "zzz" / "char" / "1.jpg"
    make_image(a)
    make_image(z)
    await run_scan(db, tmp_path, ["characters"])

    result = await character_tags.list_character_tags(
        page=1, per_page=50, search=None, parent_id=None,
        has_children=None, is_referenced=None,
        sort_by="name", sort_order="desc", db=db,
    )
    names = [n["name"] for n in result["nodes"]]
    assert names.index("zzz") < names.index("aaa")


async def test_get_endpoint_404s_for_root_and_missing(db, tmp_path):
    with pytest.raises(HTTPException) as exc_info:
        await character_tags.get_character_tag(node_id=0, db=db)
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        await character_tags.get_character_tag(node_id=999999, db=db)
    assert exc_info.value.status_code == 404


async def test_update_rejects_self_parent(db, tmp_path):
    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)
    char_id = row["char_id"]

    with pytest.raises(HTTPException) as exc_info:
        await character_tags.update_character_tag(node_id=char_id, name=None, parent_id=char_id, db=db)
    assert exc_info.value.status_code == 400


async def test_update_rejects_moving_under_own_descendant(db, tmp_path):
    img = tmp_path / "characters" / "game" / "ba" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])

    cursor = await db.execute("SELECT id FROM character_tag WHERE name = 'game'")
    game_id = (await cursor.fetchone())["id"]
    cursor = await db.execute("SELECT id FROM character_tag WHERE name = 'ba'")
    ba_id = (await cursor.fetchone())["id"]

    with pytest.raises(HTTPException) as exc_info:
        await character_tags.update_character_tag(node_id=game_id, name=None, parent_id=ba_id, db=db)
    assert exc_info.value.status_code == 400


async def test_update_renames_node(db, tmp_path):
    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)

    await character_tags.update_character_tag(node_id=row["char_id"], name="renamed", parent_id=None, db=db)

    cursor = await db.execute("SELECT name FROM character_tag WHERE id = ?", (row["char_id"],))
    assert (await cursor.fetchone())["name"] == "renamed"


async def test_update_rejects_windows_illegal_character(db, tmp_path):
    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)

    with pytest.raises(HTTPException) as exc_info:
        await character_tags.update_character_tag(node_id=row["char_id"], name="foo<bar", parent_id=None, db=db)
    assert exc_info.value.status_code == 400

    cursor = await db.execute("SELECT name FROM character_tag WHERE id = ?", (row["char_id"],))
    assert (await cursor.fetchone())["name"] == "char"  # untouched


# --- create_character_tag ---------------------------------------------


async def test_create_defaults_to_characters_node_when_no_parent_given(db):
    result = await character_tags.create_character_tag(name="新角色", parent_id=None, db=db)

    cursor = await db.execute(
        "SELECT c.name, p.name as parent_name FROM character_tag c "
        "JOIN character_tag p ON c.parent_id = p.id WHERE c.id = ?",
        (result["id"],),
    )
    row = await cursor.fetchone()
    assert row["name"] == "新角色"
    assert row["parent_name"] == "characters"


async def test_create_finds_or_creates_the_characters_node_itself(db):
    """The `characters` node may not exist yet, even on a populated DB (a
    fixed/none-policy scan never creates it -- see ADR-0003)."""
    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE name = 'characters'")
    assert (await cursor.fetchone())["n"] == 0

    await character_tags.create_character_tag(name="新角色", parent_id=None, db=db)

    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE name = 'characters'")
    assert (await cursor.fetchone())["n"] == 1


async def test_create_under_existing_parent(db):
    cursor = await db.execute("INSERT INTO character_tag (parent_id, name) VALUES (0, 'game')")
    await db.commit()
    game_id = cursor.lastrowid

    result = await character_tags.create_character_tag(name="新角色", parent_id=game_id, db=db)

    cursor = await db.execute("SELECT parent_id FROM character_tag WHERE id = ?", (result["id"],))
    assert (await cursor.fetchone())["parent_id"] == game_id


async def test_create_rejects_nonexistent_parent(db):
    with pytest.raises(HTTPException) as exc_info:
        await character_tags.create_character_tag(name="新角色", parent_id=999999, db=db)
    assert exc_info.value.status_code == 404

    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE name = '新角色'")
    assert (await cursor.fetchone())["n"] == 0


async def test_create_does_not_auto_create_missing_ancestor_chain(db):
    """Unlike parent_id=None (the `characters` exception), any OTHER
    parent_id must already exist -- no auto-creating a missing chain."""
    with pytest.raises(HTTPException) as exc_info:
        await character_tags.create_character_tag(name="leaf", parent_id=12345, db=db)
    assert exc_info.value.status_code == 404
    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag")
    assert (await cursor.fetchone())["n"] == 1  # only the root sentinel


async def test_create_rejects_illegal_name(db):
    with pytest.raises(HTTPException) as exc_info:
        await character_tags.create_character_tag(name="foo<bar", parent_id=None, db=db)
    assert exc_info.value.status_code == 400


async def test_create_rejects_characters_as_new_name(db):
    with pytest.raises(HTTPException) as exc_info:
        await character_tags.create_character_tag(name="characters", parent_id=None, db=db)
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        await character_tags.create_character_tag(name="CHARACTERS", parent_id=None, db=db)
    assert exc_info.value.status_code == 400


async def test_create_rejects_characters_as_new_name_even_once_it_already_exists(db):
    """The `characters` node existing (created by an earlier call, or a real
    scan) must not turn the reserved-name rejection into a silent
    resolve-to-existing -- it's checked unconditionally, before any sibling
    lookup, not just when there's nothing to resolve to."""
    await character_tags.create_character_tag(name="new", parent_id=None, db=db)  # creates `characters`
    cursor = await db.execute("SELECT id FROM character_tag WHERE name = 'characters'")
    characters_id = (await cursor.fetchone())["id"]

    with pytest.raises(HTTPException) as exc_info:
        await character_tags.create_character_tag(name="characters", parent_id=0, db=db)
    assert exc_info.value.status_code == 400


async def test_create_does_not_leave_the_characters_node_behind_on_validation_failure(db):
    """parent_id=None resolves/creates the `characters` node as a side
    effect BEFORE the new node's own name is validated -- a rejected name
    must not leave that node committed behind."""
    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE name = 'characters'")
    assert (await cursor.fetchone())["n"] == 0

    with pytest.raises(HTTPException) as exc_info:
        await character_tags.create_character_tag(name="foo<bar", parent_id=None, db=db)
    assert exc_info.value.status_code == 400

    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE name = 'characters'")
    assert (await cursor.fetchone())["n"] == 0


async def test_create_resolves_to_existing_node_under_a_different_parent(db):
    """A name that already exists somewhere else in the tree resolves to
    that existing node -- ignoring the requested parent_id entirely -- so a
    picker request doesn't accidentally create a confusing near-duplicate
    under a different branch."""
    cursor = await db.execute("INSERT INTO character_tag (parent_id, name) VALUES (0, 'game')")
    await db.commit()
    game_id = cursor.lastrowid
    existing = await character_tags.create_character_tag(name="666", parent_id=game_id, db=db)

    cursor = await db.execute("INSERT INTO character_tag (parent_id, name) VALUES (0, 'vt')")
    await db.commit()
    vt_id = cursor.lastrowid

    result = await character_tags.create_character_tag(name="666", parent_id=vt_id, db=db)

    assert result["id"] == existing["id"]
    cursor = await db.execute("SELECT parent_id FROM character_tag WHERE id = ?", (result["id"],))
    assert (await cursor.fetchone())["parent_id"] == game_id  # its real, original parent -- not vt_id
    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE name = '666'")
    assert (await cursor.fetchone())["n"] == 1  # no near-duplicate created under vt


async def test_create_resolves_to_existing_node_when_no_parent_given(db):
    """Same as above, but reached via the parent_id=None default path."""
    cursor = await db.execute("INSERT INTO character_tag (parent_id, name) VALUES (0, 'game')")
    await db.commit()
    game_id = cursor.lastrowid
    existing = await character_tags.create_character_tag(name="666", parent_id=game_id, db=db)

    result = await character_tags.create_character_tag(name="666", parent_id=None, db=db)

    assert result["id"] == existing["id"]
    cursor = await db.execute("SELECT parent_id FROM character_tag WHERE id = ?", (result["id"],))
    assert (await cursor.fetchone())["parent_id"] == game_id


async def test_create_rejects_ambiguous_name_matching_multiple_existing_nodes(db):
    # Seeded directly (not via create_character_tag) -- that's exactly the
    # call this test needs to exercise, and it would now correctly resolve
    # a second "666" request to the first one instead of creating a real
    # duplicate, so two genuinely separate "666" nodes can only come from
    # elsewhere (e.g. two independent scans, or legacy data).
    cursor = await db.execute("INSERT INTO character_tag (parent_id, name) VALUES (0, 'seriesA')")
    await db.commit()
    series_a = cursor.lastrowid
    cursor = await db.execute("INSERT INTO character_tag (parent_id, name) VALUES (0, 'seriesB')")
    await db.commit()
    series_b = cursor.lastrowid
    await db.execute("INSERT INTO character_tag (parent_id, name) VALUES (?, '666')", (series_a,))
    await db.execute("INSERT INTO character_tag (parent_id, name) VALUES (?, '666')", (series_b,))
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await character_tags.create_character_tag(name="666", parent_id=None, db=db)
    assert exc_info.value.status_code == 400

    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE name = '666'")
    assert (await cursor.fetchone())["n"] == 2  # unchanged -- no third node created


async def test_create_resolves_to_existing_normalized_variant(db):
    first = await character_tags.create_character_tag(name="Ooguni", parent_id=None, db=db)

    second = await character_tags.create_character_tag(name="ooguni.", parent_id=None, db=db)

    assert second["id"] == first["id"]
    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE name LIKE 'Ooguni%'")
    assert (await cursor.fetchone())["n"] == 1


async def test_update_rejects_reserved_device_name(db, tmp_path):
    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)

    with pytest.raises(HTTPException) as exc_info:
        await character_tags.update_character_tag(node_id=row["char_id"], name="NUL", parent_id=None, db=db)
    assert exc_info.value.status_code == 400


async def test_update_rejects_name_colliding_with_different_sibling(db, tmp_path):
    """Renaming into a name that only differs from an existing sibling by
    case/trailing dot-space is a real conflict -- there's no merge tooling,
    so this must be rejected, not silently resolved to the other node."""
    a = tmp_path / "characters" / "game" / "char_a" / "1.jpg"
    b = tmp_path / "characters" / "game" / "char_b" / "1.jpg"
    make_image(a)
    make_image(b)
    await run_scan(db, tmp_path, ["characters"])
    row_a = await get_image(db, a)
    row_b = await get_image(db, b)

    with pytest.raises(HTTPException) as exc_info:
        await character_tags.update_character_tag(
            node_id=row_a["char_id"], name="CHAR_B", parent_id=None, db=db
        )
    assert exc_info.value.status_code == 400

    cursor = await db.execute("SELECT name FROM character_tag WHERE id = ?", (row_a["char_id"],))
    assert (await cursor.fetchone())["name"] == "char_a"  # untouched
    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE id = ?", (row_b["char_id"],))
    assert (await cursor.fetchone())["n"] == 1  # row_b unaffected, not merged into


async def test_update_allows_renaming_to_normalized_variant_of_own_name(db, tmp_path):
    """Renaming a node to a case-different variant of ITS OWN current name
    is not a conflict (there's no other node involved) -- the literal typed
    string is stored, same as any other rename."""
    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)

    await character_tags.update_character_tag(node_id=row["char_id"], name="CHAR", parent_id=None, db=db)

    cursor = await db.execute("SELECT name FROM character_tag WHERE id = ?", (row["char_id"],))
    assert (await cursor.fetchone())["name"] == "CHAR"


async def test_update_rejects_renaming_to_trailing_dot_variant_of_own_name(db, tmp_path):
    """Unlike the case-variant above, a trailing-dot/space variant of a
    node's own current name is NOT allowed through as a no-op-ish rename:
    "char." is itself an illegal name (see ADR-0005), and matching against
    the node's own current name only means "this isn't a conflict with a
    DIFFERENT node" -- it doesn't exempt the literal string being stored
    from validation. The self-match and different-sibling-match cases are
    both normalized the same way for CONFLICT DETECTION, but only a
    genuinely legal string ever gets past validate_tag_name."""
    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)

    with pytest.raises(HTTPException) as exc_info:
        await character_tags.update_character_tag(node_id=row["char_id"], name="char.", parent_id=None, db=db)
    assert exc_info.value.status_code == 400

    cursor = await db.execute("SELECT name FROM character_tag WHERE id = ?", (row["char_id"],))
    assert (await cursor.fetchone())["name"] == "char"  # untouched
