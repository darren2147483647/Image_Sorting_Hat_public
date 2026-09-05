import local_config
import config


def test_resolve_data_dir_defaults_to_base_dir_data_when_no_setting(tmp_path):
    setting_path = tmp_path / "records_dir.json"
    assert config._resolve_data_dir(setting_path, tmp_path) == tmp_path / "data"


def test_resolve_data_dir_uses_persisted_setting_when_the_directory_exists(tmp_path):
    setting_path = tmp_path / "records_dir.json"
    custom_dir = tmp_path / "external_drive" / "紀錄"
    custom_dir.mkdir(parents=True)
    local_config.save_value(setting_path, "records_dir", str(custom_dir))

    assert config._resolve_data_dir(setting_path, tmp_path) == custom_dir


def test_resolve_data_dir_ignores_corrupt_setting_file(tmp_path):
    setting_path = tmp_path / "records_dir.json"
    setting_path.write_text("not json{{{", encoding="utf-8")

    assert config._resolve_data_dir(setting_path, tmp_path) == tmp_path / "data"


def test_resolve_data_dir_falls_back_to_default_when_configured_dir_does_not_exist(tmp_path, capsys):
    """The whole point: never let database.py reach for a possibly-absent
    external device (e.g. an unplugged drive, or a typo'd path) -- fall back
    to the always-safe, in-checkout default instead (see ADR-0008 addendum)."""
    setting_path = tmp_path / "records_dir.json"
    missing_dir = tmp_path / "external_drive" / "紀錄"  # never created
    local_config.save_value(setting_path, "records_dir", str(missing_dir))

    result = config._resolve_data_dir(setting_path, tmp_path)

    assert result == tmp_path / "data"
    assert "紀錄目錄" in capsys.readouterr().out


def test_resolve_data_dir_fallback_does_not_overwrite_the_setting_file(tmp_path):
    """Falling back is in-memory only for this run -- the persisted setting
    must survive untouched, so plugging the drive back in (or fixing the
    typo) makes the original intended location take effect again on the
    next restart, without the user having to re-enter it."""
    setting_path = tmp_path / "records_dir.json"
    missing_dir = tmp_path / "external_drive" / "紀錄"
    local_config.save_value(setting_path, "records_dir", str(missing_dir))

    config._resolve_data_dir(setting_path, tmp_path)

    assert local_config.load_value(setting_path, "records_dir", None) == str(missing_dir)
