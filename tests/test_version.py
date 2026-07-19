"""Package version must match pyproject.toml (pip metadata vs runtime)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import bib_ocr


def test_version_matches_pyproject() -> None:
    data = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert bib_ocr.__version__ == data["project"]["version"]
