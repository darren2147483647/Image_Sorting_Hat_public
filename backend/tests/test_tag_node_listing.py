from pathlib import Path

from tag_tree import get_tag_node, list_tag_nodes
from tests.test_scanner import make_image, run_scan


async def seed_overlap_tree(db, tmp_path: Path):
    """`game` ends up with a child ('ba') AND a direct image, so it should
    satisfy both has_children and is_referenced simultaneously."""
    direct = tmp_path / "characters" / "game" / "loose.jpg"
    nested = tmp_path / "characters" / "game" / "ba" / "char" / "a.jpg"
    make_image(direct)
    make_image(nested)
    await run_scan(db, tmp_path, ["characters"])
    return direct, nested


async def test_list_tag_nodes_excludes_root(db, tmp_path):
    await seed_overlap_tree(db, tmp_path)

    result = await list_tag_nodes(db, "character_tag", "char_id", page=1, per_page=50)
    names = {n["name"] for n in result["nodes"]}
    assert "root" not in names


async def test_node_can_have_children_and_be_referenced_simultaneously(db, tmp_path):
    await seed_overlap_tree(db, tmp_path)

    result = await list_tag_nodes(db, "character_tag", "char_id", page=1, per_page=50)
    game = next(n for n in result["nodes"] if n["name"] == "game")

    assert game["has_children"] is True
    assert game["is_referenced"] is True


async def test_direct_vs_total_image_count(db, tmp_path):
    await seed_overlap_tree(db, tmp_path)

    result = await list_tag_nodes(db, "character_tag", "char_id", page=1, per_page=50)
    game = next(n for n in result["nodes"] if n["name"] == "game")

    assert game["direct_image_count"] == 1  # just loose.jpg
    assert game["total_image_count"] == 2  # loose.jpg + nested a.jpg under ba/char


async def test_total_image_count_includes_unreferenced_intermediate_node(db, tmp_path):
    """A node with descendants but no image of its own must still report the
    full subtree count, not be treated as empty."""
    nested = tmp_path / "characters" / "game" / "ba" / "char" / "a.jpg"
    make_image(nested)
    await run_scan(db, tmp_path, ["characters"])

    result = await list_tag_nodes(db, "character_tag", "char_id", page=1, per_page=50)
    ba = next(n for n in result["nodes"] if n["name"] == "ba")

    assert ba["is_referenced"] is False
    assert ba["has_children"] is True
    assert ba["direct_image_count"] == 0
    assert ba["total_image_count"] == 1


async def test_list_tag_nodes_includes_parent_name(db, tmp_path):
    await seed_overlap_tree(db, tmp_path)

    result = await list_tag_nodes(db, "character_tag", "char_id", page=1, per_page=50)
    ba = next(n for n in result["nodes"] if n["name"] == "ba")
    assert ba["parent_name"] == "game"


async def test_get_tag_node_includes_parent_name(db, tmp_path):
    await seed_overlap_tree(db, tmp_path)

    cursor = await db.execute("SELECT id FROM character_tag WHERE name = 'ba'")
    ba_id = (await cursor.fetchone())["id"]

    node = await get_tag_node(db, "character_tag", "char_id", ba_id)
    assert node["parent_name"] == "game"


async def test_get_tag_node_breadcrumb_and_children(db, tmp_path):
    await seed_overlap_tree(db, tmp_path)

    cursor = await db.execute("SELECT id FROM character_tag WHERE name = 'ba'")
    ba_id = (await cursor.fetchone())["id"]

    node = await get_tag_node(db, "character_tag", "char_id", ba_id)
    assert node["breadcrumb"] == ["characters", "game"]

    child_names = {c["name"] for c in node["children"]}
    assert child_names == {"char"}


async def test_get_tag_node_returns_none_for_root_or_missing(db, tmp_path):
    assert await get_tag_node(db, "character_tag", "char_id", 0) is None
    assert await get_tag_node(db, "character_tag", "char_id", 999999) is None


async def test_search_filters_by_name(db, tmp_path):
    await seed_overlap_tree(db, tmp_path)

    result = await list_tag_nodes(
        db, "character_tag", "char_id", page=1, per_page=50, search="ba"
    )
    names = {n["name"] for n in result["nodes"]}
    assert names == {"ba"}


