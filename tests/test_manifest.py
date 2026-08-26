import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_metadata_matches_release_identity():
    metadata = yaml.safe_load((ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    assert metadata["name"] == "astrbot_plugin_arcaea_pull"
    assert metadata["version"] == "0.2.3"
    assert metadata["author"] == "i5-10500"
    assert metadata["repo"].startswith("https://github.com/")
    assert metadata["support_platforms"] == ["aiocqhttp"]
    assert "i5-10500" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert '"i5-10500"' in (ROOT / "main.py").read_text(encoding="utf-8")
    project_metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license = "AGPL-3.0-or-later"' in project_metadata
    assert 'authors = [{ name = "i5-10500" }]' in project_metadata


def test_configuration_schema_has_safe_defaults_and_separate_allowlists():
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    assert schema["auto_download"]["default"] is False
    assert schema["auto_flash_transfer"]["default"] is False
    assert schema["notify_targets"]["default"] == []
    assert schema["flash_transfer_targets"]["default"] == []
    assert schema["notify_targets"] is not schema["flash_transfer_targets"]
    assert schema["check_interval_minutes"]["default"] == 30
    assert schema["check_interval_minutes"]["slider"] == {
        "min": 1,
        "max": 1440,
        "step": 1,
    }
    assert "check_interval_seconds" not in schema
    assert "check_time" not in schema
    assert schema["extra_check_times"]["default"] == []
    assert schema["download_connect_timeout"]["default"] == 30
    assert schema["download_read_timeout"]["default"] == 120
