#!/bin/bash

# Builds monke_resolver for Blender and usdview.
# USD_INSTALL_DIR must be the OpenUSD install those apps load at runtime
# (see the README: the plugin isn't portable across USD builds).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USD_INSTALL_DIR="${USD_INSTALL_DIR:-$HOME/UsdRoot}"
SHIM_DIR="${SCRIPT_DIR}/cmake/opensubdiv-shim"

if [ ! -d "$USD_INSTALL_DIR" ]; then
    echo "ERROR: ${USD_INSTALL_DIR} not found. Set USD_INSTALL_DIR to your OpenUSD install." >&2
    exit 1
fi

(
    mkdir -p "${SCRIPT_DIR}/build"
    cd "${SCRIPT_DIR}/build"
    # CMAKE_PREFIX_PATH lets CMake find TBB inside the USD install.
    # OpenSubdiv_DIR / Imath_DIR point at shim configs: the USD install ships
    # those libs and headers but no CMake package config of its own
    cmake "$SCRIPT_DIR" \
      -Dpxr_DIR="${USD_INSTALL_DIR}" \
      -DCMAKE_PREFIX_PATH="${USD_INSTALL_DIR}" \
      -DOpenSubdiv_DIR="${SHIM_DIR}" \
      -DImath_DIR="${SHIM_DIR}"

    cmake --build . --config Release
)

echo "--- MonkeMonke!! Waaghhh!! ---"
