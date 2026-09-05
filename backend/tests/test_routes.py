"""
Smoke tests for the read/write API routes against the new tag-tree schema.
Route handlers are called directly (no HTTP layer) against the real `db`
fixture, since these are plain async functions once FastAPI's Depends/Query
wrapping is bypassed by passing every argument explicitly.
"""
from pathlib import Path

import pytest
from fastapi import HTTPException

import artist_backup
import config
import import_root
import scanner
from routes import images as images_routes
from tests.test_scanner import make_image, get_image


async def insert_image_row(db, file_path: str, file_name: str = "a.jpg") -> int:
    cursor = await db.execute(
        "INSERT INTO images (file_path, file_name) VALUES (?, ?)", (file_path, file_name)
    )
    await db.commit()
    return cursor.lastrowid


async def run_scan(db, root: Path, containers: list[str]):
    scanner.scan_progress.reset()
    await scanner._run_scan_worker(db, str(root), containers)


async def seed_deep_tree(db, tmp_path: Path):
    """characters/game/ba/三一/修女會/瑪麗/img.jpeg -- a 5-level-deep chain."""
    img = tmp_path / "characters" / "game" / "ba" / "三一" / "修女會" / "瑪麗" / "a.jpeg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    return img


async def test_set_and_delete_character_tag(db, tmp_path):
    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)
    image_id = row["id"]
    original_char_id = row["char_id"]

    cursor = await db.execute(
        "INSERT INTO character_tag (parent_id, name) VALUES (0, 'manual_pick')"
    )
    await db.commit()
    manual_id = cursor.lastrowid

    # set_character_tag moves the file (see ADR-0006), so the row is looked
    # up by id from here on -- its file_path no longer matches `img`.
    await images_routes.set_character_tag(image_id=image_id, character_id=manual_id, db=db)
    cursor = await db.execute("SELECT * FROM images WHERE id = ?", (image_id,))
    row = await cursor.fetchone()
    assert row["char_id"] == manual_id
    assert row["file_path"] == "manual_pick/a.jpg"
    assert (tmp_path / "manual_pick" / "a.jpg").exists()
    assert not img.exists()

    await images_routes.delete_tag(image_id=image_id, tag_id=manual_id, tag_type="character", db=db)
    cursor = await db.execute("SELECT * FROM images WHERE id = ?", (image_id,))
    row = await cursor.fetchone()
    assert row["char_id"] == 0

    assert original_char_id != manual_id  # sanity: we really did change it


