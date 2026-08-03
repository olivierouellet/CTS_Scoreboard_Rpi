#!/usr/bin/env bash
# Quick re-run of the install script with the server role pre-selected.
# Usage: bash reinstall.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec bash install.sh "$@"
