from pathlib import Path

import pytest

from character_reassignment import DestinationExistsError, move_back, move_to_character_folder


def make_file(path: Path, content: bytes = b"hello"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_moves_file_to_computed_destination(tmp_path):
    root = tmp_path / "library"
    source = root / "characters" / "old" / "a.jpg"
    make_file(source, b"content")

    new_path = move_to_character_folder(str(source), str(root), ["characters", "new"])

    assert Path(new_path) == root / "characters" / "new" / "a.jpg"
    assert Path(new_path).exists()
    assert not source.exists()
    assert Path(new_path).read_bytes() == b"content"


def test_creates_destination_folder_chain_if_missing(tmp_path):
    root = tmp_path / "library"
    source = root / "characters" / "a.jpg"
    make_file(source)

    new_path = move_to_character_folder(
        str(source), str(root), ["characters", "brand", "new", "chain"]
    )

    assert Path(new_path).exists()


def test_raises_and_does_not_move_when_destination_exists(tmp_path):
    root = tmp_path / "library"
    source = root / "characters" / "old" / "a.jpg"
    make_file(source, b"source content")
    dest_dir = root / "characters" / "new"
    make_file(dest_dir / "a.jpg", b"existing content")

    with pytest.raises(DestinationExistsError):
        move_to_character_folder(str(source), str(root), ["characters", "new"])

    assert source.exists()  # untouched
    assert source.read_bytes() == b"source content"
    assert (dest_dir / "a.jpg").read_bytes() == b"existing content"  # untouched


def test_move_back_restores_original_location(tmp_path):
    root = tmp_path / "library"
    original = root / "characters" / "old" / "a.jpg"
    make_file(original, b"content")

    new_path = move_to_character_folder(str(original), str(root), ["characters", "new"])
    move_back(str(original), new_path)

    assert original.exists()
    assert not Path(new_path).exists()
    assert original.read_bytes() == b"content"
