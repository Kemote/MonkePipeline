#!/bin/bash

# 1. Define the paths
PROJECT_BUILD_DIR="/home/kemot/Documents/Dev/MonkePipeline/usd_asset_resolver/build"
USD_INSTALL_DIR="/home/kemot/USD"

# 2. Build in a temporary subshell
(
    mkdir -p build
    cd build
    # We add CMAKE_PREFIX_PATH here so CMake can find TBB inside UsdRoot
    cmake .. \
      -Dpxr_DIR="${USD_INSTALL_DIR}" \
      -DCMAKE_PREFIX_PATH="${USD_INSTALL_DIR}"
      
    cmake --build . --config Release
)

echo "--- MonkeMonke!! Waaghhh!! ---"