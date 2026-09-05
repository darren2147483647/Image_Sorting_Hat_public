import pytest

from tag_tree import (
    get_or_create_tag,
    ancestor_path_names,
    get_or_create_tag_path,
    find_nodes_by_normalized_name,
    find_sibling_case_insensitive,
    validate_tag_name,
)


async def test_root_row_exists_for_both_trees(db):
    for table in ("character_tag", "individual_tag"):
        cursor = await db.execute(f"SELECT parent_id, name FROM {table} WHERE id = 0")
        row = await cursor.fetchone()
        assert row is not None
        assert row["parent_id"] is None


async def test_images_char_and_artist_id_default_to_zero(db):
    await db.execute(
        "INSERT INTO images (file_path, file_name) VALUES ('a.jpg', 'a.jpg')"
    )
    await db.commit()
    cursor = await db.execute("SELECT char_id, artist_id FROM images WHERE file_path = 'a.jpg'")
    row = await cursor.fetchone()
    assert row["char_id"] == 0
    assert row["artist_id"] == 0


async def test_get_or_create_tag_creates_new_node(db):
    tag_id = await get_or_create_tag(db, "character_tag", 0, "game")
    await db.commit()

    cursor = await db.execute("SELECT parent_id, name FROM character_tag WHERE id = ?", (tag_id,))
    row = await cursor.fetchone()
    assert row["parent_id"] == 0
    assert row["name"] == "game"


async def test_get_or_create_tag_dedupes_same_parent_and_name(db):
    first_id = await get_or_create_tag(db, "character_tag", 0, "game")
    second_id = await get_or_create_tag(db, "character_tag", 0, "game")
    await db.commit()

    assert first_id == second_id
    cursor = await db.execute(
        "SELECT COUNT(*) as n FROM character_tag WHERE parent_id = 0 AND name = 'game'"
    )
    row = await cursor.fetchone()
    assert row["n"] == 1


async def test_get_or_create_tag_allows_same_name_different_parent(db):
    vt_id = await get_or_create_tag(db, "character_tag", 0, "vt")
    game_id = await get_or_create_tag(db, "character_tag", 0, "game")
    ba_id = await get_or_create_tag(db, "character_tag", game_id, "ba")

    multiple_under_vt = await get_or_create_tag(db, "character_tag", vt_id, "multiple")
    multiple_under_ba = await get_or_create_tag(db, "character_tag", ba_id, "multiple")
    await db.commit()

    assert multiple_under_vt != multiple_under_ba

    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE name = 'multiple'")
    row = await cursor.fetchone()
    assert row["n"] == 2


async def test_get_or_create_tag_does_not_duplicate_top_level_nodes_across_calls(db):
    """Root-level nodes (parent_id=0) must dedupe correctly, unlike the old
    NULL-parent_id design where SQLite's NULL != NULL semantics let duplicate
    top-level rows accumulate on every scan."""
    first = await get_or_create_tag(db, "character_tag", 0, "game")
    second = await get_or_create_tag(db, "character_tag", 0, "game")
    third = await get_or_create_tag(db, "character_tag", 0, "game")
    await db.commit()

    assert first == second == third
    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE name = 'game'")
    row = await cursor.fetchone()
    assert row["n"] == 1


async def test_individual_tag_is_independent_from_character_tag(db):
    char_id = await get_or_create_tag(db, "character_tag", 0, "multiple")
    indiv_id = await get_or_create_tag(db, "individual_tag", 0, "multiple")
    await db.commit()

    # Same name/parent shape, but different tables -> independent id spaces, no cross-talk.
    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE name = 'multiple'")
    assert (await cursor.fetchone())["n"] == 1
    cursor = await db.execute("SELECT COUNT(*) as n FROM individual_tag WHERE name = 'multiple'")
    assert (await cursor.fetchone())["n"] == 1


async def test_ancestor_path_names_returns_root_to_leaf_excluding_sentinel(db):
    a = await get_or_create_tag(db, "individual_tag", 0, "individuals")
    b = await get_or_create_tag(db, "individual_tag", a, "紅茶社")
    c = await get_or_create_tag(db, "individual_tag", b, "XYZ")
    await db.commit()

    assert await ancestor_path_names(db, "individual_tag", c) == ["individuals", "紅茶社", "XYZ"]


async def test_ancestor_path_names_single_level(db):
    a = await get_or_create_tag(db, "individual_tag", 0, "individuals")
    await db.commit()

    assert await ancestor_path_names(db, "individual_tag", a) == ["individuals"]


