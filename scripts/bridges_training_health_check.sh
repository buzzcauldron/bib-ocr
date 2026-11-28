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
#   BRIDGES_CHECK_STRICT_BLACKNEWS=1         fail while historical-ocr main still has an
#                                            absolute blacknews_latest (even if contrib
#                                            patch applies cleanly)
#   BRIDGES_CHECK_ALLOW_ABSOLUTE_BLACKNEWS=1 treat absolute blacknews_latest as warn-only
#                                            (including when contrib patch no longer applies)
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
  pip_ok=0
  for attempt in 1 2 3; do
    if pip install -e ".[dev]" -q; then
      pip_ok=1
      break
    fi
    note "pip install attempt $attempt failed — retrying"
    sleep 2
  done
  if [[ "$pip_ok" -ne 1 ]]; then
    fail "pip install -e '.[dev]'"
  fi
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

patch_verified=0
if [[ -f "$PATCH" ]] && git -C "$HIST" apply --check "$PATCH" 2>/dev/null; then
  patch_verified=1
fi

# Ephemeral clone: apply contrib patch when it still applies (legacy absolute symlinks on main).
if [[ "$hist_ephemeral" -eq 1 && "$patch_verified" -eq 1 ]]; then
  git -C "$HIST" apply "$PATCH"
  note "applied contrib patch to ephemeral historical-ocr clone (portable benchmark symlink)"
fi

_absolute_blacknews_ok() {
  if [[ "${BRIDGES_CHECK_ALLOW_ABSOLUTE_BLACKNEWS:-}" == "1" ]]; then
    ok "$1 (BRIDGES_CHECK_ALLOW_ABSOLUTE_BLACKNEWS=1 — warn only)"
    return 0
  fi
  if [[ "$patch_verified" -eq 1 && "${BRIDGES_CHECK_STRICT_BLACKNEWS:-}" != "1" ]]; then
    note "WARN: $1 — merge contrib/historical-ocr-blacknews-latest.patch on historical-ocr main"
    ok "contrib patch verified for historical-ocr main (pending upstream merge)"
    return 0
  fi
  if [[ "${BRIDGES_CHECK_STRICT_BLACKNEWS:-}" == "1" ]]; then
    note "HINT: merge contrib/historical-ocr-blacknews-latest.patch on historical-ocr main"
  fi
  return 1
}

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
    note "blacknews_latest is absolute ($target) — breaks Linux/Bridges clones"
    note "HINT: HISTORICAL_OCR_ROOT=/path/to/historical-ocr bash scripts/remediate_historical_ocr_benchmark_symlink.sh"
    if _absolute_blacknews_ok "checkout blacknews_latest still absolute"; then
      :
    else
      fail "blacknews_latest is absolute ($target) — contrib patch missing or does not apply"
    fi
  else
    ok "blacknews_latest → $target"
    # Remediated checkout (or ephemeral clone after apply): treat like patch_verified for upstream warn-only.
    patch_verified=1
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
    if _absolute_blacknews_ok "upstream blacknews_latest still absolute on GitHub main"; then
      :
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
