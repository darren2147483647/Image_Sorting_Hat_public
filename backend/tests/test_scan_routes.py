import asyncio

from PIL import Image

import config
import import_root
import local_config
from routes import scan as scan_routes


async def fake_start_scan_task(*args, **kwargs):
    pass


async def test_start_scan_returns_loose_individuals_count(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_routes, "start_scan_task", fake_start_scan_task)
    monkeypatch.setattr(scan_routes, "_scan_task", None)

    individuals_root = tmp_path / "individuals"
    individuals_root.mkdir(parents=True)
    Image.new("RGB", (4, 4), color=(1, 2, 3)).save(individuals_root / "loose.jpg")
    Image.new("RGB", (4, 4), color=(1, 2, 3)).save(individuals_root / "loose2.jpg")

    result = await scan_routes.start_scan(
        root_path=str(tmp_path), folders="individuals", include_other=True
    )

    assert result["loose_individuals_count"] == 2
    await asyncio.sleep(0)  # let the faked background task finish cleanly


async def test_start_scan_returns_zero_loose_count_when_none_loose(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_routes, "start_scan_task", fake_start_scan_task)
    monkeypatch.setattr(scan_routes, "_scan_task", None)

    individuals_root = tmp_path / "individuals"
    artist_dir = individuals_root / "someartist"
    artist_dir.mkdir(parents=True)
    Image.new("RGB", (4, 4), color=(1, 2, 3)).save(artist_dir / "a.jpg")

    result = await scan_routes.start_scan(
        root_path=str(tmp_path), folders="individuals", include_other=True
    )

    assert result["loose_individuals_count"] == 0
    await asyncio.sleep(0)


async def test_start_scan_rejects_fixed_char_policy_without_target(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_routes, "start_scan_task", fake_start_scan_task)
    monkeypatch.setattr(scan_routes, "_scan_task", None)

    result = await scan_routes.start_scan(
        root_path=str(tmp_path), folders="characters", char_policy="fixed", char_fixed_id=None
    )

    assert "error" in result


async def test_start_scan_rejects_fixed_artist_policy_without_target(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_routes, "start_scan_task", fake_start_scan_task)
    monkeypatch.setattr(scan_routes, "_scan_task", None)

    result = await scan_routes.start_scan(
        root_path=str(tmp_path), folders="individuals", artist_policy="fixed", artist_fixed_id=None
    )

    assert "error" in result


async def test_start_scan_accepts_fixed_policy_with_target(tmp_path, monkeypatch):
    captured = {}

    async def capturing_start_scan_task(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(scan_routes, "start_scan_task", capturing_start_scan_task)
    monkeypatch.setattr(scan_routes, "_scan_task", None)

    result = await scan_routes.start_scan(
        root_path=str(tmp_path), folders="characters", char_policy="fixed", char_fixed_id=42
    )
    await asyncio.sleep(0)  # let the created task actually run before inspecting captured

    assert "error" not in result
    assert captured["char_policy"].mode == "fixed"
    assert captured["char_policy"].fixed_id == 42


async def test_start_scan_rejects_path_outside_import_root(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_routes, "start_scan_task", fake_start_scan_task)
    monkeypatch.setattr(scan_routes, "_scan_task", None)

    outside_path = tmp_path.parent / "totally-unrelated-root"
    result = await scan_routes.start_scan(root_path=str(outside_path), folders="characters")

    assert "error" in result


async def test_start_scan_accepts_import_root_itself(tmp_path, monkeypatch):
    captured = {}

    async def capturing_start_scan_task(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(scan_routes, "start_scan_task", capturing_start_scan_task)
    monkeypatch.setattr(scan_routes, "_scan_task", None)

    result = await scan_routes.start_scan(root_path=str(tmp_path), folders="characters")
    await asyncio.sleep(0)

    assert "error" not in result
    assert captured["import_root_dir"] == str(tmp_path)


async def test_get_import_root_returns_currently_saved_value(tmp_path):
    custom_root = tmp_path / "外接硬碟" / "桌布v3"
    import_root.save_import_root(config.IMPORT_ROOT_PATH, str(custom_root))

    result = await scan_routes.get_import_root()

    assert result["root_path"] == str(custom_root)


async def test_save_import_root_persists_and_is_read_back(tmp_path):
    new_root = str(tmp_path / "moved")

    await scan_routes.set_import_root(root_path=new_root)
    result = await scan_routes.get_import_root()

    assert result["root_path"] == new_root


async def test_save_import_root_reports_exists_true_for_real_directory(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()

    result = await scan_routes.set_import_root(root_path=str(real_dir))

    assert result["exists"] is True


async def test_save_import_root_reports_exists_false_but_still_saves(tmp_path):
    missing_dir = tmp_path / "not-plugged-in-yet"

    result = await scan_routes.set_import_root(root_path=str(missing_dir))

    assert result["exists"] is False
    assert (await scan_routes.get_import_root())["root_path"] == str(missing_dir)


async def test_get_records_dir_returns_current_running_process_value():
    """Unlike import root, this reflects config.DATA_DIR as already resolved
    for THIS running process at startup -- see ADR-0008. Saving a new value
    (below) never changes what this returns until a restart."""
    result = await scan_routes.get_records_dir()

    assert result["records_dir"] == str(config.DATA_DIR)


async def test_save_records_dir_persists_the_setting(tmp_path):
    new_dir = str(tmp_path / "外接硬碟" / "紀錄")

    await scan_routes.set_records_dir(records_dir=new_dir)

    assert local_config.load_value(config.RECORDS_DIR_SETTING_PATH, "records_dir", None) == new_dir


async def test_save_records_dir_does_not_change_current_process_data_dir(tmp_path):
    """The whole point of ADR-0008's restart-required design: saving must
    never mutate config.DATA_DIR (or anything database.py already resolved
    from it) for the process that's still running."""
    original_data_dir = config.DATA_DIR

    await scan_routes.set_records_dir(records_dir=str(tmp_path / "somewhere-else"))

    assert config.DATA_DIR == original_data_dir


async def test_save_records_dir_reports_restart_required():
    result = await scan_routes.set_records_dir(records_dir="anything")

    assert result["restart_required"] is True


async def test_save_records_dir_reports_exists_true_for_real_directory(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()

    result = await scan_routes.set_records_dir(records_dir=str(real_dir))

    assert result["exists"] is True


async def test_save_records_dir_reports_exists_false_but_still_saves(tmp_path):
    missing_dir = tmp_path / "not-plugged-in-yet"

    result = await scan_routes.set_records_dir(records_dir=str(missing_dir))

    assert result["exists"] is False
    assert (await scan_routes.get_records_dir())["records_dir"] == str(config.DATA_DIR)


async def test_start_scan_accepts_subfolder_of_import_root(tmp_path, monkeypatch):
    captured = {}

    async def capturing_start_scan_task(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(scan_routes, "start_scan_task", capturing_start_scan_task)
    monkeypatch.setattr(scan_routes, "_scan_task", None)

    sub = tmp_path / "batch1"
    sub.mkdir()
    result = await scan_routes.start_scan(root_path=str(sub), folders="characters")
    await asyncio.sleep(0)

    assert "error" not in result
    assert captured["import_root_dir"] == str(tmp_path)
