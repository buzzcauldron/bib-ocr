"""Unit tests for ``bib_ocr.pipeline.extract`` orchestration (mocked stages)."""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture
def tiny_pdf(tmp_path):
    p = tmp_path / "paper.pdf"
    p.write_bytes(b"%PDF-1.1\n%\xe2\xe3\xcf\xd3\n")
    return p


def test_extract_runs_ocr_stages_even_when_early_dois_plentiful(monkeypatch, tiny_pdf):
    """Pipeline no longer stops after doi/link — density + ref/footnote/inline still run."""

    import bib_ocr.stages.doi_scan as doi_scan
    import bib_ocr.stages.link_crawl as link_crawl
    import bib_ocr.stages.ref_section as ref_section
    import bib_ocr.stages.inline_crawl as inline_crawl
    import bib_ocr.density as density

    monkeypatch.setattr(
        doi_scan,
        "extract",
        lambda pdf_path, **k: [
            {"doi": "10.1000/1", "stage": "doi_scan"},
            {"doi": "10.1000/2", "stage": "doi_scan"},
            {"doi": "10.1000/3", "stage": "doi_scan"},
        ],
    )
    monkeypatch.setattr(link_crawl, "extract", lambda pdf_path, **kw: [])

    def ref_runs(_pdf_path, **_kw):
        return [{"text": "Smith 1900 refs", "stage": "ref_section"}]

    monkeypatch.setattr(ref_section, "extract", ref_runs)

    monkeypatch.setattr(
        density,
        "page_density",
        lambda _path: np.ones((5, 10), dtype=np.float32),
        raising=True,
    )
    monkeypatch.setattr(density, "target_pages", lambda _dm: [0])
    monkeypatch.setattr(density, "ref_section_start", lambda _dm: 0)

    monkeypatch.setattr(
        inline_crawl,
        "extract",
        lambda pdf_path: [{"text": "(Doe 2000)", "stage": "inline_crawl"}],
    )

    from bib_ocr.pipeline import extract as pipeline_extract

    out = pipeline_extract(tiny_pdf, max_stage=5, verbose=False)
    assert out["stages_run"] == [
        "doi_scan",
        "link_crawl",
        "ref_section",
        "footnote_scan",
        "inline_crawl",
    ]
    stages = [c["stage"] for c in out["citations"]]
    assert "ref_section" in stages
    assert "inline_crawl" in stages
    assert out["pdf"].endswith("paper.pdf")


def test_footnote_scan_falls_back_to_all_pages_when_density_hot_list_empty(monkeypatch, tiny_pdf):
    """Empty target_pages must not skip footnote OCR — fall back to scanning every page."""
    import bib_ocr.stages.doi_scan as doi_scan
    import bib_ocr.stages.link_crawl as link_crawl
    import bib_ocr.stages.ref_section as ref_section
    import bib_ocr.stages.footnote_scan as footnote_scan
    import bib_ocr.stages.inline_crawl as inline_crawl
    import bib_ocr.density as density

    monkeypatch.setattr(doi_scan, "extract", lambda pdf_path, **k: [])
    monkeypatch.setattr(link_crawl, "extract", lambda pdf_path, **kw: [])
    monkeypatch.setattr(ref_section, "extract", lambda pdf_path, **kw: [])

    seen: list = []

    def footnote_runs(_pdf_path, target_page_indices=None):
        seen.append(target_page_indices)
        return []

    monkeypatch.setattr(footnote_scan, "extract", footnote_runs)
    monkeypatch.setattr(inline_crawl, "extract", lambda pdf_path: [])

    monkeypatch.setattr(
        density,
        "page_density",
        lambda _path: np.zeros((5, 10), dtype=np.float32),
        raising=True,
    )
    monkeypatch.setattr(density, "target_pages", lambda _dm: [])
    monkeypatch.setattr(density, "ref_section_start", lambda _dm: 0)

    from bib_ocr.pipeline import extract as pipeline_extract

    pipeline_extract(tiny_pdf, max_stage=4, verbose=False)
    assert seen == [None]


def test_max_stage_skips_later_stages(monkeypatch, tiny_pdf):
    import bib_ocr.stages.doi_scan as doi_scan
    import bib_ocr.stages.link_crawl as link_crawl

    monkeypatch.setattr(
        doi_scan,
        "extract",
        lambda pdf_path, **k: [{"doi": "10.1000/1", "stage": "doi_scan"}],
    )

    def link_should_not_run(*_a, **_k):
        raise AssertionError("stage 2 blocked by max_stage=1")

    monkeypatch.setattr(link_crawl, "extract", link_should_not_run)

    from bib_ocr.pipeline import extract

    out = extract(tiny_pdf, max_stage=1, verbose=False)
    assert out["stages_run"] == ["doi_scan"]
    assert len(out["citations"]) == 1


def test_ref_section_end_exclusive_stops_when_heatmap_totals_drop() -> None:
    from bib_ocr.density import ref_section_end_exclusive

    dm = np.zeros((40, 10), dtype=np.float32)
    dm[25:29, :] = 5.0
    dm[29:, :] = 0.0
    assert ref_section_end_exclusive(dm, 25) == 29


def test_ref_section_end_exclusive_when_probe_pages_are_density_blind() -> None:
    """Dissertation-style bibliography: header page hot (+section boost); prose refs score 0."""
    from bib_ocr.density import ref_section_end_exclusive

    dm = np.zeros((50, 10), dtype=np.float32)
    dm[40, :] = 30.0  # Bibliography heading + opening lines only
    assert ref_section_end_exclusive(dm, 40) == 50


def test_result_shape(monkeypatch, tiny_pdf):
    import bib_ocr.stages.doi_scan as doi_scan

    monkeypatch.setattr(
        doi_scan,
        "extract",
        lambda pdf_path, **k: [{"doi": "10.1000/182", "stage": "doi_scan"}],
    )
    from bib_ocr import extract

    out = extract(tiny_pdf, max_stage=1, verbose=False)
    assert set(out.keys()) == {"citations", "stages_run", "pdf"}
    assert isinstance(out["citations"], list)
    assert isinstance(out["stages_run"], list)
    assert out["pdf"].endswith("paper.pdf")
