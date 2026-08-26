import json

from arcaea_pull.core.state_manager import SCHEMA_VERSION, StateManager


def test_first_load_creates_state(tmp_path):
    manager = StateManager(tmp_path / "state.json")
    state = manager.load()
    assert state["schema_version"] == SCHEMA_VERSION
    assert manager.path.exists()


def test_normal_read_write_and_independent_fields(tmp_path):
    manager = StateManager(tmp_path / "state.json")
    manager.record_observed("1", "https://x/a", "now")
    manager.record_notification("1")
    state = manager.load()
    assert state["observed"]["version"] == "1"
    assert state["notification"]["last_notified_version"] == "1"
    assert state["download"] == {}


def test_invalid_json_is_quarantined_and_recovers(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    state = StateManager(path).load()
    assert state["schema_version"] == SCHEMA_VERSION
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == SCHEMA_VERSION
    assert list(tmp_path.glob("state.json.corrupt-*"))


def test_save_leaves_no_temporary_file(tmp_path):
    manager = StateManager(tmp_path / "state.json")
    manager.save(manager.load())
    assert not list(tmp_path.glob("*.tmp"))


def test_schema_one_is_migrated_without_quarantine(tmp_path):
    path = tmp_path / "state.json"
    old = {
        "schema_version": 1,
        "remote": {"version": "1"},
        "observed": {"version": "1"},
        "notification": {},
        "download": {"last_downloaded_version": "1"},
        "distribution": {},
        "last_extracted_version": None,
    }
    path.write_text(json.dumps(old), encoding="utf-8")
    state = StateManager(path).load()
    assert state["schema_version"] == SCHEMA_VERSION
    assert state["download"]["last_downloaded_version"] == "1"
    assert state["distribution"] == {"versions": {}}
    assert not list(tmp_path.glob("state.json.corrupt-*"))


def test_schema_two_migration_preserves_distribution_success(tmp_path):
    path = tmp_path / "state.json"
    old = {
        "schema_version": 2,
        "remote": {},
        "observed": {},
        "notification": {},
        "download": {},
        "distribution": {"versions": {"1": {"targets": {"123": {"status": "success"}}}}},
        "last_extracted_version": None,
    }
    path.write_text(json.dumps(old), encoding="utf-8")
    state = StateManager(path).load()
    assert state["schema_version"] == SCHEMA_VERSION
    assert state["distribution"]["versions"]["1"]["targets"]["123"]["status"] == "success"
    assert state["verification"] == {}
