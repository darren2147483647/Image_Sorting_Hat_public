from pathlib import Path

from routes import search
from tests.test_scanner import make_image


async def run_scan(db, root: Path, containers: list[str]):
    import scanner
    scanner.scan_progress.reset()
    await scanner._run_scan_worker(db, str(root), containers)


async def test_franchise_search_bucket_excludes_leaf_characters(db, tmp_path):
    """Regression: the "franchise" bucket must use has_children_predicate(),
    not a "非根節點" (any non-root node) predicate -- CONTEXT.md's "系列" is
    satisfied by every non-root node, so using that here would duplicate
    every referenced leaf into both the character and franchise buckets."""
    img = tmp_path / "characters" / "gameseries" / "leafchar" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])

    result = await search.global_search(q="e", type="all", limit=20, db=db)
    franchise_names = {f["name"] for f in result["franchises"]}
    character_names = {c["name"] for c in result["characters"]}

    assert "leafchar" not in franchise_names  # a leaf, not a container
    assert "gameseries" in franchise_names  # has a child -> real container
    assert not (franchise_names & character_names)  # no overlap between buckets


async def test_search_suggest_franchise_excludes_leaf_characters(db, tmp_path):
    img = tmp_path / "characters" / "gameseries" / "leafchar" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])

    result = await search.search_suggest(q="e", limit=20, db=db)
    franchise_names = {s["name"] for s in result["suggestions"] if s["type"] == "franchise"}
    assert "leafchar" not in franchise_names
    assert "gameseries" in franchise_names
