#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/bench_common.sh"

SLEEP_SECS="${1:-2}"
cleanup_known_benchmark_orphans "${SLEEP_SECS}"
echo "[ok] cleaned known benchmark orphans"