async def test_set_artist_tag_writes_backup_entry_with_ancestor_path(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    image_id = (await get_image(db, img))["id"]

    cursor = await db.execute(
        "INSERT INTO individual_tag (parent_id, name) VALUES (0, 'individuals')"
    )
    root_id = cursor.lastrowid
    cursor = await db.execute(
        "INSERT INTO individual_tag (parent_id, name) VALUES (?, '紅茶社')", (root_id,)
    )
    artist_id = cursor.lastrowid
    await db.commit()

    await images_routes.set_artist_tag(image_id=image_id, artist_id=artist_id, db=db)

    assert artist_backup.load_backup(backup_path) == {
        (await get_image(db, img))["file_hash"]: ["individuals", "紅茶社"]
    }


async def test_set_artist_tag_with_root_id_removes_backup_entry(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    image_id = (await get_image(db, img))["id"]
    file_hash = (await get_image(db, img))["file_hash"]

    artist_backup.set_entry(backup_path, file_hash, ["individuals", "someone"])
    await images_routes.set_artist_tag(image_id=image_id, artist_id=0, db=db)

    assert artist_backup.load_backup(backup_path) == {}


async def test_delete_tag_artist_removes_backup_entry(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    image_id = (await get_image(db, img))["id"]

    cursor = await db.execute(
        "INSERT INTO individual_tag (parent_id, name) VALUES (0, 'someone')"
    )
    artist_id = cursor.lastrowid
    await db.commit()

    await images_routes.set_artist_tag(image_id=image_id, artist_id=artist_id, db=db)
    assert artist_backup.load_backup(backup_path) != {}

    await images_routes.delete_tag(image_id=image_id, tag_id=artist_id, tag_type="artist", db=db)

    assert artist_backup.load_backup(backup_path) == {}


async def test_delete_tag_character_does_not_touch_artist_backup(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)
    image_id, original_char_id = row["id"], row["char_id"]

    # Pre-seed an unrelated artist backup entry.
    artist_backup.set_entry(backup_path, "unrelated-hash", ["individuals", "someone"])

    await images_routes.delete_tag(image_id=image_id, tag_id=original_char_id, tag_type="character", db=db)

    assert artist_backup.load_backup(backup_path) == {"unrelated-hash": ["individuals", "someone"]}


async def test_delete_image_record_removes_only_that_row(db, tmp_path):
    keep = tmp_path / "characters" / "game" / "char" / "keep.jpg"
    gone = tmp_path / "characters" / "game" / "char" / "gone.jpg"
    make_image(keep)
    make_image(gone)
    await run_scan(db, tmp_path, ["characters"])
    keep_id = (await get_image(db, keep))["id"]
    gone_id = (await get_image(db, gone))["id"]

    await images_routes.delete_image(image_id=gone_id, db=db)

    cursor = await db.execute("SELECT id FROM images WHERE id = ?", (gone_id,))
    assert await cursor.fetchone() is None
    cursor = await db.execute("SELECT id FROM images WHERE id = ?", (keep_id,))
    assert await cursor.fetchone() is not None


async def test_delete_image_record_missing_id_404s(db):
    with pytest.raises(HTTPException) as exc_info:
        await images_routes.delete_image(image_id=999999, db=db)
    assert exc_info.value.status_code == 404


async def _list_images(db, **overrides):
    defaults = dict(
        page=1, per_page=50, character=None, char_id=None,
        artist=None, artist_id=None, include_descendants=False,
        file_name=None, source_folder=None, file_format=None,
        min_width=None, max_width=None, min_height=None, max_height=None,
        sort_by="imported_at", sort_order="desc", db=db,
    )
    defaults.update(overrides)
    return await images_routes.list_images(**defaults)


async def test_list_image_formats_reflects_actual_data(db, tmp_path):
    jpg = tmp_path / "characters" / "game" / "char" / "a.jpg"
    mp4 = tmp_path / "characters" / "game" / "char" / "b.mp4"
    make_image(jpg)
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"not a real video")
    await run_scan(db, tmp_path, ["characters"])

    result = await images_routes.list_image_formats(db=db)
    assert set(result["formats"]) == {".jpg", ".mp4"}


async def test_images_filter_by_file_name(db, tmp_path):
    match = tmp_path / "characters" / "game" / "char" / "123456_p0.jpg"
    other = tmp_path / "characters" / "game" / "char" / "999999_p0.jpg"
    make_image(match)
    make_image(other)
    await run_scan(db, tmp_path, ["characters"])

    result = await _list_images(db, file_name="123456")
    paths = {i["file_path"] for i in result["images"]}
    assert paths == {match.relative_to(tmp_path).as_posix()}


async def test_file_name_search_does_not_match_folder_names(db, tmp_path):
    """The filter must only look at file_name, not the full file_path, so a
    folder named e.g. 'ba' doesn't accidentally match every file under it."""
    img = tmp_path / "characters" / "game" / "ba" / "char" / "unrelated.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])

    result = await _list_images(db, file_name="ba")
    assert result["images"] == []


async def test_images_filter_by_char_id_zero_is_not_ignored(db, tmp_path):
    """Regression: `if character_id:` treated 0 as "not provided", but 0
    (root = "no character") is now a meaningful, explicitly filterable value."""
    char_img = tmp_path / "characters" / "game" / "char" / "a.jpg"
    indiv_img = tmp_path / "individuals" / "artist" / "b.jpg"
    make_image(char_img)
    make_image(indiv_img)
    await run_scan(db, tmp_path, ["characters", "individuals"])

    result = await _list_images(db, char_id=0)
    paths = {i["file_path"] for i in result["images"]}
    assert paths == {indiv_img.relative_to(tmp_path).as_posix()}  # only the char_id=0 (individuals-side) image


async def test_images_filter_by_char_id_exact_excludes_descendants(db, tmp_path):
    img = await seed_deep_tree(db, tmp_path)
    row = await get_image(db, img)
    cursor = await db.execute("SELECT id FROM character_tag WHERE name = 'ba'")
    ba_id = (await cursor.fetchone())["id"]

    result = await _list_images(db, char_id=ba_id, include_descendants=False)
    assert result["images"] == []  # 'ba' itself has no direct image, only descendants do


async def test_images_filter_by_char_id_with_include_descendants(db, tmp_path):
    img = await seed_deep_tree(db, tmp_path)
    row = await get_image(db, img)
    cursor = await db.execute("SELECT id FROM character_tag WHERE name = 'ba'")
    ba_id = (await cursor.fetchone())["id"]

    result = await _list_images(db, char_id=ba_id, include_descendants=True)
    ids = {i["id"] for i in result["images"]}
    assert row["id"] in ids


async def test_images_filter_by_artist_id_with_include_descendants(db, tmp_path):
    img = tmp_path / "individuals" / "artistA" / "seriesX" / "char" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["individuals"])
    row = await get_image(db, img)

    cursor = await db.execute("SELECT id FROM individual_tag WHERE name = 'artistA'")
    artist_id = (await cursor.fetchone())["id"]

    exact = await _list_images(db, artist_id=artist_id, include_descendants=False)
    assert exact["images"] == []

    expanded = await _list_images(db, artist_id=artist_id, include_descendants=True)
    ids = {i["id"] for i in expanded["images"]}
    assert row["id"] in ids


async def test_images_filter_by_char_id_and_artist_id_together_with_descendants(db, tmp_path):
    """Regression: combining two include_descendants=True filters in one
    request must not produce invalid SQL (two concatenated WITH clauses)."""
    char_img = tmp_path / "characters" / "game" / "ba" / "char" / "a.jpg"
    make_image(char_img)
    await run_scan(db, tmp_path, ["characters"])

    artist_img = tmp_path / "individuals" / "artistA" / "seriesX" / "b.jpg"
    make_image(artist_img)
    await run_scan(db, tmp_path, ["individuals"])

    cursor = await db.execute("SELECT id FROM character_tag WHERE name = 'game'")
    game_id = (await cursor.fetchone())["id"]
    cursor = await db.execute("SELECT id FROM individual_tag WHERE name = 'artistA'")
    artist_id = (await cursor.fetchone())["id"]

    result = await _list_images(
        db, char_id=game_id, artist_id=artist_id, include_descendants=True
    )
    # No image matches char_id under 'game' AND artist_id under 'artistA' at
    # once (they're unrelated files); the point is this doesn't raise.
    assert result["images"] == []


async def test_get_image_file_serves_legacy_absolute_path_unchanged(db, tmp_path):
    img = tmp_path / "a.jpg"
    make_image(img)
    image_id = await insert_image_row(db, str(img))

    response = await images_routes.get_image_file(image_id=image_id, db=db)
    assert Path(response.path) == img


async def test_get_image_file_resolves_relative_path_against_import_root(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IMPORT_ROOT_PATH", tmp_path / "import_root.json")
    root = tmp_path / "library"
    img = root / "characters" / "a.jpg"
    make_image(img)
    import_root.save_import_root(config.IMPORT_ROOT_PATH, str(root))
    image_id = await insert_image_row(db, "characters/a.jpg")

    response = await images_routes.get_image_file(image_id=image_id, db=db)
    assert Path(response.path) == img


async def test_get_image_file_404s_when_resolved_file_missing(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IMPORT_ROOT_PATH", tmp_path / "import_root.json")
    import_root.save_import_root(config.IMPORT_ROOT_PATH, str(tmp_path / "library"))
    image_id = await insert_image_row(db, "characters/does-not-exist.jpg")

    with pytest.raises(HTTPException) as exc_info:
        await images_routes.get_image_file(image_id=image_id, db=db)
    assert exc_info.value.status_code == 404


# --- set_character_tag moves the file (ADR-0006) ---------------------------


async def test_set_character_tag_moves_file_and_updates_relative_path(db, tmp_path):
    img = tmp_path / "characters" / "old" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)

    cursor = await db.execute("INSERT INTO character_tag (parent_id, name) VALUES (0, 'newchar')")
    await db.commit()
    new_char_id = cursor.lastrowid

    await images_routes.set_character_tag(image_id=row["id"], character_id=new_char_id, db=db)

    cursor = await db.execute("SELECT * FROM images WHERE id = ?", (row["id"],))
    updated = await cursor.fetchone()
    assert updated["char_id"] == new_char_id
    assert updated["file_path"] == "newchar/a.jpg"
    assert (tmp_path / "newchar" / "a.jpg").exists()
    assert not img.exists()


async def test_set_character_tag_rejects_root_id(db, tmp_path):
    img = tmp_path / "characters" / "old" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)

    with pytest.raises(HTTPException) as exc_info:
        await images_routes.set_character_tag(image_id=row["id"], character_id=0, db=db)
    assert exc_info.value.status_code == 400
    assert img.exists()  # untouched


async def test_set_character_tag_404s_for_missing_character(db, tmp_path):
    img = tmp_path / "characters" / "old" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)

    with pytest.raises(HTTPException) as exc_info:
        await images_routes.set_character_tag(image_id=row["id"], character_id=999999, db=db)
    assert exc_info.value.status_code == 404
    assert img.exists()  # untouched


