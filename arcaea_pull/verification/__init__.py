"""Fail-closed APK authenticity verification."""

from typing import TYPE_CHECKING

from .apksigner_backend import ApkSignerBackend, normalize_fingerprint
from .manifest_inspector import ApkManifestInspector

if TYPE_CHECKING:
    from .verifier import AuthenticityVerifier

__all__ = [
    "ApkManifestInspector",
    "ApkSignerBackend",
    "AuthenticityVerifier",
    "normalize_fingerprint",
]


def __getattr__(name: str):
    # Standalone Build Tools inspection must not require the AstrBot runtime.
    if name == "AuthenticityVerifier":
        from .verifier import AuthenticityVerifier

        return AuthenticityVerifier
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
