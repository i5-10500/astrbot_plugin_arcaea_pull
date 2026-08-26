"""Build and verify the AstrBot installation archive."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
ARCHIVE = DIST / "astrbot_plugin_arcaea_pull-v0.2.3.zip"
REQUIRED_ROOT_FILES = (
    "main.py",
    "metadata.yaml",
    "_conf_schema.json",
    "requirements.txt",
    "README.md",
    "LICENSE",
)


def package_files() -> list[Path]:
    files = [ROOT / name for name in REQUIRED_ROOT_FILES]
    files.extend(sorted((ROOT / "arcaea_pull").rglob("*.py")))
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing package files: {', '.join(missing)}")
    return files


def build() -> str:
    DIST.mkdir(exist_ok=True)
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in package_files():
            archive.write(path, path.relative_to(ROOT).as_posix())

    with zipfile.ZipFile(ARCHIVE) as archive:
        names = set(archive.namelist())
        bad = [
            name
            for name in names
            if name.startswith(("tests/", ".git/", ".github/", "dist/"))
            or name.endswith((".apk", ".part"))
            or "__pycache__" in name
        ]
        missing = [name for name in REQUIRED_ROOT_FILES if name not in names]
        if bad or missing or archive.testzip() is not None:
            raise RuntimeError(f"archive verification failed: bad={bad}, missing={missing}")

    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    (DIST / "SHA256SUMS.txt").write_text(
        f"{digest}  {ARCHIVE.name}\n", encoding="utf-8"
    )
    return digest


if __name__ == "__main__":
    sha256 = build()
    print(f"Built: {ARCHIVE}")
    print(f"SHA-256: {sha256}")
