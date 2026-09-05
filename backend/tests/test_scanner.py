import json
import shutil
from pathlib import Path

from PIL import Image

import artist_backup
import config
import import_root
import scanner
from tag_tree import get_or_create_tag


def make_image(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(path)


async def run_scan(db, root: Path, containers: list[str]):
    scanner.scan_progress.reset()
    await scanner._run_scan_worker(db, str(root), containers)


async def get_tag_chain(db, table: str, tag_id: int) -> list[str]:
    """Walk parent_id up to the root, returning names root-to-leaf (root excluded)."""
    names = []
    current = tag_id
    while current != 0:
        cursor = await db.execute(f"SELECT parent_id, name FROM {table} WHERE id = ?", (current,))
        row = await cursor.fetchone()
        names.insert(0, row["name"])
        current = row["parent_id"]
    return names


async def get_image(db, file_path: str):
    """Look up a row by the absolute path a test file was created at. Storage
    format is either the legacy absolute path or a POSIX-relative path that's
    a suffix of it (see ADR-0004) -- matching by suffix means every existing
    call site keeps working unchanged regardless of which form a given test
    ends up with."""
    target_native = str(file_path)
    target_posix = Path(file_path).as_posix()
    cursor = await db.execute("SELECT * FROM images")
    for row in await cursor.fetchall():
        stored = row["file_path"]
        if stored in (target_native, target_posix) or target_posix.endswith("/" + stored):
            return row
    return None


# --- Ticket 02: characters/ ---------------------------------------------


async def test_standard_nested_depth_builds_full_chain(db, tmp_path):
    img = tmp_path / "characters" / "game" / "ba" / "三一" / "修女會" / "瑪麗" / "a.jpeg"
    make_image(img)

    await run_scan(db, tmp_path, ["characters"])

    row = await get_image(db, img)
    assert row is not None
    assert row["artist_id"] == 0
    chain = await get_tag_chain(db, "character_tag", row["char_id"])
    assert chain == ["characters", "game", "ba", "三一", "修女會", "瑪麗"]


async def test_character_directly_under_category_no_series_layer(db, tmp_path):
    img = tmp_path / "characters" / "popular" / "uno" / "a.jpg"
    make_image(img)

    await run_scan(db, tmp_path, ["characters"])

    row = await get_image(db, img)
    chain = await get_tag_chain(db, "character_tag", row["char_id"])
    assert chain == ["characters", "popular", "uno"]


async def test_loose_files_directly_in_characters_container_are_not_dropped(db, tmp_path):
    img = tmp_path / "characters" / "loose.jpg"
    make_image(img)

    await run_scan(db, tmp_path, ["characters"])

    row = await get_image(db, img)
    assert row is not None
    chain = await get_tag_chain(db, "character_tag", row["char_id"])
    assert chain == ["characters"]


async def test_flat_folder_with_no_subfolders_uses_folder_name_as_leaf(db, tmp_path):
    img = tmp_path / "characters" / "無分類" / "a.jpg"
    make_image(img)

    await run_scan(db, tmp_path, ["characters"])

    row = await get_image(db, img)
    chain = await get_tag_chain(db, "character_tag", row["char_id"])
    assert chain == ["characters", "無分類"]


async def test_same_name_different_parent_resolves_to_distinct_nodes(db, tmp_path):
    vt_multiple = tmp_path / "characters" / "vt" / "multiple" / "a.jpg"
    game_multiple = tmp_path / "characters" / "game" / "ba" / "multiple" / "b.jpg"
    make_image(vt_multiple)
    make_image(game_multiple)

    await run_scan(db, tmp_path, ["characters"])

    row_a = await get_image(db, vt_multiple)
    row_b = await get_image(db, game_multiple)
    assert row_a["char_id"] != row_b["char_id"]

    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE name = 'multiple'")
    assert (await cursor.fetchone())["n"] == 2


# --- Ticket 03: individuals/ ----------------------------------------------


async def test_artist_with_only_files_no_subfolder(db, tmp_path):
    img = tmp_path / "individuals" / "someartist" / "a.jpg"
    make_image(img)

    await run_scan(db, tmp_path, ["individuals"])

    row = await get_image(db, img)
    assert row["char_id"] == 0
    chain = await get_tag_chain(db, "individual_tag", row["artist_id"])
    assert chain == ["individuals", "someartist"]


async def test_artist_with_one_nested_character_subfolder(db, tmp_path):
    img = tmp_path / "individuals" / "someartist" / "somechar" / "a.jpg"
    make_image(img)

    await run_scan(db, tmp_path, ["individuals"])

    row = await get_image(db, img)
    chain = await get_tag_chain(db, "individual_tag", row["artist_id"])
    assert chain == ["individuals", "someartist", "somechar"]


async def test_artist_nested_more_than_two_levels_is_not_dropped(db, tmp_path):
    """Regression test: the old _analyze_artist_folder only understood
    artist/character (2 levels) and silently dropped anything deeper."""
    img = tmp_path / "individuals" / "someartist" / "seriesA" / "seriesB" / "char" / "a.jpg"
    make_image(img)

    await run_scan(db, tmp_path, ["individuals"])

    row = await get_image(db, img)
    assert row is not None
    chain = await get_tag_chain(db, "individual_tag", row["artist_id"])
    assert chain == ["individuals", "someartist", "seriesA", "seriesB", "char"]


# --- Ticket 04: rescan is insert-only --------------------------------------


async def test_rescanning_does_not_duplicate_images(db, tmp_path):
    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)

    await run_scan(db, tmp_path, ["characters"])
    await run_scan(db, tmp_path, ["characters"])

    cursor = await db.execute("SELECT COUNT(*) as n FROM images")
    assert (await cursor.fetchone())["n"] == 1


