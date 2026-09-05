import json
from pathlib import Path

import artist_backup


def test_load_backup_missing_file_returns_empty_dict(tmp_path):
    assert artist_backup.load_backup(tmp_path / "nope.json") == {}


def test_load_backup_corrupt_file_returns_empty_dict(tmp_path):
    path = tmp_path / "backup.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert artist_backup.load_backup(path) == {}


def test_save_then_load_round_trips_including_non_ascii(tmp_path):
    path = tmp_path / "backup.json"
    data = {"abc123": ["individuals", "紅茶社", "XYZ"]}
    artist_backup.save_backup(path, data)
    assert artist_backup.load_backup(path) == data


def test_save_backup_leaves_no_leftover_temp_file(tmp_path):
    path = tmp_path / "backup.json"
    artist_backup.save_backup(path, {"a": ["x"]})
    leftovers = [p for p in tmp_path.iterdir() if p != path]
    assert leftovers == []


def test_save_backup_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "backup.json"
    artist_backup.save_backup(path, {"a": ["x"]})
    assert path.exists()


def test_set_entry_adds_new_key(tmp_path):
    path = tmp_path / "backup.json"
    artist_backup.set_entry(path, "hash1", ["individuals", "A"])
    assert artist_backup.load_backup(path) == {"hash1": ["individuals", "A"]}


def test_set_entry_overwrites_existing_key(tmp_path):
    path = tmp_path / "backup.json"
    artist_backup.set_entry(path, "hash1", ["individuals", "A"])
    artist_backup.set_entry(path, "hash1", ["individuals", "B"])
    assert artist_backup.load_backup(path) == {"hash1": ["individuals", "B"]}


def test_set_entry_preserves_other_keys(tmp_path):
    path = tmp_path / "backup.json"
    artist_backup.set_entry(path, "hash1", ["individuals", "A"])
    artist_backup.set_entry(path, "hash2", ["individuals", "B"])
    assert artist_backup.load_backup(path) == {
        "hash1": ["individuals", "A"],
        "hash2": ["individuals", "B"],
    }


def test_remove_entry_deletes_present_key(tmp_path):
    path = tmp_path / "backup.json"
    artist_backup.set_entry(path, "hash1", ["individuals", "A"])
    artist_backup.remove_entry(path, "hash1")
    assert artist_backup.load_backup(path) == {}


def test_remove_entry_absent_key_is_a_noop(tmp_path):
    path = tmp_path / "backup.json"
    artist_backup.set_entry(path, "hash1", ["individuals", "A"])
    artist_backup.remove_entry(path, "does-not-exist")
    assert artist_backup.load_backup(path) == {"hash1": ["individuals", "A"]}


def test_remove_entry_missing_file_is_a_noop(tmp_path):
    path = tmp_path / "backup.json"
    artist_backup.remove_entry(path, "hash1")  # must not raise
    assert artist_backup.load_backup(path) == {}


def test_append_conflict_log_writes_one_json_line(tmp_path):
    path = tmp_path / "scan_conflicts.log"
    entry = {
        "file_path": "a.jpg",
        "file_hash": "abc123",
        "existing": ["individuals", "Ooguni"],
        "discarded": ["individuals", "Mauve"],
    }
    artist_backup.append_conflict_log(path, entry)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == entry


def test_append_conflict_log_appends_without_overwriting(tmp_path):
    path = tmp_path / "scan_conflicts.log"
    artist_backup.append_conflict_log(path, {"n": 1})
    artist_backup.append_conflict_log(path, {"n": 2})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [{"n": 1}, {"n": 2}]


def test_append_conflict_log_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "scan_conflicts.log"
    artist_backup.append_conflict_log(path, {"n": 1})
    assert path.exists()


def test_append_conflict_log_preserves_non_ascii(tmp_path):
    path = tmp_path / "scan_conflicts.log"
    entry = {"existing": ["individuals", "紅茶社"]}
    artist_backup.append_conflict_log(path, entry)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == entry
