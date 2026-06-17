"""Ensure package version is consistent across metadata sources."""

from __future__ import annotations

import tomllib
from pathlib import Path

import bib_ocr


def test_version_matches_pyproject() -> None:
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads(root.joinpath("pyproject.toml").read_text(encoding="utf-8"))
    assert bib_ocr.__version__ == data["project"]["version"]
