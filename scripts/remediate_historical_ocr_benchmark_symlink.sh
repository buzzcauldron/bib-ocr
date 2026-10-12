#!/usr/bin/env bash
# Fix historical-ocr blacknews_latest symlink + benchmark_dual_targets.sh (idempotent).
#
# Applies contrib/historical-ocr-blacknews-latest.patch when git apply works,
# otherwise falls back to inline fixes.
#
# Usage:
#   HISTORICAL_OCR_ROOT=../historical-ocr bash scripts/remediate_historical_ocr_benchmark_symlink.sh
#   bash scripts/remediate_historical_ocr_benchmark_symlink.sh --dry-run
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PATCH="$REPO/contrib/historical-ocr-blacknews-latest.patch"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

_resolve_hist() {
  if [[ -n "${HISTORICAL_OCR_ROOT:-}" && -d "${HISTORICAL_OCR_ROOT}/.git" ]]; then
    echo "${HISTORICAL_OCR_ROOT}"
    return
  fi
  for cand in \
    "$REPO/../historical-ocr" \
    "$REPO/../historical ocr"; do
    if [[ -d "$cand/.git" ]]; then
      echo "$cand"
      return
    fi
  done
  echo "error: set HISTORICAL_OCR_ROOT to a historical-ocr git checkout" >&2
  exit 1
}

HIST="$(_resolve_hist)"
cd "$HIST"

BN="data/benchmarks/blacknews_latest"
needs=0
if [[ -L "$BN" ]]; then
  target="$(readlink "$BN")"
  [[ "$target" == /* ]] && needs=1
fi
if grep -q 'ln -sfn "\$OUT" "\${BENCH_DIR}/blacknews_latest"' scripts/benchmark_dual_targets.sh 2>/dev/null; then
  needs=1
fi

if [[ "$needs" -eq 0 ]]; then
  echo "[remediate] historical-ocr benchmark symlink already OK at $HIST"
  exit 0
fi

echo "[remediate] fixing historical-ocr at $HIST"
if [[ "$DRY" -eq 1 ]]; then
  echo "[dry-run] would apply blacknews_latest + benchmark_dual_targets.sh fix"
  exit 0
fi

if [[ -f "$PATCH" ]] && git apply --check "$PATCH" 2>/dev/null; then
  git apply "$PATCH"
  echo "[remediate] applied $PATCH"
  exit 0
fi

# Inline fallback (matches contrib patch)
stamp_dir="blacknews_20260611T134944Z"
if [[ -d "data/benchmarks/$stamp_dir" ]]; then
  rm -f "$BN"
  ln -sfn "$stamp_dir" "$BN"
fi
sed -i 's|ln -sfn "\$OUT" "\${BENCH_DIR}/blacknews_latest"|(cd "${BENCH_DIR}" \&\& ln -sfn "blacknews_${STAMP}" blacknews_latest)|' \
  scripts/benchmark_dual_targets.sh
echo "[remediate] inline fix applied (commit and push from historical-ocr repo)"
