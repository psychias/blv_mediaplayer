#!/usr/bin/env bash
# Run the Phase 1 mock demo: produces a length-matched .wav + .vtt + manifest.
set -euo pipefail
cd "$(dirname "$0")/.."
exec ladpipe run --mock --demo "$@"
