#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON:-python3}"
if [[ -x "${project_root}/.venv/bin/python" ]]; then
  python_bin="${project_root}/.venv/bin/python"
fi

PYTHONPATH="${project_root}${PYTHONPATH:+:${PYTHONPATH}}" \
  "${python_bin}" "${project_root}/tests/smoke_test.py"