async def test_rescanning_never_overwrites_existing_row(db, tmp_path):
    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)

    await run_scan(db, tmp_path, ["characters"])

    # Simulate a manual correction.
    existing_id = (await get_image(db, img))["id"]
    await db.execute("UPDATE images SET char_id = 0 WHERE id = ?", (existing_id,))
    await db.commit()

    await run_scan(db, tmp_path, ["characters"])

    row = await get_image(db, img)
    assert row["char_id"] == 0  # untouched by the rescan, still the manual value


# --- artist_tags_backup.json reapplication on import -----------------------


async def test_backup_reapplies_artist_after_full_rebuild_with_different_ids(db, tmp_path, monkeypatch):
    """The critical regression test: individual_tag ids are autoincrement and
    NOT stable across a full DB rebuild, so the backup must resolve by name
    path, not by caching the old numeric id."""
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img = tmp_path / "individuals" / "someartist" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["individuals"])

    row = await get_image(db, img)
    original_artist_id = row["artist_id"]
    file_hash = row["file_hash"]
    original_chain = await get_tag_chain(db, "individual_tag", original_artist_id)
    artist_backup.set_entry(backup_path, file_hash, original_chain)

    # Simulate "DB wiped and rebuilt": clear images + individual_tag (root
    # kept), then push the autoincrement sequence forward so a freshly
    # (re)created node for the same name is guaranteed to land on a
    # different id than before -- proving reapplication isn't accidentally
    # "working" just because ids happened to come back the same.
    await db.execute("DELETE FROM images")
    await db.execute("DELETE FROM individual_tag WHERE id != 0")
    await db.commit()
    for i in range(5):
        await get_or_create_tag(db, "individual_tag", 0, f"__offset_{i}__")
    await db.commit()

    # Move the file to a different folder (same bytes -> same file_hash) so
    # folder-derivation ALONE would now produce a different, wrong chain --
    # the only way the assertion below can pass is if the backup is what
    # actually restored the original classification.
    moved = tmp_path / "individuals" / "unsorted" / "a.jpg"
    moved.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(img), str(moved))

    await run_scan(db, tmp_path, ["individuals"])

    new_row = await get_image(db, moved)
    assert new_row["artist_id"] != original_artist_id
    new_chain = await get_tag_chain(db, "individual_tag", new_row["artist_id"])
    assert new_chain == original_chain  # not ["individuals", "unsorted"]


