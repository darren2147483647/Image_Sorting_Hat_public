import local_config


def test_load_value_returns_default_when_file_missing(tmp_path):
    path = tmp_path / "nope.json"
    assert local_config.load_value(path, "some_key", "fallback") == "fallback"


def test_load_value_returns_default_when_file_is_corrupt(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("not json{{{", encoding="utf-8")
    assert local_config.load_value(path, "some_key", "fallback") == "fallback"


def test_load_value_returns_default_when_key_absent(tmp_path):
    path = tmp_path / "settings.json"
    local_config.save_value(path, "other_key", "irrelevant")
    assert local_config.load_value(path, "some_key", "fallback") == "fallback"


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "settings.json"
    local_config.save_value(path, "records_dir", "D:\\外接硬碟\\紀錄")
    assert local_config.load_value(path, "records_dir", "fallback") == "D:\\外接硬碟\\紀錄"


def test_save_overwrites_existing_value_for_same_key(tmp_path):
    path = tmp_path / "settings.json"
    local_config.save_value(path, "records_dir", "first")
    local_config.save_value(path, "records_dir", "second")
    assert local_config.load_value(path, "records_dir", "fallback") == "second"


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "settings.json"
    local_config.save_value(path, "records_dir", "value")
    assert local_config.load_value(path, "records_dir", "fallback") == "value"


def test_save_leaves_no_leftover_temp_files(tmp_path):
    path = tmp_path / "settings.json"
    local_config.save_value(path, "records_dir", "value")
    remaining = list(tmp_path.iterdir())
    assert remaining == [path]
