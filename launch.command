#!/bin/bash
set -euo pipefail

# Show a friendly error instead of leaving the user with a cryptic shell failure.
on_error() {
  local exit_code=$?
  echo
  echo "Meowdoku Companion could not start."
  echo "Setup stopped because a required command failed."
  echo "Please review the message above, then try launching again."
  exit "$exit_code"
}
trap on_error ERR

# Always run from the project root, even when launched by double-clicking in Finder.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Find a Python 3.11+ interpreter without changing the system Python.
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 or newer is required to run Meowdoku Companion."
  echo
  echo "Install Python 3.11+ from https://www.python.org/downloads/macos/"
  echo "or with Homebrew:"
  echo "  brew install python@3.12"
  echo
  echo "Then double-click launch.command again."
  exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)'; then
  echo "The python3 on your PATH is older than Python 3.11."
  echo
  echo "Install Python 3.11+ from https://www.python.org/downloads/macos/"
  echo "or with Homebrew:"
  echo "  brew install python@3.12"
  echo
  echo "Then make sure that newer python3 is on your PATH and relaunch."
  exit 1
fi

PYTHON_BIN="$(command -v python3)"
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python3"
STAMP_FILE="$VENV_DIR/.requirements.sha256"

# Create the local virtual environment only when it is missing.
venv_created=0
if [[ ! -x "$VENV_PYTHON" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  venv_created=1
fi

# Install dependencies only after first setup or when requirements.txt changes.
requirements_sha="$(shasum -a 256 requirements.txt | awk '{print $1}')"
installed_sha=""
if [[ -f "$STAMP_FILE" ]]; then
  installed_sha="$(cat "$STAMP_FILE")"
fi

if [[ "$venv_created" -eq 1 || ! -f "$STAMP_FILE" || "$requirements_sha" != "$installed_sha" ]]; then
  if ! "$VENV_PYTHON" -m pip install --upgrade pip; then
    echo
    echo "Could not update pip for Meowdoku Companion."
    echo "Internet access is required for first-time setup only."
    echo "After setup succeeds once, normal launches can work offline."
    exit 1
  fi

  if ! "$VENV_PYTHON" -m pip install -r requirements.txt; then
    echo
    echo "Could not install Meowdoku Companion dependencies."
    echo "Internet access is required for first-time setup only."
    echo "After setup succeeds once, normal launches can work offline."
    exit 1
  fi

  echo "$requirements_sha" > "$STAMP_FILE"
fi

# Replace this shell with the app process.
exec "$VENV_PYTHON" -m meowdoku.app "$@"
