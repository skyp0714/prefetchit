#!/usr/bin/env bash

FLAT_CODEGEN_ROOT="${FLAT_CODEGEN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PREFETCHIT_ROOT="${PREFETCHIT_ROOT:-$(cd "${FLAT_CODEGEN_ROOT}/.." && pwd)}"
export FLAT_CODEGEN_ROOT PREFETCHIT_ROOT
