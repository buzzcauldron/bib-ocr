"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import extract


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Extract bibliography citations from a PDF.")
    p.add_argument("pdf", help="Path to input PDF")
    p.add_argument("--min-hits", type=int, default=8,
                   help="Min DOI/citation hits before skipping remaining stages (default: 8)")
    p.add_argument(
        "--max-stage",
        type=int,
        default=5,
        choices=[1, 2, 3, 4, 5],
        help="Stop after this stage number 1–5 (default: 5)",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--output", "-o", default="-",
                   help="Output path for JSON results (default: stdout)")
    p.add_argument("--density-map", metavar="PNG",
                   help="Save a reference-density heat map to this PNG path (requires matplotlib)")
    args = p.parse_args(argv)

    if args.density_map:
        try:
            from bib_ocr import page_density, render_heatmap  # type: ignore[import]
        except ImportError:
            from .density import page_density, render_heatmap  # type: ignore[import]
        dm = page_density(args.pdf)
        render_heatmap(dm, args.density_map, title=Path(args.pdf).name)
        if args.verbose:
            print(f"Density map written to {args.density_map}", file=sys.stderr)
        if args.output == "-" and not sys.stdin.isatty():
            return  # density-only mode if no explicit --output

    result = extract(args.pdf, min_hits=args.min_hits, max_stage=args.max_stage, verbose=args.verbose)

    out = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output == "-":
        print(out)
    else:
        Path(args.output).write_text(out, encoding="utf-8")
        if args.verbose:
            print(f"Written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
