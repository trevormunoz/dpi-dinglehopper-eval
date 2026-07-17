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
# Temporary venv for pip download (pip 24.3.1 requires an active virtualenv);
# call pip by explicit path — bin/ on POSIX, Scripts/ on Windows (Git Bash).
TMPVENV=$(mktemp -d)
"$PY" -m venv "$TMPVENV"
if [ -x "$TMPVENV/bin/pip" ]; then VPIP="$TMPVENV/bin/pip"; else VPIP="$TMPVENV/Scripts/pip.exe"; fi
if [ "$MODE" = "--probe" ]; then
  "$VPIP" download --only-binary :all: fastapi uvicorn python-multipart lxml -d "$OUT" >/dev/null
else
  (cd "$REPO_ROOT" && uv export --no-dev --no-emit-project --format requirements-txt) > "$OUT/requirements.txt"
  "$VPIP" download --only-binary :all: -r "$OUT/requirements.txt" -d "$OUT" >/dev/null
fi
rm -rf "$TMPVENV"
PKG="dpi-dinglehopper-eval"
# shasum (Perl, macOS/Linux) vs sha256sum (GNU coreutils, Git Bash on Windows).
if command -v shasum >/dev/null 2>&1; then SHA="shasum -a 256"
else SHA="sha256sum"; fi
HASH=$(ls "$OUT" | sort | $SHA | cut -d' ' -f1)
printf '%s\n%s\n' "$PKG" "$HASH" > "$OUT/MANIFEST"
if [ "$MODE" = "--probe" ]; then echo probe >> "$OUT/MANIFEST"; fi
echo "wheelhouse ($MODE): $(ls "$OUT" | wc -l | tr -d ' ') files"
