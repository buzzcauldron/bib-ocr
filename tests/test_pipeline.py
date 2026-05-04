"""Unit tests for ``bib_ocr.pipeline.extract`` orchestration (mocked stages)."""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture
def tiny_pdf(tmp_path):
    p = tmp_path / "paper.pdf"
    p.write_bytes(b"%PDF-1.1\n%\xe2\xe3\xcf\xd3\n")
    return p


def test_extract_short_circuits_when_min_hits_met(monkeypatch, tiny_pdf):
    import bib_ocr.stages.doi_scan as doi_scan
    import bib_ocr.stages.link_crawl as link_crawl

    def doi_extract(pdf_path, **kwargs):
        return [
            {"doi": "10.1000/1", "stage": "doi_scan"},
            {"doi": "10.1000/2", "stage": "doi_scan"},
            {"doi": "10.1000/3", "stage": "doi_scan"},
        ]

    def link_extract_always_runs(*_a, **_k):
        return []  # no extra dois from annotations; doi_scan alone already meets min_hits

    monkeypatch.setattr(doi_scan, "extract", doi_extract)
    monkeypatch.setattr(link_crawl, "extract", link_extract_always_runs)

    from bib_ocr.pipeline import extract

    out = extract(tiny_pdf, min_hits=3, max_stage=5, verbose=False)
    assert out["stages_run"] == ["doi_scan", "link_crawl"]
    assert len(out["citations"]) == 3
    assert "pdf" in out


def test_early_stages_combine_dois_before_short_circuit(monkeypatch, tiny_pdf):
    import bib_ocr.stages.doi_scan as doi_scan
    import bib_ocr.stages.link_crawl as link_crawl
    import bib_ocr.stages.ref_section as ref_section

    monkeypatch.setattr(
        doi_scan,
        "extract",
        lambda pdf_path, **k: [
            {"doi": "10.1000/a", "stage": "doi_scan"},
            {"doi": "10.1000/b", "stage": "doi_scan"},
        ],
    )

    monkeypatch.setattr(
        link_crawl,
        "extract",
        lambda pdf_path, **kw: [{"doi": "10.1000/c", "stage": "link_crawl", "page": 0, "url": "x"}],
    )

    def ref_must_not_run(*_a, **_k):
        raise AssertionError("ref_section should not run — min_hits met after dois 1–2 combined")

    monkeypatch.setattr(ref_section, "extract", ref_must_not_run)

    from bib_ocr.pipeline import extract

    out = extract(tiny_pdf, min_hits=3, max_stage=5, verbose=False)
    assert out["stages_run"] == ["doi_scan", "link_crawl"]
    assert len({c["doi"] for c in out["citations"] if c.get("doi")}) == 3


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

    out = extract(tiny_pdf, min_hits=99, max_stage=1, verbose=False)
    assert out["stages_run"] == ["doi_scan"]
    assert len(out["citations"]) == 1


def test_ref_section_end_exclusive_stops_when_heatmap_totals_drop() -> None:
    from bib_ocr.density import ref_section_end_exclusive

    dm = np.zeros((40, 10), dtype=np.float32)
    dm[25:29, :] = 5.0
    dm[29:, :] = 0.0
    assert ref_section_end_exclusive(dm, 25) == 29


def test_result_shape(monkeypatch, tiny_pdf):
    import bib_ocr.stages.doi_scan as doi_scan

    monkeypatch.setattr(
        doi_scan,
        "extract",
        lambda pdf_path, **k: [{"doi": "10.1000/182", "stage": "doi_scan"}],
    )
    from bib_ocr import extract

    out = extract(tiny_pdf, min_hits=1, max_stage=1, verbose=False)
    assert set(out.keys()) == {"citations", "stages_run", "pdf"}
    assert isinstance(out["citations"], list)
    assert isinstance(out["stages_run"], list)
    assert out["pdf"].endswith("paper.pdf")
