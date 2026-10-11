#!/usr/bin/env bash
# Local health check for Bridges / historical-OCR training stack (cron-friendly).
#
# Usage:
#   bash scripts/bridges_training_health_check.sh
#   HISTORICAL_OCR_ROOT=/path/to/historical-ocr bash scripts/bridges_training_health_check.sh
#
# Exit codes:
#   0  bib-ocr tests pass and historical-ocr checks pass (or skipped)
#   1  bib-ocr and/or historical-ocr issues found
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

failures=0
note() { echo "[bridges-check] $*"; }
fail() { note "FAIL: $*"; failures=$((failures + 1)); }
ok() { note "OK: $*"; }

note "bib-ocr pytest"
if ! python3 -c "import pytest" 2>/dev/null; then
  note "installing bib-ocr dev deps (pytest missing)"
  pip install -e ".[dev]" -q
fi
if ! python3 -m pytest -q; then
  fail "bib-ocr pytest"
else
  ok "bib-ocr pytest"
fi

_resolve_hist() {
  if [[ -n "${HISTORICAL_OCR_ROOT:-}" && -d "${HISTORICAL_OCR_ROOT}/scripts" ]]; then
    echo "${HISTORICAL_OCR_ROOT}"
    return
  fi
  for cand in \
    "$REPO/../historical-ocr" \
    "$REPO/../historical ocr" \
    "$HOME/Projects/historical-ocr" \
    "$HOME/Projects/historical ocr"; do
    if [[ -d "$cand/scripts" ]]; then
      echo "$cand"
      return
    fi
  done
  return 1
}

HIST=""
if HIST="$(_resolve_hist)"; then
  note "historical-ocr root: $HIST"
else
  note "historical-ocr not found locally — fresh shallow clone for script/symlink checks"
  HIST="$(mktemp -d "${TMPDIR:-/tmp}/historical-ocr-bridges-check.XXXXXX")"
  trap 'rm -rf "$HIST"' EXIT
  git clone --depth 1 https://github.com/buzzcauldron/historical-ocr.git "$HIST"
fi

for f in "$HIST"/scripts/bridges_* "$HIST"/scripts/submit_bridges_*; do
  [[ -f "$f" ]] || continue
  if bash -n "$f"; then
    ok "$(basename "$f") syntax"
  else
    fail "$(basename "$f") bash -n"
  fi
done

BN="$HIST/data/benchmarks/blacknews_latest"
if [[ -L "$BN" ]]; then
  target="$(readlink "$BN")"
  if [[ "$target" == /* ]]; then
    fail "blacknews_latest is absolute ($target) — breaks Linux/Bridges clones"
    note "HINT: bash scripts/remediate_historical_ocr_benchmark_symlink.sh"
  else
    ok "blacknews_latest → $target"
  fi
elif [[ -e "$BN" ]]; then
  ok "blacknews_latest present"
else
  note "WARN: blacknews_latest missing (benchmark only)"
fi

if [[ "$failures" -gt 0 ]]; then
  note "$failures issue(s) — see above"
  exit 1
fi
note "all checks passed"
exit 0
