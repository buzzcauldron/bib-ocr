"""Packaging metadata must match the runtime __version__."""

from __future__ import annotations

from pathlib import Path

import bib_ocr


def test_pyproject_version_matches_package() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            quoted = line.split("=", 1)[1].strip().strip('"')
            assert quoted == bib_ocr.__version__
            return
    raise AssertionError("version not found in pyproject.toml")
