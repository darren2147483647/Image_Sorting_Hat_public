import pytest
from fastapi import HTTPException

from routes import individual_tags


async def seed_individuals_container(db):
    cursor = await db.execute(
        "INSERT INTO individual_tag (parent_id, name) VALUES (0, 'individuals')"
    )
    await db.commit()
    return cursor.lastrowid


async def test_creates_new_artist_node_under_individuals_container(db):
    individuals_id = await seed_individuals_container(db)

    result = await individual_tags.create_individual_tag(name="Ooguni", db=db)

    cursor = await db.execute(
        "SELECT parent_id, name FROM individual_tag WHERE id = ?", (result["id"],)
    )
    row = await cursor.fetchone()
    assert row["name"] == "Ooguni"
    assert row["parent_id"] == individuals_id


async def test_returns_existing_node_for_same_case_name(db):
    await seed_individuals_container(db)
    first = await individual_tags.create_individual_tag(name="Ooguni", db=db)

    second = await individual_tags.create_individual_tag(name="Ooguni", db=db)

    assert second["id"] == first["id"]
    cursor = await db.execute("SELECT COUNT(*) as n FROM individual_tag WHERE name = 'Ooguni'")
    assert (await cursor.fetchone())["n"] == 1


async def test_returns_existing_node_for_different_case_name(db):
    """The key duplicate-prevention behaviour: 'ooguni' must resolve to the
    same node as an existing 'Ooguni', not create a second one."""
    await seed_individuals_container(db)
    first = await individual_tags.create_individual_tag(name="Ooguni", db=db)

    second = await individual_tags.create_individual_tag(name="ooguni", db=db)

    assert second["id"] == first["id"]
    assert second["name"] == "Ooguni"  # the pre-existing casing is preserved, not overwritten
    cursor = await db.execute("SELECT COUNT(*) as n FROM individual_tag WHERE name = 'Ooguni'")
    assert (await cursor.fetchone())["n"] == 1


async def test_rejects_blank_name(db):
    await seed_individuals_container(db)

    with pytest.raises(HTTPException) as exc_info:
        await individual_tags.create_individual_tag(name="   ", db=db)
    assert exc_info.value.status_code == 400


async def test_different_artists_get_different_nodes(db):
    await seed_individuals_container(db)

    a = await individual_tags.create_individual_tag(name="Ooguni", db=db)
    b = await individual_tags.create_individual_tag(name="Mauve", db=db)

    assert a["id"] != b["id"]


async def test_rejects_windows_illegal_character(db):
    await seed_individuals_container(db)

    with pytest.raises(HTTPException) as exc_info:
        await individual_tags.create_individual_tag(name="foo<bar", db=db)
    assert exc_info.value.status_code == 400

    cursor = await db.execute("SELECT COUNT(*) as n FROM individual_tag WHERE name LIKE 'foo%'")
    assert (await cursor.fetchone())["n"] == 0


async def test_rejects_reserved_device_name(db):
    await seed_individuals_container(db)

    with pytest.raises(HTTPException) as exc_info:
        await individual_tags.create_individual_tag(name="CON", db=db)
    assert exc_info.value.status_code == 400


async def test_rejects_new_name_with_trailing_dot_when_no_existing_match(db):
    await seed_individuals_container(db)

    with pytest.raises(HTTPException) as exc_info:
        await individual_tags.create_individual_tag(name="Ooguni.", db=db)
    assert exc_info.value.status_code == 400


async def test_resolves_trailing_dot_variant_to_existing_node(db):
    """"Ooguni." is itself an illegal name, but since "Ooguni" already
    exists, this must resolve to the existing node instead of being
    rejected -- not creating anything new."""
    await seed_individuals_container(db)
    first = await individual_tags.create_individual_tag(name="Ooguni", db=db)

    second = await individual_tags.create_individual_tag(name="Ooguni.", db=db)

    assert second["id"] == first["id"]
    assert second["name"] == "Ooguni"
    cursor = await db.execute("SELECT COUNT(*) as n FROM individual_tag WHERE name LIKE 'Ooguni%'")
    assert (await cursor.fetchone())["n"] == 1
