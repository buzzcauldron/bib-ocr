"""Ensure package version is consistent across metadata sources."""

from __future__ import annotations

import tomllib
from pathlib import Path

import bib_ocr


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as f:
        declared = tomllib.load(f)["project"]["version"]
    assert bib_ocr.__version__ == declared
