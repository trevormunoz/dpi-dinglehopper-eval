#!/usr/bin/env bash
# Build the offline wheelhouse (wheels only). --probe = this repo's wheel +
# the minimal web deps (fastapi/uvicorn/python-multipart/lxml — lxml because
# dpi_eval.adapter imports it at module scope), minus dinglehopper.
set -euo pipefail
cd "$(dirname "$0")"
REPO_ROOT="$(cd ../.. && pwd)"
MODE="${1:-full}"
OUT="payload/wheelhouse"
if [ -x payload/cpython/bin/python3 ]; then PY=payload/cpython/bin/python3
elif [ -x payload/cpython/python.exe ]; then PY=payload/cpython/python.exe
else echo "run fetch_python.sh first" >&2; exit 1; fi
rm -rf "$OUT"; mkdir -p "$OUT"
(cd "$REPO_ROOT" && uv build --wheel --out-dir "$PWD/desktop/runtime/$OUT")
if [ "$MODE" = "--probe" ]; then
  # Create temporary venv for pip download (pip 24.3.1 requires virtualenv)
  TMPVENV=$(mktemp -d)
  "$PY" -m venv "$TMPVENV"
  . "$TMPVENV/bin/activate"
  pip download --only-binary :all: fastapi uvicorn python-multipart lxml -d "$OUT" >/dev/null
  deactivate
  rm -rf "$TMPVENV"
else
  (cd "$REPO_ROOT" && uv export --no-dev --no-emit-project --format requirements-txt) > "$OUT/requirements.txt"
  # Create temporary venv for pip download (pip 24.3.1 requires virtualenv)
  TMPVENV=$(mktemp -d)
  "$PY" -m venv "$TMPVENV"
  . "$TMPVENV/bin/activate"
  pip download --only-binary :all: -r "$OUT/requirements.txt" -d "$OUT" >/dev/null
  deactivate
  rm -rf "$TMPVENV"
fi
PKG="dpi-dinglehopper-eval"
HASH=$(ls "$OUT" | sort | shasum -a 256 | cut -d' ' -f1)
printf '%s\n%s\n' "$PKG" "$HASH" > "$OUT/MANIFEST"
if [ "$MODE" = "--probe" ]; then echo probe >> "$OUT/MANIFEST"; fi
echo "wheelhouse ($MODE): $(ls "$OUT" | wc -l | tr -d ' ') files"
