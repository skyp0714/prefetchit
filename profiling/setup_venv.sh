#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
REQ_FILE="${SCRIPT_DIR}/required_package.txt"

if [[ ! -f "${REQ_FILE}" ]]; then
  echo "[err] missing ${REQ_FILE}" >&2
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  if ! python3 -m venv "${VENV_DIR}" >/dev/null 2>&1; then
    echo "[err] failed to create venv. Install python3-venv first." >&2
    exit 1
  fi
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip >/dev/null
"${VENV_DIR}/bin/python" -m pip install -r "${REQ_FILE}" >/dev/null

echo "[ok] venv ready at ${VENV_DIR}"