async def test_get_or_create_tag_path_creates_full_chain(db):
    leaf_id = await get_or_create_tag_path(db, "individual_tag", ["individuals", "紅茶社", "XYZ"])
    await db.commit()

    assert await ancestor_path_names(db, "individual_tag", leaf_id) == ["individuals", "紅茶社", "XYZ"]


async def test_get_or_create_tag_path_reuses_existing_nodes(db):
    first = await get_or_create_tag_path(db, "individual_tag", ["individuals", "紅茶社", "XYZ"])
    second = await get_or_create_tag_path(db, "individual_tag", ["individuals", "紅茶社", "XYZ"])
    await db.commit()

    assert first == second
    cursor = await db.execute("SELECT COUNT(*) as n FROM individual_tag WHERE name = 'XYZ'")
    assert (await cursor.fetchone())["n"] == 1


async def test_get_or_create_tag_path_empty_path_resolves_to_root(db):
    assert await get_or_create_tag_path(db, "individual_tag", []) == 0


async def test_ancestor_path_names_and_get_or_create_tag_path_are_inverses_with_duplicate_leaf_names(db):
    """Two different parents sharing a leaf name -- get_or_create_tag_path must
    land on the correct one when driven by the full path, not just the leaf name."""
    artist_a = await get_or_create_tag(db, "individual_tag", 0, "artistA")
    artist_b = await get_or_create_tag(db, "individual_tag", 0, "artistB")
    multiple_under_a = await get_or_create_tag(db, "individual_tag", artist_a, "multiple")
    multiple_under_b = await get_or_create_tag(db, "individual_tag", artist_b, "multiple")
    await db.commit()

    path_a = await ancestor_path_names(db, "individual_tag", multiple_under_a)
    resolved = await get_or_create_tag_path(db, "individual_tag", path_a)

    assert resolved == multiple_under_a
    assert resolved != multiple_under_b


async def test_find_sibling_case_insensitive_finds_exact_case_match(db):
    artist_id = await get_or_create_tag(db, "individual_tag", 0, "Ooguni")
    await db.commit()

    found = await find_sibling_case_insensitive(db, "individual_tag", 0, "Ooguni")
    assert found == artist_id


async def test_find_sibling_case_insensitive_finds_different_case_match(db):
    artist_id = await get_or_create_tag(db, "individual_tag", 0, "Ooguni")
    await db.commit()

    assert await find_sibling_case_insensitive(db, "individual_tag", 0, "ooguni") == artist_id
    assert await find_sibling_case_insensitive(db, "individual_tag", 0, "OOGUNI") == artist_id


async def test_find_sibling_case_insensitive_returns_none_when_absent(db):
    await get_or_create_tag(db, "individual_tag", 0, "Ooguni")
    await db.commit()

    assert await find_sibling_case_insensitive(db, "individual_tag", 0, "Mauve") is None


async def test_find_sibling_case_insensitive_scoped_to_parent(db):
    """Same name, different parent -- must not match across siblings under
    different parents."""
    parent_a = await get_or_create_tag(db, "individual_tag", 0, "artistA")
    parent_b = await get_or_create_tag(db, "individual_tag", 0, "artistB")
    child_under_a = await get_or_create_tag(db, "individual_tag", parent_a, "multiple")
    await db.commit()

    assert await find_sibling_case_insensitive(db, "individual_tag", parent_a, "MULTIPLE") == child_under_a
    assert await find_sibling_case_insensitive(db, "individual_tag", parent_b, "MULTIPLE") is None


async def test_find_sibling_case_insensitive_leaves_cjk_names_unaffected(db):
    """No case distinction in CJK -- an unrelated different name must not
    accidentally match."""
    artist_id = await get_or_create_tag(db, "individual_tag", 0, "紅茶社")
    await db.commit()

    assert await find_sibling_case_insensitive(db, "individual_tag", 0, "紅茶社") == artist_id
    assert await find_sibling_case_insensitive(db, "individual_tag", 0, "紅茶") is None


async def test_find_sibling_case_insensitive_matches_trailing_dot_variant(db):
    artist_id = await get_or_create_tag(db, "individual_tag", 0, "Ooguni")
    await db.commit()

    assert await find_sibling_case_insensitive(db, "individual_tag", 0, "Ooguni.") == artist_id


async def test_find_sibling_case_insensitive_matches_trailing_space_variant(db):
    artist_id = await get_or_create_tag(db, "individual_tag", 0, "Ooguni")
    await db.commit()

    assert await find_sibling_case_insensitive(db, "individual_tag", 0, "Ooguni ") == artist_id