async def test_sort_by_name_asc_and_desc(db, tmp_path):
    a = tmp_path / "characters" / "aaa" / "char" / "1.jpg"
    z = tmp_path / "characters" / "zzz" / "char" / "1.jpg"
    make_image(a)
    make_image(z)
    await run_scan(db, tmp_path, ["characters"])

    asc = await list_tag_nodes(
        db, "character_tag", "char_id", page=1, per_page=50, sort_by="name", sort_order="asc"
    )
    names_asc = [n["name"] for n in asc["nodes"]]
    assert names_asc.index("aaa") < names_asc.index("zzz")

    desc = await list_tag_nodes(
        db, "character_tag", "char_id", page=1, per_page=50, sort_by="name", sort_order="desc"
    )
    names_desc = [n["name"] for n in desc["nodes"]]
    assert names_desc.index("zzz") < names_desc.index("aaa")


async def test_sort_by_image_count_uses_total_not_direct(db, tmp_path):
    """A container with many descendant images but nothing directly on it
    must still sort above a leaf with fewer total images -- sorting by
    direct_image_count would put it last instead."""
    big_series = tmp_path / "characters" / "bigseries" / "c1" / "1.jpg"
    big_series2 = tmp_path / "characters" / "bigseries" / "c2" / "1.jpg"
    small_leaf = tmp_path / "characters" / "smallleaf" / "1.jpg"
    make_image(big_series)
    make_image(big_series2)
    make_image(small_leaf)
    await run_scan(db, tmp_path, ["characters"])

    result = await list_tag_nodes(
        db, "character_tag", "char_id", page=1, per_page=50,
        sort_by="image_count", sort_order="desc",
    )
    names = [n["name"] for n in result["nodes"]]
    assert names.index("bigseries") < names.index("smallleaf")


async def test_sort_with_ties_paginates_without_duplicates_or_gaps(db, tmp_path):
    """Regression: sorting by image_count has many nodes tied at 0 (unlike
    name, where UNIQUE(parent_id, name) makes ties rare) -- without a stable
    secondary key, paging through tied rows can duplicate or skip a node."""
    for i in range(5):
        make_image(tmp_path / "characters" / f"leaf{i}" / "1.jpg")
    await run_scan(db, tmp_path, ["characters"])

    # 6 total non-root nodes: the 'characters' container plus 5 leaves.
    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE id != 0")
    total_nodes = (await cursor.fetchone())["n"]
    assert total_nodes == 6

    page1 = await list_tag_nodes(
        db, "character_tag", "char_id", page=1, per_page=3,
        sort_by="image_count", sort_order="desc",
    )
    page2 = await list_tag_nodes(
        db, "character_tag", "char_id", page=2, per_page=3,
        sort_by="image_count", sort_order="desc",
    )
    ids_page1 = [n["id"] for n in page1["nodes"]]
    ids_page2 = [n["id"] for n in page2["nodes"]]
    assert len(set(ids_page1) & set(ids_page2)) == 0  # no duplicates across pages
    assert len(set(ids_page1) | set(ids_page2)) == total_nodes  # and nothing skipped


async def test_has_children_filter_narrows_to_series_only(db, tmp_path):
    await seed_overlap_tree(db, tmp_path)  # game has a child ('ba') AND a direct image

    result = await list_tag_nodes(
        db, "character_tag", "char_id", page=1, per_page=50, has_children=True
    )
    names = {n["name"] for n in result["nodes"]}
    assert "game" in names  # has a child -> included
    # a pure leaf with no children (e.g. a character with no subfolders) must be excluded
    cursor = await db.execute(
        "SELECT name FROM character_tag WHERE id NOT IN (SELECT DISTINCT parent_id FROM character_tag) AND id != 0"
    )
    leaf_names = {r["name"] for r in await cursor.fetchall()}
    assert not (leaf_names & names)


async def test_is_referenced_filter_narrows_to_characters_only(db, tmp_path):
    await seed_overlap_tree(db, tmp_path)

    result = await list_tag_nodes(
        db, "character_tag", "char_id", page=1, per_page=50, is_referenced=True
    )
    names = {n["name"] for n in result["nodes"]}
    assert "game" in names  # referenced by loose.jpg
    assert "ba" not in names  # not referenced by any image directly


async def test_parent_id_filters_direct_children_only(db, tmp_path):
    await seed_overlap_tree(db, tmp_path)

    cursor = await db.execute("SELECT id FROM character_tag WHERE name = 'game'")
    game_id = (await cursor.fetchone())["id"]

    result = await list_tag_nodes(
        db, "character_tag", "char_id", page=1, per_page=50, parent_id=game_id
    )
    names = {n["name"] for n in result["nodes"]}
    assert names == {"ba"}  # direct child only, not the grandchild 'char'
