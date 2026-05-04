"""Regression tests for bibliography line splitting / glue heuristics."""

from __future__ import annotations

from bib_ocr.stages.ref_section import _split_ref_entries


def test_ssrn_concatenated_preprint_splits_before_next_surname_year() -> None:
    block = (
        "Bastani, Hamsa and Gerard P Cachon (2025), … SSRN preprint 5962739. "
        "Ben-Porath, Yoram (1967), “The production of human capital ….”"
    )
    entries = _split_ref_entries(block)
    texts = "\n".join(entries)
    assert "Ben-Porath, Yoram" in texts


def test_diacritic_surname_splits_across_wrapped_journal_line() -> None:
    block = (
        "Gibbons, Robert … The Quarterly Journal of Economics, 114, 1321–1358.\n"
        "Holmstr¨om, Bengt (1979), “Moral hazard…”The Bell Journal of Economics …\n"
        "Holmstrom, Bengt and Paul Milgrom (1991), …"
    )
    ents = _split_ref_entries(block)
    assert any("Holmstr" in e and "(1979)" in e for e in ents)


def test_initials_inside_author_list_are_not_fragmented_by_glue_regex() -> None:
    chunk = (
        "Monteiro, S., J. Sherbino, A. LoGiudice, M. Lee, G. Norman, and "
        "M. Sibbald (2024), … Medical Education, 58, 858–868.\n"
        "Natali, C., … (2025), … Review, 58.\nNi, Xiao, … (2024), …"
    )
    entries = _split_ref_entries(chunk)
    assert entries and entries[0].startswith("Monteiro, ")
    assert any("Natali" in e for e in entries)

