from pathlib import Path

import import_root


def test_load_import_root_missing_file_returns_default(tmp_path):
    assert import_root.load_import_root(tmp_path / "nope.json") == import_root.DEFAULT_IMPORT_ROOT


def test_load_import_root_corrupt_file_returns_default(tmp_path):
    path = tmp_path / "import_root.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert import_root.load_import_root(path) == import_root.DEFAULT_IMPORT_ROOT


def test_load_import_root_malformed_structure_returns_default(tmp_path):
    path = tmp_path / "import_root.json"
    path.write_text('{"root_path": 123}', encoding="utf-8")
    assert import_root.load_import_root(path) == import_root.DEFAULT_IMPORT_ROOT


def test_save_then_load_round_trips_including_non_ascii(tmp_path):
    path = tmp_path / "import_root.json"
    root = "D:\\外接硬碟\\桌布v3"
    import_root.save_import_root(path, root)
    assert import_root.load_import_root(path) == root


def test_save_import_root_leaves_no_leftover_temp_file(tmp_path):
    path = tmp_path / "import_root.json"
    import_root.save_import_root(path, "D:\\x")
    leftovers = [p for p in tmp_path.iterdir() if p != path]
    assert leftovers == []


def test_save_import_root_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "import_root.json"
    import_root.save_import_root(path, "D:\\x")
    assert path.exists()


def test_to_relative_computes_posix_style_path(tmp_path):
    root = tmp_path / "桌布v3"
    file_path = root / "characters" / "game" / "a.jpg"
    assert import_root.to_relative(str(file_path), str(root)) == "characters/game/a.jpg"


def test_to_relative_handles_deeply_nested_paths(tmp_path):
    root = tmp_path / "root"
    file_path = root / "a" / "b" / "c" / "d" / "e.jpg"
    assert import_root.to_relative(str(file_path), str(root)) == "a/b/c/d/e.jpg"


def test_resolve_absolute_input_returned_unchanged(tmp_path):
    abs_path = str(tmp_path / "characters" / "a.jpg")
    assert import_root.resolve(abs_path, str(tmp_path / "some_other_root")) == abs_path


def test_resolve_relative_input_joined_with_root(tmp_path):
    root = tmp_path / "桌布v3"
    resolved = import_root.resolve("characters/a.jpg", str(root))
    assert Path(resolved) == root / "characters" / "a.jpg"


def test_is_within_true_for_root_itself(tmp_path):
    root = tmp_path / "桌布v3"
    assert import_root.is_within(str(root), str(root)) is True


def test_is_within_true_for_nested_subpath(tmp_path):
    root = tmp_path / "桌布v3"
    sub = root / "characters" / "game"
    assert import_root.is_within(str(sub), str(root)) is True


def test_is_within_false_for_unrelated_path(tmp_path):
    root = tmp_path / "桌布v3"
    other = tmp_path / "別的資料夾"
    assert import_root.is_within(str(other), str(root)) is False


def test_is_within_false_for_prefix_similar_sibling(tmp_path):
    root = tmp_path / "root"
    sibling = tmp_path / "root2"
    assert import_root.is_within(str(sibling), str(root)) is False
