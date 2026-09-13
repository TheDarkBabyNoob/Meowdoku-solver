#!/usr/bin/env bash
# Build a native-looking macOS .app bundle for Meowdoku Companion.
#
# This script keeps the existing source launcher intact. It uses only the
# project-local virtual environment at .venv, installs build-only tooling there
# when needed, generates a local icon from original drawn shapes, and then asks
# PyInstaller to produce a Finder-launchable app bundle.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
APP_NAME="Meowdoku Companion"
DIST_APP="${PROJECT_ROOT}/dist/${APP_NAME}.app"
ROOT_APP="${PROJECT_ROOT}/${APP_NAME}.app"

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

run_step() {
  local description="$1"
  shift

  printf '\n%s\n' "$description"
  "$@" || die "${description} failed."
}

ensure_venv() {
  if [[ ! -d "${VENV_DIR}" ]]; then
    command -v python3 >/dev/null 2>&1 || die "python3 was not found; cannot create ${VENV_DIR}."
    run_step "Creating project virtual environment at ${VENV_DIR}..." \
      python3 -m venv "${VENV_DIR}"
    run_step "Installing Python requirements into the project virtual environment..." \
      "${VENV_PYTHON}" -m pip install -r "${PROJECT_ROOT}/requirements.txt"
  fi

  [[ -x "${VENV_PYTHON}" ]] || die "Virtual environment exists but ${VENV_PYTHON} is not executable."
}

ensure_python_package() {
  local package_name="$1"
  local import_name="$2"

  if ! "${VENV_PYTHON}" -m pip show "${package_name}" >/dev/null 2>&1; then
    run_step "Installing ${package_name} into the project virtual environment..." \
      "${VENV_PYTHON}" -m pip install "${package_name}"
  fi

  "${VENV_PYTHON}" -c "import ${import_name}" >/dev/null 2>&1 || \
    die "${package_name} could not be imported from the project virtual environment."
}

main() {
  cd "${PROJECT_ROOT}"

  ensure_venv
  ensure_python_package "pyinstaller" "PyInstaller"
  ensure_python_package "Pillow" "PIL"

  run_step "Generating the macOS app icon..." \
    "${VENV_PYTHON}" "${SCRIPT_DIR}/make_icon.py"

  run_step "Building ${APP_NAME}.app with PyInstaller..." \
    "${VENV_PYTHON}" -m PyInstaller \
      --windowed \
      --name "${APP_NAME}" \
      --icon packaging/AppIcon.icns \
      --osx-bundle-identifier com.meowdokucompanion.app \
      --noconfirm \
      --clean \
      meowdoku/app.py

  [[ -d "${DIST_APP}" ]] || die "PyInstaller completed, but ${DIST_APP} was not found."

  rm -rf "${ROOT_APP}"
  if command -v rsync >/dev/null 2>&1; then
    run_step "Copying ${APP_NAME}.app to the project root..." \
      rsync -a "${DIST_APP}" "${PROJECT_ROOT}/"
  else
    run_step "Copying ${APP_NAME}.app to the project root..." \
      cp -R "${DIST_APP}" "${PROJECT_ROOT}/"
  fi

  cat <<MESSAGE

Created:
  ${ROOT_APP}

You can double-click "${APP_NAME}.app" in Finder to launch the real app using
the bundled Python and Qt runtime. No network connection is needed at launch.

On first launch, macOS Gatekeeper will likely warn that "${APP_NAME}" cannot be
opened because the developer cannot be verified. This is expected for an
unsigned, non-notarized local build; no paid Apple Developer account was used
or required. Right-click or Control-click the app, choose Open, then confirm
Open in the dialog. You should only need to do that once.

When the packaged app first tries to capture the screen, macOS Screen Recording
permission must be granted specifically to "${APP_NAME}" under System Settings
> Privacy & Security > Screen Recording. This is different from running through
launch.command, where Terminal itself needs the permission, because macOS grants
Screen Recording permission per launching-process/binary identity rather than
per Python script.

MESSAGE
}

main "$@"
