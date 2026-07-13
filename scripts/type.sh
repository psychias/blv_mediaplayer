#!/usr/bin/env bash
# Type-check with mypy (strict, configured in pyproject.toml).
set -euo pipefail
cd "$(dirname "$0")/.."
exec mypy "$@"
