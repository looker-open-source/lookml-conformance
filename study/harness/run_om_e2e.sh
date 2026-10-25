#!/usr/bin/env bash
# Run OpenMetadata's real LookerSource data-model stage end to end (harness/om_e2e.py) on one
# LookML project directory (relative to the evidence folder, e.g. cases/c01_divergence, relative to
# the caller's cwd, or absolute). Prints JSON: data models created + lineage edges.
# (om_e2e.py resolves its argument itself; we resolve too so cwd-relative paths work after the cd.)
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <lookml project dir>" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OM_ROOT="${OM_ROOT:-$HOME/work/OpenMetadata}"
EVIDENCE="${EVIDENCE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
HARNESS="${HARNESS:-$SCRIPT_DIR}"
ORIG_PWD="$PWD"

p="$1"; shift
case "$p" in
  /*) ;;
  *)
    if [ -e "$ORIG_PWD/$p" ]; then p="$(realpath "$ORIG_PWD/$p")"
    elif [ -e "$EVIDENCE/$p" ]; then p="$(realpath "$EVIDENCE/$p")"
    else echo "run_om_e2e.sh: path not found: $p (tried $ORIG_PWD and $EVIDENCE)" >&2; exit 2
    fi ;;
esac

# node is only needed when EXPLORES_FROM_ORACLE is set, but keep PATH consistent with run_differential.sh.
export PATH="$HOME/bin:$PATH"
# shellcheck disable=SC1091
source "$OM_ROOT/env/bin/activate"
export PYTHONPATH="$HARNESS"
export PYTHONWARNINGS="ignore"
export PYTHONDONTWRITEBYTECODE=1   # keep __pycache__ out of the evidence repo

cd "$EVIDENCE"
exec python "$HARNESS/om_e2e.py" "$p" "$@"
