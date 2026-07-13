#!/usr/bin/env bash
# Run the test suite (no GPU, no network).
set -euo pipefail
cd "$(dirname "$0")/.."
exec pytest "$@"
