import zipfile

from scripts.build_release import ARCHIVE, REQUIRED_ROOT_FILES, build


def test_release_archive_contains_runtime_files_only():
    build()
    with zipfile.ZipFile(ARCHIVE) as archive:
        names = set(archive.namelist())
    assert set(REQUIRED_ROOT_FILES) <= names
    assert any(name.startswith("arcaea_pull/") for name in names)
    assert not any(name.startswith("tests/") for name in names)
    assert not any(name.endswith((".apk", ".part")) for name in names)

