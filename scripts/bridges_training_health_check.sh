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
#
# Env:
#   BRIDGES_CHECK_ALLOW_ABSOLUTE_BLACKNEWS=1  warn only when upstream blacknews_latest
#                                            is still an absolute path (default: fail)
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
hist_ephemeral=0
if HIST="$(_resolve_hist)"; then
  note "historical-ocr root: $HIST"
else
  note "historical-ocr not found locally — fresh shallow clone for script/symlink checks"
  HIST="$(mktemp -d "${TMPDIR:-/tmp}/historical-ocr-bridges-check.XXXXXX")"
  hist_ephemeral=1
  trap 'rm -rf "$HIST"' EXIT
  git clone --depth 1 https://github.com/buzzcauldron/historical-ocr.git "$HIST"
fi

PATCH="$REPO/contrib/historical-ocr-blacknews-latest.patch"
patch_applies=0
if [[ -f "$PATCH" ]] && git -C "$HIST" apply --check "$PATCH" 2>/dev/null; then
  patch_applies=1
fi

# Ephemeral clone: apply the portable blacknews_latest fix so bash -n and symlink
# checks exercise the post-patch tree (upstream main may still be absolute until merged).
if [[ "$hist_ephemeral" -eq 1 ]] && [[ "$patch_applies" -eq 1 ]]; then
  git -C "$HIST" apply "$PATCH"
  note "applied contrib patch to ephemeral historical-ocr clone (portable benchmark symlink)"
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
    if [[ "$patch_applies" -eq 1 ]]; then
      note "WARN: blacknews_latest still absolute in this checkout ($target)"
      note "HINT: apply contrib/historical-ocr-blacknews-latest.patch on historical-ocr main"
      note "      or: HISTORICAL_OCR_ROOT=/path/to/historical-ocr bash scripts/remediate_historical_ocr_benchmark_symlink.sh"
      if [[ "$hist_ephemeral" -eq 1 ]]; then
        fail "ephemeral clone still has absolute blacknews_latest after contrib patch"
      elif [[ "${BRIDGES_CHECK_ALLOW_ABSOLUTE_BLACKNEWS:-}" == "1" ]]; then
        ok "contrib patch applies cleanly (BRIDGES_CHECK_ALLOW_ABSOLUTE_BLACKNEWS=1 — warn only)"
      else
        fail "blacknews_latest still absolute; remediate local historical-ocr or merge contrib patch"
      fi
    else
      fail "blacknews_latest is absolute ($target) — breaks Linux/Bridges clones (contrib patch does not apply)"
      note "HINT: HISTORICAL_OCR_ROOT=/path/to/historical-ocr bash scripts/remediate_historical_ocr_benchmark_symlink.sh"
    fi
  else
    ok "blacknews_latest → $target"
  fi
elif [[ -e "$BN" ]]; then
  ok "blacknews_latest present"
else
  note "WARN: blacknews_latest missing (benchmark only)"
fi

_check_upstream_blacknews() {
  local raw url target
  url="https://raw.githubusercontent.com/buzzcauldron/historical-ocr/main/data/benchmarks/blacknews_latest"
  note "upstream historical-ocr main: blacknews_latest"
  if ! raw="$(curl -fsSL --max-time 30 "$url" 2>/dev/null)"; then
    note "WARN: could not fetch upstream blacknews_latest ($url)"
    return 0
  fi
  target="$(printf '%s' "$raw" | tr -d '\r\n')"
  if [[ -z "$target" ]]; then
    note "WARN: upstream blacknews_latest empty"
    return 0
  fi
  if [[ "$target" == /* ]]; then
    note "upstream target is absolute ($target)"
    note "HINT: merge contrib/historical-ocr-blacknews-latest.patch on historical-ocr main"
    if [[ "${BRIDGES_CHECK_ALLOW_ABSOLUTE_BLACKNEWS:-}" == "1" ]]; then
      ok "upstream still absolute (BRIDGES_CHECK_ALLOW_ABSOLUTE_BLACKNEWS=1 — warn only)"
    elif [[ "$patch_applies" -eq 1 ]]; then
      note "WARN: upstream historical-ocr main still has absolute blacknews_latest (merge contrib patch)"
      ok "contrib patch applies cleanly to upstream main — Bridges training tree is patch-verified"
    else
      fail "upstream blacknews_latest still absolute on GitHub main"
    fi
  else
    ok "upstream blacknews_latest → $target"
  fi
}

_check_upstream_blacknews

if [[ "$failures" -gt 0 ]]; then
  note "$failures issue(s) — see above"
  exit 1
fi
note "all checks passed"
exit 0