async def test_backup_resolves_correct_node_among_duplicate_leaf_names(db, tmp_path, monkeypatch):
    """Two different parents can share a leaf name (already a real occurrence
    in this project's data) -- reapplication must land on the one the full
    path actually points to, not any node with a matching bare name."""
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img_a = tmp_path / "individuals" / "artistA" / "multiple" / "a.jpg"
    img_b = tmp_path / "individuals" / "artistB" / "multiple" / "b.jpg"
    make_image(img_a)
    make_image(img_b)
    await run_scan(db, tmp_path, ["individuals"])

    row_a = await get_image(db, img_a)
    chain_a = await get_tag_chain(db, "individual_tag", row_a["artist_id"])
    assert chain_a == ["individuals", "artistA", "multiple"]
    artist_backup.set_entry(backup_path, row_a["file_hash"], chain_a)

    await db.execute("DELETE FROM images")
    await db.execute("DELETE FROM individual_tag WHERE id != 0")
    await db.commit()

    # Move img_a out of its original folder (same bytes -> same file_hash) so
    # folder-derivation alone would no longer reproduce "artistA/multiple" --
    # img_b's own real folder still independently creates a *different*
    # "multiple" node under artistB, so a bare-name (not full-path) lookup
    # would risk resolving img_a onto the wrong one.
    moved_a = tmp_path / "individuals" / "unsorted" / "a.jpg"
    moved_a.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(img_a), str(moved_a))

    await run_scan(db, tmp_path, ["individuals"])

    new_row_a = await get_image(db, moved_a)
    assert await get_tag_chain(db, "individual_tag", new_row_a["artist_id"]) == chain_a

    cursor = await db.execute("SELECT COUNT(*) as n FROM individual_tag WHERE name = 'multiple'")
    assert (await cursor.fetchone())["n"] == 2  # not accidentally merged into one node



# --- Ticket 01 (scan-classification-policy): 其他位置 ----------------------


def test_walk_other_locations_finds_loose_file_at_root(tmp_path):
    make_image(tmp_path / "loose.jpg")

    assert scanner.walk_other_locations(tmp_path) == [str(tmp_path / "loose.jpg")]


def test_walk_other_locations_finds_file_at_any_depth(tmp_path):
    make_image(tmp_path / "wallpapers" / "2024" / "spring" / "a.jpg")

    assert scanner.walk_other_locations(tmp_path) == [
        str(tmp_path / "wallpapers" / "2024" / "spring" / "a.jpg")
    ]


def test_walk_other_locations_excludes_characters_container(tmp_path):
    make_image(tmp_path / "characters" / "game" / "char" / "a.jpg")
    make_image(tmp_path / "loose.jpg")

    assert scanner.walk_other_locations(tmp_path) == [str(tmp_path / "loose.jpg")]


def test_walk_other_locations_excludes_individuals_container(tmp_path):
    make_image(tmp_path / "individuals" / "someartist" / "a.jpg")
    make_image(tmp_path / "loose.jpg")

    assert scanner.walk_other_locations(tmp_path) == [str(tmp_path / "loose.jpg")]


def test_walk_other_locations_only_excludes_top_level_container_names(tmp_path):
    """A nested folder that happens to share a container's name isn't one of
    the two fixed containers -- only root/characters and root/individuals
    (exact top-level paths) are excluded."""
    make_image(tmp_path / "wallpapers" / "characters" / "a.jpg")

    assert scanner.walk_other_locations(tmp_path) == [
        str(tmp_path / "wallpapers" / "characters" / "a.jpg")
    ]


def test_walk_other_locations_root_does_not_exist_returns_empty(tmp_path):
    assert scanner.walk_other_locations(tmp_path / "does-not-exist") == []


def test_walk_other_locations_ignores_unsupported_file_types(tmp_path):
    other = tmp_path / "readme.txt"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("not an image")

    assert scanner.walk_other_locations(tmp_path) == []


async def test_scan_imports_other_location_files_with_source_folder_other(db, tmp_path):
    make_image(tmp_path / "wallpapers" / "a.jpg")

    await run_scan(db, tmp_path, [])

    row = await get_image(db, tmp_path / "wallpapers" / "a.jpg")
    assert row is not None
    assert row["source_folder"] == "other"
    assert row["char_id"] == 0
    assert row["artist_id"] == 0


async def test_scan_other_locations_creates_no_tag_nodes(db, tmp_path):
    make_image(tmp_path / "wallpapers" / "2024" / "a.jpg")

    await run_scan(db, tmp_path, [])

    cursor = await db.execute("SELECT COUNT(*) as n FROM character_tag WHERE id != 0")
    assert (await cursor.fetchone())["n"] == 0
    cursor = await db.execute("SELECT COUNT(*) as n FROM individual_tag WHERE id != 0")
    assert (await cursor.fetchone())["n"] == 0


