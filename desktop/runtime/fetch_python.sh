#!/usr/bin/env bash
# Fetch pinned python-build-standalone for the current platform into payload/cpython.
set -euo pipefail
cd "$(dirname "$0")"
VERSION=$(cat python-version.txt)
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) TRIPLE="aarch64-apple-darwin" ;;
  Linux-x86_64) TRIPLE="x86_64-unknown-linux-gnu" ;;
  MINGW*|MSYS*|CYGWIN*) TRIPLE="x86_64-pc-windows-msvc" ;;
  *) echo "unsupported platform" >&2; exit 1 ;;
esac
TAG="${VERSION#cpython-}"; TAG="${TAG#*+}"
PYVER="${VERSION#cpython-}"; PYVER="${PYVER%%+*}"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${TAG}/cpython-${PYVER}+${TAG}-${TRIPLE}-install_only.tar.gz"
mkdir -p payload
rm -rf payload/cpython
curl -fL "$URL" -o payload/python.tar.gz
tar -xzf payload/python.tar.gz -C payload
mv payload/python payload/cpython
rm payload/python.tar.gz
echo "fetched $VERSION for $TRIPLE"
