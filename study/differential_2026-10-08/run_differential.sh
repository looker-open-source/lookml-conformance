#!/usr/bin/env bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Run the OpenMetadata before/after differential (harness/differential.py) against one or more
# LookML project directories. Paths may be relative to the evidence folder (e.g. cases/c01_divergence),
# relative to the caller's cwd, or absolute (e.g. ~/work/blocks/<repo>). Prints JSON.
#
# NOTE: arguments are resolved to ABSOLUTE paths before being handed to the harness. OpenMetadata's
# LocalReader.read() computes `base_path / path` where `path` already starts with base_path; that is
# harmless for absolute base paths (pathlib drops the left operand) but doubles a relative one, so the
# parsers silently see zero files when given `cases/...` directly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OM_ROOT="${OM_ROOT:-$HOME/work/OpenMetadata}"
EVIDENCE="${EVIDENCE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
HARNESS="${HARNESS:-$(cd "$SCRIPT_DIR/../harness" && pwd)}"
ORIG_PWD="$PWD"

resolve() {
  local p="$1"
  case "$p" in
    /*) printf '%s\n' "$p" ;;
    *)
      if [ -e "$ORIG_PWD/$p" ]; then
        realpath "$ORIG_PWD/$p"
      elif [ -e "$EVIDENCE/$p" ]; then
        realpath "$EVIDENCE/$p"
      else
        echo "run_differential.sh: path not found: $p (tried $ORIG_PWD and $EVIDENCE)" >&2
        exit 2
      fi
      ;;
  esac
}

ARGS=()
for a in "$@"; do ARGS+=("$(resolve "$a")"); done

# node (oracle_full.js) must be on PATH; npm/npx live in $HOME/bin on this machine.
export PATH="$HOME/bin:$PATH"
# shellcheck disable=SC1091
source "$OM_ROOT/env/bin/activate"
export PYTHONPATH="$HARNESS"
# Keep noisy, irrelevant warnings (google.api_core EOL notice, pydantic shadowing) out of stderr.
export PYTHONWARNINGS="ignore"
export PYTHONDONTWRITEBYTECODE=1   # keep __pycache__ out of the evidence repo

cd "$EVIDENCE"
exec python "$HARNESS/differential.py" "${ARGS[@]}"
