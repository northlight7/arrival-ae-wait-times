#!/bin/bash
# LAUNCHER.sh — start Arrival on macOS or Linux.
#
# Works identically on Apple Silicon and Intel Macs. Everything it installs
# lives inside this folder, so deleting the folder removes every trace.
# No administrator password, no system Python, no Node.
#
# Windows users: double-click LAUNCHER.bat instead.

cd "$(dirname "$0")"
ROOT="$(pwd)"
UV_DIR="$ROOT/.uv"
UV_BIN="$UV_DIR/uv"
PORT=8094

# Keep every byte uv writes inside this folder. Left alone, uv caches packages
# and downloaded Pythons in shared per-user directories that survive deleting
# this folder and can reach hundreds of megabytes.
export UV_CACHE_DIR="$ROOT/.uv-cache"
export UV_PYTHON_INSTALL_DIR="$ROOT/.uv-python"
export UV_PYTHON_CACHE_DIR="$ROOT/.uv-cache/python"
export UV_PYTHON_BIN_DIR="$ROOT/.uv-python/bin"
export UV_TOOL_DIR="$ROOT/.uv-tools"
export UV_TOOL_BIN_DIR="$ROOT/.uv-tools/bin"

say()  { echo "  $*"; }
fail() { echo; say "$1"; echo; read -r -p "Press Enter to close..."; exit 1; }

echo
say "Arrival — honest A&E waits for Hong Kong"
say "$(uname -s) $(uname -m)"
echo

# 1. uv: a single binary that can download its own Python.
if [ -x "$UV_BIN" ]; then
    UV="$UV_BIN"
elif command -v uv >/dev/null 2>&1; then
    UV="$(command -v uv)"
else
    say "First run — setting up. Needs internet; only happens once."
    echo
    say "Step 1 of 3: downloading the setup tool..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh \
            | env UV_UNMANAGED_INSTALL="$UV_DIR" sh >/dev/null 2>&1
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh \
            | env UV_UNMANAGED_INSTALL="$UV_DIR" sh >/dev/null 2>&1
    else
        fail "This computer has neither curl nor wget, so nothing can be downloaded."
    fi
    [ -x "$UV_BIN" ] || fail "The setup tool did not download. Check your internet connection and try again."
    UV="$UV_BIN"
fi

cd engine || fail "The 'engine' folder is missing. Extract the whole download, not just the launcher."

# 2. Python + Flask. Nothing here is compiled for this project's own code, and
#    Flask's one binary dependency (MarkupSafe's optional C speedup) falls back
#    to pure Python wherever no wheel matches — so `uv sync` resolves correctly
#    on Apple Silicon, Intel Mac, x86 Windows and ARM Windows alike.
say "Step 2 of 3: installing Python and Flask..."
if ! "$UV" sync --quiet; then
    say "That did not work. Rebuilding from scratch..."
    rm -rf .venv
    "$UV" sync --quiet || fail "Could not install Python or Flask. Check your internet connection and try again."
fi

# 3. Confirm the data is present before promising a working page.
if [ ! -f "$ROOT/data/ae_corpus.json" ] && [ ! -f "$ROOT/data/ae_corpus.json.gz" ]; then
    fail "The historical data file is missing from the 'data' folder. Re-extract the download."
fi

# 3b. And the built page. Without this the server starts happily and serves a
#     blank window — the worst failure mode, because it looks like the app is
#     working and simply has nothing to say.
if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
    fail "The built page is missing from 'frontend/dist'. Re-extract the download, or run 'npm install && npm run build' in the frontend folder."
fi

say "Step 3 of 3: starting up..."
echo
say "Opening http://localhost:$PORT"
say "Leave this window open. Closing it stops Arrival."
echo

# Open the browser once the server is actually answering.
( for _ in $(seq 1 60); do
    if curl -s -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
      command -v open >/dev/null 2>&1 && open "http://localhost:$PORT" \
        || command -v xdg-open >/dev/null 2>&1 && xdg-open "http://localhost:$PORT" >/dev/null 2>&1
      break
    fi
    sleep 1
  done ) &

"$UV" run python server.py $PORT
EXIT=$?

if [ $EXIT -ne 0 ] && [ $EXIT -ne 130 ]; then
    echo
    echo "Arrival closed with an error (code $EXIT)."
    read -r -p "Press Enter to close..."
fi
exit $EXIT