async def test_set_character_tag_rejects_destination_collision(db, tmp_path):
    img = tmp_path / "characters" / "old" / "a.jpg"
    make_image(img)
    make_image(tmp_path / "newchar" / "a.jpg")  # pre-existing file at the destination
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)

    cursor = await db.execute("INSERT INTO character_tag (parent_id, name) VALUES (0, 'newchar')")
    await db.commit()
    new_char_id = cursor.lastrowid

    with pytest.raises(HTTPException) as exc_info:
        await images_routes.set_character_tag(image_id=row["id"], character_id=new_char_id, db=db)
    assert exc_info.value.status_code == 400

    assert img.exists()  # source untouched
    cursor = await db.execute("SELECT char_id FROM images WHERE id = ?", (row["id"],))
    assert (await cursor.fetchone())["char_id"] == row["char_id"]  # unchanged


async def test_set_character_tag_moves_file_back_when_db_write_fails(db, tmp_path, monkeypatch):
    img = tmp_path / "characters" / "old" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["characters"])
    row = await get_image(db, img)

    cursor = await db.execute("INSERT INTO character_tag (parent_id, name) VALUES (0, 'newchar')")
    await db.commit()
    new_char_id = cursor.lastrowid

    async def failing_commit():
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(db, "commit", failing_commit)

    with pytest.raises(RuntimeError):
        await images_routes.set_character_tag(image_id=row["id"], character_id=new_char_id, db=db)

    assert img.exists()  # moved back to the original location
    assert not (tmp_path / "newchar" / "a.jpg").exists()


async def test_set_character_tag_does_not_affect_artist_id_or_hash(db, tmp_path, monkeypatch):
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(config, "ARTIST_TAGS_BACKUP_PATH", backup_path)

    img = tmp_path / "individuals" / "artistA" / "a.jpg"
    make_image(img)
    await run_scan(db, tmp_path, ["individuals"])
    row = await get_image(db, img)
    original_artist_id = row["artist_id"]
    original_hash = row["file_hash"]

    cursor = await db.execute("INSERT INTO character_tag (parent_id, name) VALUES (0, 'newchar')")
    await db.commit()
    new_char_id = cursor.lastrowid

    await images_routes.set_character_tag(image_id=row["id"], character_id=new_char_id, db=db)

    cursor = await db.execute("SELECT * FROM images WHERE id = ?", (row["id"],))
    updated = await cursor.fetchone()
    assert updated["artist_id"] == original_artist_id
    assert updated["file_hash"] == original_hash