async def test_scan_include_other_false_skips_other_locations(db, tmp_path):
    make_image(tmp_path / "wallpapers" / "a.jpg")

    scanner.scan_progress.reset()
    await scanner._run_scan_worker(db, str(tmp_path), [], include_other=False)

    row = await get_image(db, tmp_path / "wallpapers" / "a.jpg")
    assert row is None


async def test_scan_other_locations_respects_existing_artist_backup(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img = tmp_path / "wallpapers" / "a.jpg"
    make_image(img)
    file_hash = scanner.compute_file_hash(str(img))
    artist_id = await get_or_create_tag(db, "individual_tag", 0, "someartist")
    await db.commit()
    artist_backup.set_entry(backup_path, file_hash, ["someartist"])

    await run_scan(db, tmp_path, [])

    row = await get_image(db, img)
    assert row["artist_id"] == artist_id



# --- Ticket 02 (scan-classification-policy): 鬆散影像提醒 --------------------


def test_count_loose_individuals_files_counts_direct_files(tmp_path):
    individuals_root = tmp_path / "individuals"
    make_image(individuals_root / "loose1.jpg")
    make_image(individuals_root / "loose2.jpg")

    assert scanner.count_loose_individuals_files(individuals_root) == 2


def test_count_loose_individuals_files_does_not_count_files_in_subfolders(tmp_path):
    individuals_root = tmp_path / "individuals"
    make_image(individuals_root / "loose.jpg")
    make_image(individuals_root / "someartist" / "a.jpg")

    assert scanner.count_loose_individuals_files(individuals_root) == 1


def test_count_loose_individuals_files_returns_zero_when_root_missing(tmp_path):
    assert scanner.count_loose_individuals_files(tmp_path / "individuals") == 0


def test_count_loose_individuals_files_returns_zero_when_only_artist_subfolders(tmp_path):
    individuals_root = tmp_path / "individuals"
    make_image(individuals_root / "someartist" / "a.jpg")
    make_image(individuals_root / "anotherartist" / "b.jpg")

    assert scanner.count_loose_individuals_files(individuals_root) == 0


def test_count_loose_individuals_files_ignores_non_image_files(tmp_path):
    individuals_root = tmp_path / "individuals"
    individuals_root.mkdir(parents=True)
    (individuals_root / "readme.txt").write_text("not an image")

    assert scanner.count_loose_individuals_files(individuals_root) == 0



# --- Ticket 03 (scan-classification-policy): 分類策略 -----------------------


async def test_char_policy_fixed_applies_uniformly_across_all_sources(db, tmp_path):
    fixed_char_id = await get_or_create_tag(db, "character_tag", 0, "fixed-target")
    await db.commit()

    char_img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    artist_img = tmp_path / "individuals" / "someartist" / "b.jpg"
    other_img = tmp_path / "wallpapers" / "c.jpg"
    make_image(char_img)
    make_image(artist_img)
    make_image(other_img)

    scanner.scan_progress.reset()
    await scanner._run_scan_worker(
        db, str(tmp_path), ["characters", "individuals"], include_other=True,
        char_policy=scanner.ClassificationPolicy("fixed", fixed_char_id),
    )

    for img in (char_img, artist_img, other_img):
        row = await get_image(db, img)
        assert row["char_id"] == fixed_char_id


async def test_char_policy_none_gives_zero_char_id_everywhere(db, tmp_path):
    char_img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(char_img)

    scanner.scan_progress.reset()
    await scanner._run_scan_worker(
        db, str(tmp_path), ["characters"], include_other=False,
        char_policy=scanner.ClassificationPolicy("none"),
    )

    row = await get_image(db, char_img)
    assert row["char_id"] == 0


async def test_artist_policy_fixed_applies_uniformly_across_all_sources(db, tmp_path):
    fixed_artist_id = await get_or_create_tag(db, "individual_tag", 0, "fixed-target")
    await db.commit()

    char_img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    artist_img = tmp_path / "individuals" / "someartist" / "b.jpg"
    other_img = tmp_path / "wallpapers" / "c.jpg"
    make_image(char_img)
    make_image(artist_img)
    make_image(other_img)

    scanner.scan_progress.reset()
    await scanner._run_scan_worker(
        db, str(tmp_path), ["characters", "individuals"], include_other=True,
        artist_policy=scanner.ClassificationPolicy("fixed", fixed_artist_id),
    )

    for img in (char_img, artist_img, other_img):
        row = await get_image(db, img)
        assert row["artist_id"] == fixed_artist_id


async def test_artist_policy_none_gives_zero_artist_id_everywhere(db, tmp_path):
    artist_img = tmp_path / "individuals" / "someartist" / "a.jpg"
    make_image(artist_img)

    scanner.scan_progress.reset()
    await scanner._run_scan_worker(
        db, str(tmp_path), ["individuals"], include_other=False,
        artist_policy=scanner.ClassificationPolicy("none"),
    )

    row = await get_image(db, artist_img)
    assert row["artist_id"] == 0


async def test_char_policy_fixed_creates_no_character_tag_nodes(db, tmp_path):
    fixed_char_id = await get_or_create_tag(db, "character_tag", 0, "fixed-target")
    await db.commit()
    make_image(tmp_path / "characters" / "game" / "char" / "a.jpg")

    scanner.scan_progress.reset()
    await scanner._run_scan_worker(
        db, str(tmp_path), ["characters"], include_other=False,
        char_policy=scanner.ClassificationPolicy("fixed", fixed_char_id),
    )

    cursor = await db.execute(
        "SELECT COUNT(*) as n FROM character_tag WHERE id != 0 AND id != ?",
        (fixed_char_id,),
    )
    assert (await cursor.fetchone())["n"] == 0


async def test_artist_policy_none_creates_no_individual_tag_nodes(db, tmp_path):
    make_image(tmp_path / "individuals" / "someartist" / "a.jpg")

    scanner.scan_progress.reset()
    await scanner._run_scan_worker(
        db, str(tmp_path), ["individuals"], include_other=False,
        artist_policy=scanner.ClassificationPolicy("none"),
    )

    cursor = await db.execute("SELECT COUNT(*) as n FROM individual_tag WHERE id != 0")
    assert (await cursor.fetchone())["n"] == 0


async def test_backup_overrides_artist_policy_none(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img = tmp_path / "individuals" / "someartist" / "a.jpg"
    make_image(img)
    file_hash = scanner.compute_file_hash(str(img))
    artist_id = await get_or_create_tag(db, "individual_tag", 0, "realartist")
    await db.commit()
    artist_backup.set_entry(backup_path, file_hash, ["realartist"])

    scanner.scan_progress.reset()
    await scanner._run_scan_worker(
        db, str(tmp_path), ["individuals"], include_other=False,
        artist_policy=scanner.ClassificationPolicy("none"),
    )

    row = await get_image(db, img)
    assert row["artist_id"] == artist_id


async def test_backup_overrides_artist_policy_fixed(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img = tmp_path / "individuals" / "someartist" / "a.jpg"
    make_image(img)
    file_hash = scanner.compute_file_hash(str(img))
    real_artist_id = await get_or_create_tag(db, "individual_tag", 0, "realartist")
    fixed_artist_id = await get_or_create_tag(db, "individual_tag", 0, "fixed-target")
    await db.commit()
    artist_backup.set_entry(backup_path, file_hash, ["realartist"])

    scanner.scan_progress.reset()
    await scanner._run_scan_worker(
        db, str(tmp_path), ["individuals"], include_other=False,
        artist_policy=scanner.ClassificationPolicy("fixed", fixed_artist_id),
    )

    row = await get_image(db, img)
    assert row["artist_id"] == real_artist_id


async def test_char_and_artist_policies_are_independent(db, tmp_path):
    fixed_char_id = await get_or_create_tag(db, "character_tag", 0, "fixed-target")
    await db.commit()

    char_img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    artist_img = tmp_path / "individuals" / "someartist" / "b.jpg"
    make_image(char_img)
    make_image(artist_img)

    scanner.scan_progress.reset()
    await scanner._run_scan_worker(
        db, str(tmp_path), ["characters", "individuals"], include_other=False,
        char_policy=scanner.ClassificationPolicy("fixed", fixed_char_id),
        artist_policy=scanner.ClassificationPolicy("folder"),
    )

    char_row = await get_image(db, char_img)
    artist_row = await get_image(db, artist_img)
    assert char_row["char_id"] == fixed_char_id
    chain = await get_tag_chain(db, "individual_tag", artist_row["artist_id"])
    assert chain == ["individuals", "someartist"]


async def test_scan_history_records_policy(db, tmp_path):
    fixed_char_id = await get_or_create_tag(db, "character_tag", 0, "fixed-target")
    await db.commit()
    make_image(tmp_path / "characters" / "game" / "char" / "a.jpg")

    scanner.scan_progress.reset()
    await scanner._run_scan_worker(
        db, str(tmp_path), ["characters"], include_other=False,
        char_policy=scanner.ClassificationPolicy("fixed", fixed_char_id),
        artist_policy=scanner.ClassificationPolicy("none"),
    )

    cursor = await db.execute(
        "SELECT char_policy, char_fixed_id, artist_policy, artist_fixed_id FROM scan_history ORDER BY id DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    assert row["char_policy"] == "fixed"
    assert row["char_fixed_id"] == fixed_char_id
    assert row["artist_policy"] == "none"
    assert row["artist_fixed_id"] is None



# --- Ticket 04 (scan-classification-policy): 備份寫回與衝突偵測 -------------


async def test_import_writes_new_artist_backup_entry_when_none_existed(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img = tmp_path / "individuals" / "someartist" / "a.jpg"
    make_image(img)

    await run_scan(db, tmp_path, ["individuals"])

    data = artist_backup.load_backup(backup_path)
    file_hash = scanner.compute_file_hash(str(img))
    assert data[file_hash] == ["individuals", "someartist"]


async def test_import_detects_within_scan_collision_between_duplicate_hash_files(db, tmp_path, monkeypatch):
    """Two different files, byte-identical content (same hash), but folder-
    derived artist classification disagrees -- the second one processed must
    detect the collision against the first one's just-written entry, not
    just against whatever existed before this scan."""
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img_a = tmp_path / "individuals" / "artistA" / "a.jpg"
    img_b = tmp_path / "individuals" / "artistB" / "b.jpg"
    make_image(img_a)
    make_image(img_b)
    assert scanner.compute_file_hash(str(img_a)) == scanner.compute_file_hash(str(img_b))

    await run_scan(db, tmp_path, ["individuals"])

    data = artist_backup.load_backup(backup_path)
    file_hash = scanner.compute_file_hash(str(img_a))
    # Exactly one of the two folder-derived paths won -- whichever was
    # processed first -- and the backup holds only that one value.
    assert data[file_hash] in (["individuals", "artistA"], ["individuals", "artistB"])

    row_a = await get_image(db, img_a)
    row_b = await get_image(db, img_b)
    winning_path = data[file_hash]
    winning_chain = (
        await get_tag_chain(db, "individual_tag", row_a["artist_id"])
        if winning_path == ["individuals", "artistA"]
        else await get_tag_chain(db, "individual_tag", row_b["artist_id"])
    )
    # Both rows resolved to the SAME winning classification, not each to its
    # own folder-derived value.
    assert await get_tag_chain(db, "individual_tag", row_a["artist_id"]) == winning_path
    assert await get_tag_chain(db, "individual_tag", row_b["artist_id"]) == winning_path
    assert winning_chain == winning_path


async def test_import_logs_conflict_for_disagreeing_duplicate_hash_files(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    log_path = tmp_path / "conflicts.log"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)
    monkeypatch.setattr(config, "SCAN_CONFLICTS_LOG_PATH", log_path)

    img_a = tmp_path / "individuals" / "artistA" / "a.jpg"
    img_b = tmp_path / "individuals" / "artistB" / "b.jpg"
    make_image(img_a)
    make_image(img_b)

    await run_scan(db, tmp_path, ["individuals"])

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["file_hash"] == scanner.compute_file_hash(str(img_a))
    assert {tuple(entry["existing"]), tuple(entry["discarded"])} == {
        ("individuals", "artistA"),
        ("individuals", "artistB"),
    }


async def test_import_no_conflict_logged_when_pre_existing_backup_matches(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    log_path = tmp_path / "conflicts.log"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)
    monkeypatch.setattr(config, "SCAN_CONFLICTS_LOG_PATH", log_path)

    img = tmp_path / "individuals" / "someartist" / "a.jpg"
    make_image(img)
    file_hash = scanner.compute_file_hash(str(img))
    artist_backup.set_entry(backup_path, file_hash, ["individuals", "someartist"])

    await run_scan(db, tmp_path, ["individuals"])

    assert not log_path.exists()


async def test_import_conflict_with_pre_existing_backup_is_logged_and_backup_wins(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    log_path = tmp_path / "conflicts.log"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)
    monkeypatch.setattr(config, "SCAN_CONFLICTS_LOG_PATH", log_path)

    img = tmp_path / "individuals" / "artistA" / "a.jpg"
    make_image(img)
    file_hash = scanner.compute_file_hash(str(img))
    artist_backup.set_entry(backup_path, file_hash, ["individuals", "realartist"])

    await run_scan(db, tmp_path, ["individuals"])

    row = await get_image(db, img)
    chain = await get_tag_chain(db, "individual_tag", row["artist_id"])
    assert chain == ["individuals", "realartist"]

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["existing"] == ["individuals", "realartist"]
    assert entry["discarded"] == ["individuals", "artistA"]

    data = artist_backup.load_backup(backup_path)
    assert data[file_hash] == ["individuals", "realartist"]  # untouched


async def test_scan_progress_conflicts_field_populated(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img_a = tmp_path / "individuals" / "artistA" / "a.jpg"
    img_b = tmp_path / "individuals" / "artistB" / "b.jpg"
    make_image(img_a)
    make_image(img_b)

    await run_scan(db, tmp_path, ["individuals"])

    assert len(scanner.scan_progress.conflicts) == 1
    assert scanner.scan_progress.conflicts == scanner.scan_progress.to_dict()["conflicts"]


async def test_backup_applies_regardless_of_container(db, tmp_path, monkeypatch):
    """artist_id is decoupled from folder position -- a backup entry must
    apply to a newly-scanned file under characters/ just as much as one
    under individuals/."""
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    artist_img = tmp_path / "individuals" / "someartist" / "a.jpg"
    make_image(artist_img)
    await run_scan(db, tmp_path, ["individuals"])
    artist_row = await get_image(db, artist_img)
    artist_chain = await get_tag_chain(db, "individual_tag", artist_row["artist_id"])

    char_img = tmp_path / "characters" / "game" / "char" / "b.jpg"
    make_image(char_img)
    file_hash = scanner.compute_file_hash(str(char_img))
    artist_backup.set_entry(backup_path, file_hash, artist_chain)

    await run_scan(db, tmp_path, ["characters"])

    row = await get_image(db, char_img)
    assert row["char_id"] != 0  # normal folder-derived character classification
    chain = await get_tag_chain(db, "individual_tag", row["artist_id"])
    assert chain == artist_chain


# --- Ticket 02 (switchable-import-root): 相對路徑儲存 -----------------------


async def test_scan_stores_relative_posix_path_by_default(db, tmp_path):
    """No import_root_dir passed -- falls back to root_path itself, so the
    stored path is relative to the same folder that was scanned."""
    img = tmp_path / "characters" / "game" / "a.jpg"
    make_image(img)

    await run_scan(db, tmp_path, ["characters"])

    row = await get_image(db, img)
    assert row["file_path"] == "characters/game/a.jpg"


async def test_scan_of_subfolder_stores_path_relative_to_import_root_not_scan_root(db, tmp_path):
    """When the scan root is itself a subfolder of the (separately supplied)
    import root, the stored path must stay relative to the import root, not
    to the narrower folder that was actually scanned this run."""
    import_root_dir = tmp_path / "library"
    scan_root = import_root_dir / "batch1"
    img = scan_root / "characters" / "a.jpg"
    make_image(img)

    scanner.scan_progress.reset()
    await scanner._run_scan_worker(
        db, str(scan_root), ["characters"], import_root_dir=str(import_root_dir)
    )

    row = await get_image(db, img)
    assert row["file_path"] == "batch1/characters/a.jpg"


async def test_rescan_does_not_duplicate_legacy_absolute_path_row(db, tmp_path):
    """Transitional safety net: a row imported before the migration script
    ran (ticket 04) still has an absolute file_path. Rescanning the same
    physical file must not create a second row for it just because the
    freshly-computed value is now relative."""
    img = tmp_path / "characters" / "a.jpg"
    make_image(img)
    await db.execute(
        "INSERT INTO images (file_path, file_name) VALUES (?, ?)", (str(img), "a.jpg")
    )
    await db.commit()

    await run_scan(db, tmp_path, ["characters"])

    cursor = await db.execute("SELECT COUNT(*) as n FROM images")
    assert (await cursor.fetchone())["n"] == 1
