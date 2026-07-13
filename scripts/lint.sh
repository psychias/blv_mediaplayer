#!/usr/bin/env bash
# Lint with ruff.
set -euo pipefail
cd "$(dirname "$0")/.."
exec ruff check src tests "$@"
