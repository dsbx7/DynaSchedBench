"""dsbx: dynamic scheduling benchmark and simulation toolkit."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:  # pragma: no cover - defensive
    __version__ = version("dsbx")
except PackageNotFoundError:  # pragma: no cover - during editable installs
    __version__ = "0.0.0"
