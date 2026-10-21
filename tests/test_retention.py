import os

import pytest

from arcaea_pull.utils.retention import cleanup_old_apks, validate_retention_count


def apk(directory, version, timestamp):
    path = directory / f"arcaea_{version}.apk"
    path.write_bytes(b"fixture")
    os.utime(path, (timestamp, timestamp))
    return path


def test_retention_orders_by_recorded_time_and_protects_current(tmp_path):
    oldest = apk(tmp_path, "99c", 400)
    recent = apk(tmp_path, "alpha", 200)
    current = apk(tmp_path, "current", 1)
    removed = cleanup_old_apks(
        tmp_path, current, old_versions_to_keep=1, timestamps={oldest.resolve(): 100},
    )
    assert removed == (oldest,)
    assert recent.is_file() and current.is_file()


def test_cleanup_preserves_unrelated_partial_and_nested_files(tmp_path):
    current = apk(tmp_path, "current", 1)
    old = apk(tmp_path, "old", 2)
    unrelated = tmp_path / "personal.apk"
    partial = tmp_path / "arcaea_incomplete.apk.part"
    nested = tmp_path / "nested"
    nested.mkdir()
    child = apk(nested, "old", 2)
    unrelated.write_bytes(b"personal")
    partial.write_bytes(b"partial")
    assert cleanup_old_apks(tmp_path, current, old_versions_to_keep=0) == (old,)
    assert all(path.is_file() for path in [current, unrelated, partial, child])


def test_cleanup_does_nothing_without_current_in_managed_directory(tmp_path):
    directory = tmp_path / "managed"
    directory.mkdir()
    old = apk(directory, "old", 1)
    external = apk(tmp_path, "current", 2)
    assert not cleanup_old_apks(directory, external, old_versions_to_keep=0)
    assert not cleanup_old_apks(directory, directory / "missing.apk", old_versions_to_keep=0)
    assert old.is_file()


def test_cleanup_never_follows_symlinked_files_or_directory(tmp_path):
    directory = tmp_path / "managed"
    directory.mkdir()
    current = apk(directory, "current", 1)
    external = apk(tmp_path, "outside", 2)
    link = directory / "arcaea_link.apk"
    loop = directory / "arcaea_loop.apk"
    linked_dir = tmp_path / "linked"
    try:
        link.symlink_to(external)
        loop.symlink_to(loop)
        linked_dir.symlink_to(directory, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable on this test host")
    assert not cleanup_old_apks(directory, current, old_versions_to_keep=0)
    assert external.is_file() and link.is_symlink()
    assert loop.is_symlink()
    old = apk(directory, "old", 3)
    assert not cleanup_old_apks(linked_dir, current, old_versions_to_keep=0)
    assert old.is_file()


@pytest.mark.parametrize("invalid", [True, -1, 21, 1.5, "2", None])
def test_invalid_retention_counts_are_rejected_before_any_deletion(invalid):
    with pytest.raises(ValueError, match="old_versions_to_keep"):
        validate_retention_count(invalid)
