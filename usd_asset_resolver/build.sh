#!/bin/bash

# 1. Define the paths
PROJECT_BUILD_DIR="/home/kemot/Documents/Dev/MonkePipeline/usd_asset_resolver/build"
USD_INSTALL_DIR="/home/kemot/UsdRoot"

# 2. Build in a temporary subshell
(
    mkdir -p build
    cd build
    # We add CMAKE_PREFIX_PATH here so CMake can find TBB inside UsdRoot
    # OpenSubdiv_DIR points at a shim config (UsdRoot ships the OpenSubdiv
    # libs/headers but no CMake package config of its own)
    cmake .. \
      -Dpxr_DIR="${USD_INSTALL_DIR}" \
      -DCMAKE_PREFIX_PATH="${USD_INSTALL_DIR}" \
      -DOpenSubdiv_DIR="/home/kemot/Documents/Dev/MonkePipeline/usd_asset_resolver/cmake/opensubdiv-shim" \
      -DImath_DIR="/home/kemot/Documents/Dev/MonkePipeline/usd_asset_resolver/cmake/opensubdiv-shim"
      
    cmake --build . --config Release
)

echo "--- MonkeMonke!! Waaghhh!! ---"