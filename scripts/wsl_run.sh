#!/usr/bin/env bash
# Run a pipeline command under WSL/Linux with a user-level venv and a bundled JRE
# (jdk4py), so no sudo / system Java is needed. Spark on native Windows needs
# Hadoop winutils binaries; running it on Linux avoids that entirely.
#
# One-time setup (inside WSL):
#   python3 -m venv ~/cogvenv
#   ~/cogvenv/bin/pip install jdk4py -r requirements-data.txt
#
# Usage (from Windows):
#   wsl -d Ubuntu-24.04 -- bash scripts/wsl_run.sh make all
#   wsl -d Ubuntu-24.04 -- bash scripts/wsl_run.sh python -m pipeline.run_pipeline --root pipeline_data
set -euo pipefail
cd "$(dirname "$0")/.."

VENV="${COG_VENV:-$HOME/cogvenv}"
export PATH="$VENV/bin:/usr/local/bin:/usr/bin:/bin"
JAVA_HOME="$(python -c 'import jdk4py; print(jdk4py.JAVA_HOME)')"
export JAVA_HOME PATH="$JAVA_HOME/bin:$PATH"
export PYTHONPATH="$PWD" PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1

if [ "${1:-}" = "make" ]; then
  shift
  exec make PY=python "$@"
fi
exec "$@"