async def test_find_sibling_case_insensitive_combines_case_and_trailing_normalization(db):
    artist_id = await get_or_create_tag(db, "individual_tag", 0, "Ooguni")
    await db.commit()

    assert await find_sibling_case_insensitive(db, "individual_tag", 0, "OOGUNI.") == artist_id


async def test_find_sibling_case_insensitive_does_not_match_genuinely_different_name(db):
    """Trailing-dot/space normalization must not become so loose it merges
    unrelated names -- only the trailing characters are stripped."""
    artist_id = await get_or_create_tag(db, "individual_tag", 0, "Ooguni")
    await db.commit()

    assert await find_sibling_case_insensitive(db, "individual_tag", 0, "Oogun") is None
    assert await find_sibling_case_insensitive(db, "individual_tag", 0, ".Ooguni") is None


# --- find_nodes_by_normalized_name --------------------------------------


async def test_find_nodes_by_normalized_name_finds_single_match_anywhere(db):
    game_id = await get_or_create_tag(db, "character_tag", 0, "game")
    char_id = await get_or_create_tag(db, "character_tag", game_id, "666")
    await db.commit()

    assert await find_nodes_by_normalized_name(db, "character_tag", "666") == [char_id]


async def test_find_nodes_by_normalized_name_matches_case_and_trailing_variants(db):
    game_id = await get_or_create_tag(db, "character_tag", 0, "game")
    char_id = await get_or_create_tag(db, "character_tag", game_id, "Ooguni")
    await db.commit()

    assert await find_nodes_by_normalized_name(db, "character_tag", "ooguni.") == [char_id]


async def test_find_nodes_by_normalized_name_returns_all_matches_across_different_parents(db):
    a = await get_or_create_tag(db, "character_tag", 0, "seriesA")
    b = await get_or_create_tag(db, "character_tag", 0, "seriesB")
    char_a = await get_or_create_tag(db, "character_tag", a, "666")
    char_b = await get_or_create_tag(db, "character_tag", b, "666")
    await db.commit()

    matches = await find_nodes_by_normalized_name(db, "character_tag", "666")
    assert set(matches) == {char_a, char_b}


async def test_find_nodes_by_normalized_name_empty_when_absent(db):
    assert await find_nodes_by_normalized_name(db, "character_tag", "nope") == []


async def test_find_nodes_by_normalized_name_excludes_root_sentinel(db):
    assert await find_nodes_by_normalized_name(db, "character_tag", "root") == []


# --- validate_tag_name -------------------------------------------------


@pytest.mark.parametrize("char", list('<>:"/\\|?*'))
def test_validate_tag_name_rejects_each_illegal_character(char):
    assert validate_tag_name(f"foo{char}bar") is not None


def test_validate_tag_name_rejects_control_characters():
    assert validate_tag_name("foo\x01bar") is not None


_RESERVED_NAMES_TO_TEST = (
    ["CON", "con", "Con", "PRN", "AUX", "NUL"]
    + [f"COM{n}" for n in range(1, 10)]
    + [f"com{n}" for n in range(1, 10)]
    + [f"LPT{n}" for n in range(1, 10)]
    + [f"lpt{n}" for n in range(1, 10)]
)


@pytest.mark.parametrize("reserved", _RESERVED_NAMES_TO_TEST)
def test_validate_tag_name_rejects_reserved_names_any_case(reserved):
    assert validate_tag_name(reserved) is not None


def test_validate_tag_name_does_not_flag_reserved_name_as_prefix():
    # "CONTEST" must not be rejected just because it starts with "CON".
    assert validate_tag_name("CONTEST") is None


def test_validate_tag_name_rejects_trailing_dot():
    assert validate_tag_name("foo.") is not None


def test_validate_tag_name_rejects_trailing_space():
    assert validate_tag_name("foo ") is not None


def test_validate_tag_name_rejects_empty_string():
    assert validate_tag_name("") is not None


def test_validate_tag_name_accepts_normal_name():
    assert validate_tag_name("Ooguni") is None


def test_validate_tag_name_accepts_cjk_name():
    assert validate_tag_name("紅茶社") is None


def test_validate_tag_name_accepts_internal_dot_and_space():
    assert validate_tag_name("Mr. Foo Bar") is None


def test_validate_tag_name_does_not_limit_length():
    assert validate_tag_name("a" * 500) is None
